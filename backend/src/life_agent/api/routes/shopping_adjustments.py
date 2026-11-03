"""Private shopping-plan adjustment endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from life_agent.api.dependencies import CurrentUser, Database
from life_agent.api.routes.auth import require_trusted_origin
from life_agent.modules.runs.service import RunNotFoundError
from life_agent.modules.shopping_adjustments.schemas import (
    ShoppingAdjustmentCreate,
    ShoppingAdjustmentList,
    ShoppingAdjustmentResponse,
)
from life_agent.modules.shopping_adjustments.service import (
    AdjustmentConflictError,
    AdjustmentIdempotencyConflictError,
    create_adjustment,
    list_adjustments,
)

router = APIRouter()


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="任务、run 或候选不存在。")


def _storage_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="方案调整存储暂时不可用。")


@router.post(
    "/tasks/{task_id}/shopping-adjustments",
    response_model=ShoppingAdjustmentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_trusted_origin)],
)
def create(
    task_id: uuid.UUID,
    body: ShoppingAdjustmentCreate,
    db: Database,
    current_user: CurrentUser,
) -> ShoppingAdjustmentResponse:
    try:
        adjustment = create_adjustment(
            db,
            current_user.id,
            task_id,
            base_run_id=body.base_run_id,
            expected_revision=body.expected_revision,
            expected_adjustment_version=body.expected_adjustment_version,
            client_request_id=body.client_request_id,
            items=[(item.candidate_id, item.package_quantity) for item in body.items],
        )
    except RunNotFoundError as exc:
        raise _not_found() from exc
    except AdjustmentConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "任务条件或方案调整版本冲突。",
                "current_adjustment_version": exc.current_version,
            },
        ) from exc
    except AdjustmentIdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail="幂等键已用于其他调整请求。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="调整请求发生并发冲突，请刷新后重试。") from exc
    except SQLAlchemyError as exc:
        raise _storage_unavailable() from exc
    return ShoppingAdjustmentResponse.model_validate(adjustment)


@router.get(
    "/tasks/{task_id}/shopping-adjustments",
    response_model=ShoppingAdjustmentList,
)
def history(
    task_id: uuid.UUID,
    db: Database,
    current_user: CurrentUser,
) -> ShoppingAdjustmentList:
    try:
        items = list_adjustments(db, current_user.id, task_id)
    except RunNotFoundError as exc:
        raise _not_found() from exc
    except SQLAlchemyError as exc:
        raise _storage_unavailable() from exc
    current_version = items[0].version if items else 0
    return ShoppingAdjustmentList(
        items=[ShoppingAdjustmentResponse.model_validate(item) for item in items],
        current_version=current_version,
    )
