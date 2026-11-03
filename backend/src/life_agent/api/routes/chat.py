"""Selected shopping-task chat turn endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import SQLAlchemyError

from life_agent.api.dependencies import CurrentUser, Database
from life_agent.api.routes.auth import require_trusted_origin
from life_agent.modules.chat.schemas import TaskChatTurnCreate, TaskChatTurnResponse
from life_agent.modules.chat.service import (
    ChatTurnConflictError,
    ChatTurnNotFoundError,
    submit_turn,
)
from life_agent.modules.conversations.schemas import MessageResponse
from life_agent.modules.runs.schemas import RunResponse
from life_agent.modules.tasks.consistency import GoalConflictError
from life_agent.modules.tasks.schemas import TaskResponse

router = APIRouter(prefix="/conversations")


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="购物任务或对话不存在。")


def _task_response(turn) -> TaskResponse:
    return TaskResponse.model_validate(
        {
            "id": turn.task.id,
            "conversation_id": turn.task.conversation_id,
            "domain": turn.task.domain,
            "goal": turn.goal,
            "current_revision": turn.task.current_revision,
            "conditions": turn.conditions,
            "goal_conflicts": turn.goal_conflicts or None,
            "goal_resolution": turn.goal_resolution,
            "goal_legacy": turn.goal_legacy,
            "created_at": turn.task.created_at,
            "updated_at": turn.task.updated_at,
        }
    )


def _response(turn) -> TaskChatTurnResponse:
    return TaskChatTurnResponse(
        message=MessageResponse.model_validate(turn.message),
        run=RunResponse.model_validate(turn.run),
        task=_task_response(turn),
        assistant_message=(
            MessageResponse.model_validate(turn.assistant_message)
            if turn.assistant_message is not None
            else None
        ),
    )


@router.post(
    "/{conversation_id}/tasks/{task_id}/turns",
    response_model=TaskChatTurnResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_trusted_origin)],
)
def submit(
    conversation_id: uuid.UUID,
    task_id: uuid.UUID,
    body: TaskChatTurnCreate,
    response: Response,
    db: Database,
    current_user: CurrentUser,
) -> TaskChatTurnResponse:
    try:
        turn = submit_turn(
            db,
            current_user.id,
            conversation_id,
            body.client_turn_id,
            body.content.strip(),
            task_id,
            body.expected_revision,
        )
    except ChatTurnNotFoundError as exc:
        raise _not_found() from exc
    except ChatTurnConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail="回合幂等键、任务版本或消息状态发生冲突，请读取最新任务后重试。",
        ) from exc
    except GoalConflictError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"message": str(exc), "goal_conflicts": exc.conflicts},
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="购物对话暂时不可用。") from exc
    if not turn.created:
        response.status_code = status.HTTP_200_OK
    return _response(turn)
