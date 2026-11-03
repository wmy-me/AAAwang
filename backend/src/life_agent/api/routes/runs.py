"""Private persistent run endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from life_agent.api.dependencies import CurrentUser, Database
from life_agent.api.routes.auth import require_trusted_origin
from life_agent.modules.runs.schemas import (
    RunConflictResponse,
    RunCreate,
    RunList,
    RunResponse,
)
from life_agent.modules.runs.service import (
    IdempotencyConflictError,
    RunNotFoundError,
    RunRevisionConflictError,
    cancel_run,
    create_run,
    get_run,
    list_runs,
)

router = APIRouter()
PageOffset = Annotated[int, Query(ge=0, le=1_000_000)]
PageLimit = Annotated[int, Query(ge=1, le=100)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="任务或 run 不存在。")


def _storage_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="run 存储暂时不可用。")


def _response(run) -> RunResponse:
    return RunResponse.model_validate(run)


@router.post(
    "/tasks/{task_id}/runs",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_trusted_origin)],
    responses={409: {"model": RunConflictResponse}},
)
def create(
    task_id: uuid.UUID, body: RunCreate, db: Database, current_user: CurrentUser
) -> RunResponse:
    try:
        run = create_run(
            db, current_user.id, task_id, body.expected_revision, body.idempotency_key
        )
    except RunNotFoundError as exc:
        raise _not_found() from exc
    except RunRevisionConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": "任务条件版本冲突。", "current_revision": exc.current_revision},
        ) from exc
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail="幂等键已用于其他 run 请求。") from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="幂等键已用于其他 run 请求。") from exc
    except SQLAlchemyError as exc:
        raise _storage_unavailable() from exc
    return _response(run)


@router.get("/tasks/{task_id}/runs", response_model=RunList)
def list_for_task(
    task_id: uuid.UUID,
    db: Database,
    current_user: CurrentUser,
    offset: PageOffset = 0,
    limit: PageLimit = 50,
) -> RunList:
    try:
        items = list_runs(db, current_user.id, task_id, offset, limit)
    except RunNotFoundError as exc:
        raise _not_found() from exc
    except SQLAlchemyError as exc:
        raise _storage_unavailable() from exc
    return RunList(items=[_response(item) for item in items], offset=offset, limit=limit)


@router.get("/runs/{run_id}", response_model=RunResponse)
def get_one(run_id: uuid.UUID, db: Database, current_user: CurrentUser) -> RunResponse:
    try:
        run = get_run(db, current_user.id, run_id)
    except RunNotFoundError as exc:
        raise _not_found() from exc
    except SQLAlchemyError as exc:
        raise _storage_unavailable() from exc
    return _response(run)


@router.post(
    "/runs/{run_id}/cancel",
    response_model=RunResponse,
    dependencies=[Depends(require_trusted_origin)],
)
def cancel(run_id: uuid.UUID, db: Database, current_user: CurrentUser) -> RunResponse:
    try:
        run = cancel_run(db, current_user.id, run_id)
    except RunNotFoundError as exc:
        raise _not_found() from exc
    except SQLAlchemyError as exc:
        raise _storage_unavailable() from exc
    return _response(run)