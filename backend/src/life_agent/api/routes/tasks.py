"""Private task and immutable condition revision endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError

from life_agent.api.dependencies import CurrentUser, Database
from life_agent.api.routes.auth import require_trusted_origin
from life_agent.modules.tasks.schemas import (
    RevisionConflictResponse,
    TaskCreate,
    TaskList,
    TaskResponse,
    TaskRevisionCreate,
    TaskRevisionList,
    TaskRevisionResponse,
    validate_conditions,
)
from life_agent.modules.tasks.service import (
    RevisionConflictError,
    TaskNotFoundError,
    TaskView,
    create_revision,
    create_task,
    get_task,
    list_revisions,
    list_tasks,
)

router = APIRouter()
PageOffset = Annotated[int, Query(ge=0, le=1_000_000)]
PageLimit = Annotated[int, Query(ge=1, le=100)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="任务或对话不存在。")


def _storage_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="任务存储暂时不可用。")


def _task_response(view: TaskView) -> TaskResponse:
    task = view.task
    return TaskResponse(
        id=task.id,
        conversation_id=task.conversation_id,
        domain=task.domain,
        goal=task.goal,
        current_revision=task.current_revision,
        conditions=view.conditions,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


@router.post(
    "/conversations/{conversation_id}/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_trusted_origin)],
)
def create(
    conversation_id: uuid.UUID,
    body: TaskCreate,
    db: Database,
    current_user: CurrentUser,
) -> TaskResponse:
    try:
        view = create_task(
            db,
            current_user.id,
            conversation_id,
            body.domain,
            body.goal,
            body.conditions,
            body.change_note,
        )
    except TaskNotFoundError as exc:
        raise _not_found() from exc
    except SQLAlchemyError as exc:
        raise _storage_unavailable() from exc
    return _task_response(view)


@router.get("/conversations/{conversation_id}/tasks", response_model=TaskList)
def list_for_conversation(
    conversation_id: uuid.UUID,
    db: Database,
    current_user: CurrentUser,
    offset: PageOffset = 0,
    limit: PageLimit = 50,
) -> TaskList:
    try:
        items = list_tasks(db, current_user.id, conversation_id, offset, limit)
    except TaskNotFoundError as exc:
        raise _not_found() from exc
    except SQLAlchemyError as exc:
        raise _storage_unavailable() from exc
    return TaskList(
        items=[_task_response(item) for item in items], offset=offset, limit=limit
    )


@router.get("/tasks/{task_id}", response_model=TaskResponse)
def get_one(task_id: uuid.UUID, db: Database, current_user: CurrentUser) -> TaskResponse:
    try:
        view = get_task(db, current_user.id, task_id)
    except TaskNotFoundError as exc:
        raise _not_found() from exc
    except SQLAlchemyError as exc:
        raise _storage_unavailable() from exc
    return _task_response(view)


@router.get("/tasks/{task_id}/revisions", response_model=TaskRevisionList)
def get_revisions(
    task_id: uuid.UUID,
    db: Database,
    current_user: CurrentUser,
    offset: PageOffset = 0,
    limit: PageLimit = 100,
) -> TaskRevisionList:
    try:
        items = list_revisions(db, current_user.id, task_id, offset, limit)
    except TaskNotFoundError as exc:
        raise _not_found() from exc
    except SQLAlchemyError as exc:
        raise _storage_unavailable() from exc
    return TaskRevisionList(items=items, offset=offset, limit=limit)


@router.post(
    "/tasks/{task_id}/revisions",
    response_model=TaskRevisionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_trusted_origin)],
    responses={409: {"model": RevisionConflictResponse}},
)
def revise(
    task_id: uuid.UUID,
    body: TaskRevisionCreate,
    db: Database,
    current_user: CurrentUser,
) -> TaskRevisionResponse:
    try:
        task = get_task(db, current_user.id, task_id).task
        conditions = validate_conditions(task.domain, body.conditions)
        change_note = body.change_note.strip() or None if body.change_note else None
        revision = create_revision(
            db,
            current_user.id,
            task_id,
            body.expected_revision,
            conditions,
            change_note,
        )
    except TaskNotFoundError as exc:
        raise _not_found() from exc
    except RevisionConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "任务条件版本冲突。",
                "current_revision": exc.current_revision,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise _storage_unavailable() from exc
    return TaskRevisionResponse.model_validate(revision)