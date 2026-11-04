"""Private dynamic task form endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError

from life_agent.api.dependencies import CurrentUser, Database
from life_agent.api.routes.auth import require_trusted_origin
from life_agent.modules.forms.schemas import DynamicFormProposalResponse, FormSubmit
from life_agent.modules.forms.service import (
    FormNotFoundError,
    FormValidationError,
    confirm_proposal,
    get_or_create_proposal,
)
from life_agent.modules.tasks.schemas import (
    RevisionConflictResponse,
    TaskRevisionResponse,
)
from life_agent.modules.tasks.service import RevisionConflictError

router = APIRouter()


@router.get("/tasks/{task_id}/form", response_model=DynamicFormProposalResponse)
def get_form(task_id: uuid.UUID, db: Database, current_user: CurrentUser):
    try:
        return get_or_create_proposal(db, current_user.id, task_id)
    except FormNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务或表单不存在。") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="表单存储暂时不可用。") from exc


@router.post(
    "/tasks/{task_id}/form/submit",
    response_model=TaskRevisionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_trusted_origin)],
    responses={409: {"model": RevisionConflictResponse}},
)
def submit_form(
    task_id: uuid.UUID,
    body: FormSubmit,
    db: Database,
    current_user: CurrentUser,
) -> TaskRevisionResponse:
    try:
        _proposal, revision = confirm_proposal(
            db, current_user.id, task_id, body.proposal_id, body.expected_revision,
            body.client_request_id, body.values
        )
        return TaskRevisionResponse.model_validate(revision)
    except (ValueError, FormValidationError) as exc:
        if isinstance(exc, RevisionConflictError):
            raise HTTPException(status_code=409, detail={"message": "任务条件版本冲突。", "current_revision": exc.current_revision}) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FormNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务或表单不存在。") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="表单存储暂时不可用。") from exc