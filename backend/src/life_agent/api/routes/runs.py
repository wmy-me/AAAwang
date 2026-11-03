"""Private persistent run and event endpoints."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from time import monotonic
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from life_agent.api.dependencies import CurrentUser, Database
from life_agent.api.routes.auth import require_trusted_origin
from life_agent.core.config import Settings, get_settings
from life_agent.modules.runs.schemas import (
    RunConflictResponse,
    RunCreate,
    RunEventList,
    RunEventResponse,
    RunList,
    RunResponse,
    ShoppingArtifactsResponse,
    ShoppingCandidateResponse,
    ShoppingPlanResponse,
    ShoppingRunResultResponse,
)
from life_agent.modules.runs.service import (
    IdempotencyConflictError,
    RunNotFoundError,
    RunRevisionConflictError,
    cancel_run,
    create_run,
    get_run,
    get_shopping_artifacts,
    get_shopping_result,
    list_events,
    list_runs,
)

router = APIRouter()
PageOffset = Annotated[int, Query(ge=0, le=1_000_000)]
PageLimit = Annotated[int, Query(ge=1, le=100)]
EventCursor = Annotated[int, Query(ge=0, le=1_000_000_000)]


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
            db,
            current_user.id,
            task_id,
            body.expected_revision,
            body.idempotency_key,
            body.execution_type,
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
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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


@router.get("/runs/{run_id}/result", response_model=ShoppingRunResultResponse)
def result(
    run_id: uuid.UUID, db: Database, current_user: CurrentUser
) -> ShoppingRunResultResponse:
    try:
        value = get_shopping_result(db, current_user.id, run_id)
    except RunNotFoundError as exc:
        raise _not_found() from exc
    except SQLAlchemyError as exc:
        raise _storage_unavailable() from exc
    return ShoppingRunResultResponse.model_validate(value)


@router.get("/runs/{run_id}/shopping-artifacts", response_model=ShoppingArtifactsResponse)
def shopping_artifacts(
    run_id: uuid.UUID, db: Database, current_user: CurrentUser
) -> ShoppingArtifactsResponse:
    try:
        candidates, plan = get_shopping_artifacts(db, current_user.id, run_id)
    except RunNotFoundError as exc:
        raise _not_found() from exc
    except SQLAlchemyError as exc:
        raise _storage_unavailable() from exc
    return ShoppingArtifactsResponse(
        candidates=[ShoppingCandidateResponse.model_validate(item) for item in candidates],
        plan=ShoppingPlanResponse.model_validate(plan) if plan is not None else None,
    )


@router.get("/runs/{run_id}/events", response_model=RunEventList)
def events(
    run_id: uuid.UUID,
    db: Database,
    current_user: CurrentUser,
    after: EventCursor = 0,
    limit: PageLimit = 100,
) -> RunEventList:
    try:
        items = list_events(db, current_user.id, run_id, after, limit)
    except RunNotFoundError as exc:
        raise _not_found() from exc
    except SQLAlchemyError as exc:
        raise _storage_unavailable() from exc
    next_after = items[-1].sequence if items else after
    return RunEventList(
        items=[RunEventResponse.model_validate(item) for item in items],
        after=after,
        limit=limit,
        next_after=next_after,
    )


def _parse_last_event_id(value: str | None) -> int:
    if value is None or value == "":
        return 0
    if not value.isascii() or not value.isdecimal():
        raise HTTPException(status_code=422, detail="Last-Event-ID 必须是非负整数。")
    cursor = int(value)
    if cursor > 1_000_000_000:
        raise HTTPException(status_code=422, detail="Last-Event-ID 超出允许范围。")
    return cursor


async def _event_stream(
    request: Request,
    db: Database,
    owner_id: uuid.UUID,
    run_id: uuid.UUID,
    cursor: int,
    settings: Settings,
) -> AsyncIterator[ServerSentEvent]:
    last_heartbeat = monotonic()
    while True:
        if await request.is_disconnected():
            return
        try:
            events = list_events(
                db, owner_id, run_id, cursor, settings.run_events_batch_size
            )
            run = get_run(db, owner_id, run_id)
        except (RunNotFoundError, SQLAlchemyError):
            return
        for event in events:
            cursor = event.sequence
            yield ServerSentEvent(
                id=str(event.sequence), event=event.event_type, data=event.payload
            )
        if run.status in {"completed", "failed", "cancelled"} and not events:
            return
        if monotonic() - last_heartbeat >= settings.run_events_heartbeat_seconds:
            yield ServerSentEvent(comment="heartbeat")
            last_heartbeat = monotonic()
        await asyncio.sleep(settings.run_events_poll_seconds)


@router.get(
    "/runs/{run_id}/events/stream",
    response_class=EventSourceResponse,
    response_model=None,
)
async def event_stream(
    run_id: uuid.UUID,
    request: Request,
    db: Database,
    current_user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
    after: EventCursor | None = None,
) -> AsyncIterator[ServerSentEvent]:
    try:
        get_run(db, current_user.id, run_id)
        header_cursor = _parse_last_event_id(request.headers.get("last-event-id"))
        cursor = after if after is not None else header_cursor
        if after is not None and header_cursor > 0 and header_cursor != after:
            raise HTTPException(status_code=422, detail="游标参数不一致。")
    except RunNotFoundError as exc:
        raise _not_found() from exc
    except SQLAlchemyError as exc:
        raise _storage_unavailable() from exc
    async for event in _event_stream(
        request, db, current_user.id, run_id, cursor, settings
    ):
        yield event