"""Private dynamic task form endpoints."""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from life_agent.api.dependencies import CurrentUser, Database
from life_agent.api.routes.auth import require_trusted_origin
from life_agent.db.models import Conversation, Message, Run, Task
from life_agent.modules.conversations.schemas import MessageResponse
from life_agent.modules.forms.schemas import (
    DynamicFormProposalResponse,
    FormSubmit,
    FormSubmitResponse,
)
from life_agent.modules.forms.service import (
    FormNotFoundError,
    FormValidationError,
    confirm_proposal,
    get_or_create_proposal,
    get_proposal,
)
from life_agent.modules.runs.schemas import RunResponse
from life_agent.modules.runs.service import create_run
from life_agent.modules.tasks.schemas import RevisionConflictResponse, TaskResponse
from life_agent.modules.tasks.service import RevisionConflictError, get_task

router = APIRouter()


@router.get("/tasks/{task_id}/form", response_model=DynamicFormProposalResponse)
def get_form(task_id: uuid.UUID, db: Database, current_user: CurrentUser):
    try:
        return get_or_create_proposal(db, current_user.id, task_id)
    except FormNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务或表单不存在。") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="表单存储暂时不可用。") from exc


@router.get(
    "/tasks/{task_id}/form/{proposal_id}",
    response_model=DynamicFormProposalResponse,
)
def get_form_proposal(
    task_id: uuid.UUID,
    proposal_id: uuid.UUID,
    db: Database,
    current_user: CurrentUser,
):
    try:
        return get_proposal(db, current_user.id, task_id, proposal_id)
    except FormNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务或表单不存在。") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="表单存储暂时不可用。") from exc


@router.post(
    "/tasks/{task_id}/form/submit",
    response_model=FormSubmitResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_trusted_origin)],
    responses={409: {"model": RevisionConflictResponse}},
)
def submit_form(
    task_id: uuid.UUID,
    body: FormSubmit,
    db: Database,
    current_user: CurrentUser,
) -> FormSubmitResponse:
    try:
        proposal, revision = confirm_proposal(
            db, current_user.id, task_id, body.proposal_id, body.expected_revision,
            body.client_request_id, body.values, commit=False
        )
        task = db.get(Task, task_id)
        if task is None:
            raise FormNotFoundError
        content = "通过动态表单确认：" + json.dumps(body.values, ensure_ascii=False, sort_keys=True)
        message = db.scalar(
            select(Message).where(
                Message.task_id == task_id,
                Message.client_message_id == body.client_request_id,
                Message.role == "user",
            )
        )
        if message is None:
            conversation = db.get(Conversation, task.conversation_id)
            if conversation is None or conversation.owner_id != current_user.id:
                raise FormNotFoundError
            message = Message(
                conversation_id=task.conversation_id,
                client_message_id=body.client_request_id,
                role="user",
                content=content,
                task_id=task_id,
            )
            db.add(message)
            db.flush()
            run = create_run(
                db,
                current_user.id,
                task_id,
                revision.revision,
                f"form:{body.client_request_id}",
                "capability_decision",
                input_message_id=message.id,
                decision={
                    "kind": "pending",
                    "capability_ids": [],
                    "decision_source": "deepseek_structured_worker",
                    "form_proposal_id": str(proposal.id),
                },
                commit=False,
            )
            message.run_id = run.id
            conversation.updated_at = revision.created_at
            db.commit()
            db.refresh(message)
            db.refresh(run)
        else:
            run = db.scalar(select(Run).where(Run.input_message_id == message.id))
            if run is None:
                raise FormValidationError("表单消息缺少关联 Run。")
        view = get_task(db, current_user.id, task_id)
        task_response = TaskResponse.model_validate({
            "id": view.task.id,
            "conversation_id": view.task.conversation_id,
            "domain": view.task.domain,
            "goal": view.goal,
            "current_revision": view.task.current_revision,
            "conditions": view.conditions,
            "goal_conflicts": view.goal_conflicts or None,
            "goal_resolution": view.goal_resolution,
            "goal_legacy": view.goal_legacy,
            "created_at": view.task.created_at,
            "updated_at": view.task.updated_at,
        })
        return FormSubmitResponse(
            message=MessageResponse.model_validate(message),
            run=RunResponse.model_validate(run),
            task=task_response,
        )
    except (ValueError, FormValidationError) as exc:
        if isinstance(exc, RevisionConflictError):
            raise HTTPException(status_code=409, detail={"message": "任务条件版本冲突。", "current_revision": exc.current_revision}) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FormNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务或表单不存在。") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="表单存储暂时不可用。") from exc