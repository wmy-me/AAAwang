"""Owner-scoped proposal generation and atomic form confirmation."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from life_agent.db.models import Conversation, DynamicFormProposal, Task, TaskRevision
from life_agent.modules.tasks.schemas import Conditions, validate_conditions
from life_agent.modules.tasks.service import RevisionConflictError, create_revision


class FormNotFoundError(LookupError):
    pass


class FormValidationError(ValueError):
    pass


@dataclass(frozen=True)
class FormFieldSpec:
    id: str
    control: str
    label: str
    reason: str
    unit: str | None = None
    required: bool = False
    min_value: int | float | None = None
    max_value: int | float | None = None


def _owned_task(db: Session, owner_id: uuid.UUID, task_id: uuid.UUID) -> Task:
    task = db.scalar(
        select(Task).join(Conversation).where(
            Task.id == task_id, Conversation.owner_id == owner_id
        )
    )
    if task is None:
        raise FormNotFoundError
    return task


def _shopping_specs(snapshot: TaskRevision) -> list[FormFieldSpec]:
    current = dict(snapshot.conditions)
    specs = [
        FormFieldSpec("item", "short_text", "想买什么", "帮助缩小商品探索范围"),
        FormFieldSpec("people", "number", "覆盖人数", "只有需要覆盖人数时才作为方案约束", "人", False, 1, 100000),
        FormFieldSpec("quantity", "number", "数量", "便于估算需要购买的件数", "件", False, 1, 100000),
        FormFieldSpec("budget", "money", "目标预算", "用于预算复算；不填写时不假设默认金额", "元", False, 0.01, 100000000),
    ]
    return [spec for spec in specs if spec.id not in current]


def _schema(specs: list[FormFieldSpec]) -> list[dict[str, object]]:
    return [
        {
            "id": spec.id,
            "control": spec.control,
            "label": spec.label,
            "reason": spec.reason,
            "required": spec.required,
            **({"unit": spec.unit} if spec.unit else {}),
            **({"min_value": spec.min_value} if spec.min_value is not None else {}),
            **({"max_value": spec.max_value} if spec.max_value is not None else {}),
        }
        for spec in specs
    ]


def get_or_create_proposal(
    db: Session, owner_id: uuid.UUID, task_id: uuid.UUID
) -> DynamicFormProposal:
    task = _owned_task(db, owner_id, task_id)
    snapshot = db.scalar(
        select(TaskRevision).where(
            TaskRevision.task_id == task.id,
            TaskRevision.revision == task.current_revision,
        )
    )
    if snapshot is None:
        raise FormNotFoundError
    existing = db.scalar(
        select(DynamicFormProposal).where(
            DynamicFormProposal.task_id == task.id,
            DynamicFormProposal.task_revision_id == snapshot.id,
        )
    )
    if existing is not None:
        return existing
    proposal = DynamicFormProposal(
        task_id=task.id,
        task_revision_id=snapshot.id,
        revision=snapshot.revision,
        schema=_schema(_shopping_specs(snapshot)),
        client_request_id=f"proposal:{snapshot.id}",
        created_at=datetime.now(UTC),
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return proposal


def _validate_values(
    proposal: DynamicFormProposal, values: dict[str, object]
) -> Conditions:
    fields = {field["id"]: field for field in proposal.schema}
    unknown = set(values) - fields.keys()
    if unknown:
        raise FormValidationError(f"表单包含未知字段: {', '.join(sorted(unknown))}。")
    missing = {
        str(field["id"])
        for field in proposal.schema
        if field.get("required") and field["id"] not in values
    }
    if missing:
        raise FormValidationError(f"缺少必填字段: {', '.join(sorted(missing))}。")
    conditions: Conditions = {}
    for field_id, value in values.items():
        field = fields[field_id]
        control = field["control"]
        if control == "short_text" and (not isinstance(value, str) or not value.strip()):
            raise FormValidationError(f"{field_id} 必须是非空文本。")
        if control in {"number", "money"}:
            if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
                raise FormValidationError(f"{field_id} 必须是正数。")
            if control == "number" and not isinstance(value, int):
                raise FormValidationError(f"{field_id} 必须是正整数。")
            if field.get("min_value") is not None and value < field["min_value"]:
                raise FormValidationError(f"{field_id} 超出允许范围。")
            if field.get("max_value") is not None and value > field["max_value"]:
                raise FormValidationError(f"{field_id} 超出允许范围。")
        conditions[field_id] = value
    try:
        return validate_conditions("shopping", conditions)
    except ValueError as exc:
        raise FormValidationError(str(exc)) from exc


def confirm_proposal(
    db: Session,
    owner_id: uuid.UUID,
    task_id: uuid.UUID,
    proposal_id: uuid.UUID,
    expected_revision: int,
    client_request_id: str,
    values: dict[str, object],
) -> tuple[DynamicFormProposal, TaskRevision]:
    task = _owned_task(db, owner_id, task_id)
    proposal = db.scalar(
        select(DynamicFormProposal).where(
            DynamicFormProposal.id == proposal_id,
            DynamicFormProposal.task_id == task.id,
        )
    )
    if proposal is None:
        raise FormNotFoundError
    if proposal.status == "confirmed" and proposal.client_request_id == client_request_id:
        if proposal.confirmed_values != values:
            raise FormValidationError("相同请求 ID 不能提交不同的字段值。")
        revision = db.scalar(
            select(TaskRevision).where(
                TaskRevision.task_id == task.id,
                TaskRevision.revision == proposal.revision + 1,
            )
        )
        if revision is None:
            raise FormValidationError("表单确认结果不完整。")
        return proposal, revision
    if task.current_revision != expected_revision or proposal.revision != expected_revision:
        raise RevisionConflictError(task.current_revision)
    conditions = _validate_values(proposal, values)
    revision = create_revision(
        db,
        owner_id,
        task.id,
        expected_revision,
        None,
        conditions,
        "确认动态表单字段",
        commit=False,
    )
    proposal.status = "confirmed"
    proposal.confirmed_values = dict(values)
    proposal.client_request_id = client_request_id
    proposal.confirmed_at = datetime.now(UTC)
    db.commit()
    db.refresh(proposal)
    return proposal, revision