"""Owner-scoped proposal generation and atomic form confirmation."""

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from life_agent.db.models import Conversation, DynamicFormProposal, Task, TaskRevision
from life_agent.modules.forms.schemas import FormField
from life_agent.modules.tasks.schemas import Conditions, validate_conditions
from life_agent.modules.tasks.service import RevisionConflictError, create_revision

logger = logging.getLogger(__name__)


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
    options: tuple[str, ...] = ()


_REGISTERED_FORM_FIELDS = {
    "item": FormFieldSpec("item", "short_text", "想买什么", "帮助缩小商品探索范围"),
    "people": FormFieldSpec("people", "number", "覆盖人数", "只有需要覆盖人数时才作为方案约束", "人", False, 1, 100000),
    "quantity": FormFieldSpec("quantity", "number", "数量", "便于估算需要购买的件数", "件", False, 1, 100000),
    "budget": FormFieldSpec("budget", "money", "目标预算", "用于预算复算；不填写时不假设默认金额", "元", False, 0.01, 100000000),
}
_REGISTERED_FORM_FIELDS_BY_DOMAIN = {
    "shopping": _REGISTERED_FORM_FIELDS | {
        "color": FormFieldSpec("color", "single_select", "偏好颜色", "帮助筛选更符合需求的商品", options=("黑色", "蓝色", "黄色", "红色", "其他")),
        "use_case": FormFieldSpec("use_case", "single_select", "主要用途", "区分通勤、户外和日常使用场景", options=("通勤", "户外", "日常", "运动")),
    },
    "travel": {
        "destination": FormFieldSpec("destination", "location", "城市或地点", "确定活动地点范围"),
        "start_date": FormFieldSpec("start_date", "date", "开始日期", "限定活动开始时间"),
        "end_date": FormFieldSpec("end_date", "date", "结束日期", "限定活动结束时间"),
        "activity_types": FormFieldSpec("activity_types", "multi_select", "活动偏好", "帮助筛选周末活动类型", options=("美食", "展览", "户外", "亲子", "文化")),
    },
}
_CORE_FORM_FIELD_IDS = frozenset(_REGISTERED_FORM_FIELDS)
_RESERVED_DYNAMIC_FIELD_IDS = frozenset(
    {
        "owner_id",
        "task_id",
        "revision",
        "run_id",
        "service_url",
        "tool_name",
        "api_key",
        "secret",
        "password",
        "token",
        "payment",
    }
)
_DYNAMIC_FIELD_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_MAX_DYNAMIC_FIELDS = 8
_MAX_OPTION_COUNT = 12


def _owned_task(db: Session, owner_id: uuid.UUID, task_id: uuid.UUID) -> Task:
    task = db.scalar(
        select(Task).join(Conversation).where(
            Task.id == task_id, Conversation.owner_id == owner_id
        )
    )
    if task is None:
        raise FormNotFoundError
    return task


def _shopping_specs(snapshot: TaskRevision, domain: str = "shopping") -> list[FormFieldSpec]:
    current = dict(snapshot.conditions)
    specs = list(
        (_REGISTERED_FORM_FIELDS if domain == "shopping" else _REGISTERED_FORM_FIELDS_BY_DOMAIN.get(domain, {})).values()
    )
    return [spec for spec in specs if spec.id not in current]


def validate_model_schema(
    raw_schema: object, current_conditions: Conditions, domain: str = "shopping"
) -> list[dict[str, object]]:
    """Validate model suggestions against the bounded form contract."""
    if raw_schema is None:
        return []
    registered_fields = _REGISTERED_FORM_FIELDS_BY_DOMAIN.get(domain, _REGISTERED_FORM_FIELDS)
    if not isinstance(raw_schema, list) or len(raw_schema) > _MAX_DYNAMIC_FIELDS:
        raise FormValidationError("模型表单 schema 必须是有限字段列表。")
    fields: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw_field in raw_schema:
        try:
            field = FormField.model_validate(raw_field)
        except ValueError as exc:
            raise FormValidationError("模型表单字段格式不合法。") from exc
        if (
            field.id in seen
            or field.id in _RESERVED_DYNAMIC_FIELD_IDS
            or not _DYNAMIC_FIELD_ID.fullmatch(field.id)
        ):
            raise FormValidationError("模型表单包含非法、保留或重复字段。")
        if field.id in current_conditions:
            raise FormValidationError("模型表单不能重复要求已确认条件。")
        registered = registered_fields.get(field.id)
        if registered is not None and field.control != registered.control:
            raise FormValidationError("核心字段控件类型不匹配注册能力。")
        unit = field.unit.strip() if isinstance(field.unit, str) else field.unit
        unit = unit or None
        if registered is not None and unit != registered.unit:
            raise FormValidationError("模型表单单位不匹配注册能力。")
        if any(
            character in field.label or character in field.reason
            for character in "<>\x00\n\r"
        ):
            raise FormValidationError("模型表单文本不能包含脚本标记。")
        options = tuple(field.options or ())
        if len(options) > _MAX_OPTION_COUNT or len(set(options)) != len(options) or any(
            not option.strip() or len(option) > 80 or any(character in option for character in "<>")
            for option in options
        ):
            raise FormValidationError("模型表单选项不合法。")
        if field.control in {"single_select", "multi_select"}:
            if not 2 <= len(options) <= _MAX_OPTION_COUNT:
                raise FormValidationError("选择控件必须提供 2–12 个选项。")
        elif options:
            raise FormValidationError("非选择控件不能提供选项。")
        if field.control in {"number", "money"}:
            if field.min_value is not None and field.min_value < 0:
                raise FormValidationError("数字字段最小值不能为负数。")
            if field.max_value is not None and field.max_value > 100000000:
                raise FormValidationError("数字字段最大值超出范围。")
            if (
                field.min_value is not None
                and field.max_value is not None
                and field.min_value > field.max_value
            ):
                raise FormValidationError("数字字段范围无效。")
        elif field.min_value is not None or field.max_value is not None:
            raise FormValidationError("非数字控件不能提供数值范围。")
        seen.add(field.id)
        normalized = field.model_dump(exclude_none=True)
        normalized["unit"] = unit
        if unit is None:
            normalized.pop("unit")
        fields.append(normalized)
    return fields


def persist_model_proposal(
    db: Session,
    task_id: uuid.UUID,
    revision: int,
    raw_schema: object,
) -> DynamicFormProposal | None:
    snapshot = db.scalar(
        select(TaskRevision).where(
            TaskRevision.task_id == task_id, TaskRevision.revision == revision
        )
    )
    if snapshot is None:
        raise FormNotFoundError
    task = db.get(Task, task_id)
    if task is None:
        raise FormNotFoundError
    try:
        schema = validate_model_schema(raw_schema, dict(snapshot.conditions), task.domain)
    except FormValidationError:
        logger.warning(
            "discarding invalid model form schema: task=%s revision=%s",
            task_id,
            revision,
        )
        return None
    proposal = db.scalar(
        select(DynamicFormProposal).where(
            DynamicFormProposal.task_id == task_id,
            DynamicFormProposal.task_revision_id == snapshot.id,
        )
    )
    if proposal is not None and proposal.status == "confirmed":
        return proposal
    if not schema:
        return proposal
    if proposal is None:
        proposal = DynamicFormProposal(
            task_id=task_id,
            task_revision_id=snapshot.id,
            revision=revision,
            client_request_id=f"proposal:{snapshot.id}",
            created_at=datetime.now(UTC),
        )
        db.add(proposal)
    proposal.schema = schema
    proposal.source = "deepseek_structured_worker"
    proposal.status = "pending"
    return proposal


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
            **({"options": list(spec.options)} if spec.options else {}),
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
        schema=_schema(_shopping_specs(snapshot, task.domain)),
        client_request_id=f"proposal:{snapshot.id}",
        created_at=datetime.now(UTC),
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return proposal


def get_proposal(
    db: Session, owner_id: uuid.UUID, task_id: uuid.UUID, proposal_id: uuid.UUID
) -> DynamicFormProposal:
    """Read one owner-scoped proposal, including proposals for old revisions."""
    task = _owned_task(db, owner_id, task_id)
    proposal = db.scalar(
        select(DynamicFormProposal).where(
            DynamicFormProposal.id == proposal_id,
            DynamicFormProposal.task_id == task.id,
        )
    )
    if proposal is None:
        raise FormNotFoundError
    return proposal


def _validate_values(
    proposal: DynamicFormProposal,
    values: dict[str, object],
    base_conditions: Conditions,
    domain: str,
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
    conditions: Conditions = dict(base_conditions)
    for field_id, value in values.items():
        field = fields[field_id]
        control = field["control"]
        if isinstance(value, str) and any(character in value for character in "<>"):
            raise FormValidationError(f"{field_id} 包含不允许的标记字符。")
        if control in {"short_text", "location", "date", "single_select"} and (
            not isinstance(value, str) or not value.strip()
        ):
            raise FormValidationError(f"{field_id} 必须是非空文本。")
        if control == "date":
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise FormValidationError(f"{field_id} 必须是 YYYY-MM-DD 日期。") from exc
        if control == "single_select" and value not in field.get("options", []):
            raise FormValidationError(f"{field_id} 不是允许的选项。")
        if control == "multi_select":
            options = field.get("options", [])
            if (
                not isinstance(value, list)
                or not value
                or len(value) > len(options)
                or len(set(value)) != len(value)
                or any(item not in options for item in value)
            ):
                raise FormValidationError(f"{field_id} 不是允许的多选值。")
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
        return validate_conditions(domain, conditions)
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
    commit: bool = True,
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
    snapshot = db.scalar(
        select(TaskRevision).where(
            TaskRevision.task_id == task.id,
            TaskRevision.revision == proposal.revision,
        )
    )
    if snapshot is None:
        raise FormNotFoundError
    conditions = _validate_values(proposal, values, dict(snapshot.conditions), task.domain)
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
    if commit:
        db.commit()
        db.refresh(proposal)
    return proposal, revision