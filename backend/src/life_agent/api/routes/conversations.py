"""Private conversation and user-authored message endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import SQLAlchemyError

from life_agent.api.dependencies import CurrentUser, Database
from life_agent.api.routes.auth import require_trusted_origin
from life_agent.modules.conversations.schemas import (
    ConversationCreate,
    ConversationList,
    ConversationResponse,
    ConversationUpdate,
    MessageCreate,
    MessageList,
    MessageResponse,
)
from life_agent.modules.conversations.service import (
    ClientMessageConflictError,
    ConversationNotFoundError,
    append_message,
    create_conversation,
    get_conversation,
    list_conversations,
    list_messages,
    update_conversation_title,
)

router = APIRouter(prefix="/conversations")
PageOffset = Annotated[int, Query(ge=0, le=1_000_000)]
PageLimit = Annotated[int, Query(ge=1, le=100)]


def not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="对话不存在。")


def storage_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="对话存储暂时不可用。")


@router.post(
    "",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_trusted_origin)],
)
def create(
    body: ConversationCreate, db: Database, current_user: CurrentUser
) -> ConversationResponse:
    try:
        conversation = create_conversation(db, current_user.id, body.title)
    except SQLAlchemyError as exc:
        raise storage_unavailable() from exc
    return ConversationResponse.model_validate(conversation)


@router.get("", response_model=ConversationList)
def list_all(
    db: Database,
    current_user: CurrentUser,
    offset: PageOffset = 0,
    limit: PageLimit = 50,
) -> ConversationList:
    try:
        items = list_conversations(db, current_user.id, offset, limit)
    except SQLAlchemyError as exc:
        raise storage_unavailable() from exc
    return ConversationList(items=items, offset=offset, limit=limit)


@router.get("/{conversation_id}", response_model=ConversationResponse)
def get_one(
    conversation_id: uuid.UUID, db: Database, current_user: CurrentUser
) -> ConversationResponse:
    try:
        conversation = get_conversation(db, current_user.id, conversation_id)
    except ConversationNotFoundError as exc:
        raise not_found() from exc
    except SQLAlchemyError as exc:
        raise storage_unavailable() from exc
    return ConversationResponse.model_validate(conversation)


@router.patch(
    "/{conversation_id}",
    response_model=ConversationResponse,
    dependencies=[Depends(require_trusted_origin)],
)
def update(
    conversation_id: uuid.UUID,
    body: ConversationUpdate,
    db: Database,
    current_user: CurrentUser,
) -> ConversationResponse:
    try:
        conversation = update_conversation_title(
            db, current_user.id, conversation_id, body.title
        )
    except ConversationNotFoundError as exc:
        raise not_found() from exc
    except SQLAlchemyError as exc:
        raise storage_unavailable() from exc
    return ConversationResponse.model_validate(conversation)


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_trusted_origin)],
)
def add_message(
    conversation_id: uuid.UUID,
    body: MessageCreate,
    response: Response,
    db: Database,
    current_user: CurrentUser,
) -> MessageResponse:
    try:
        result = append_message(
            db,
            current_user.id,
            conversation_id,
            body.client_message_id,
            body.content,
        )
    except ConversationNotFoundError as exc:
        raise not_found() from exc
    except ClientMessageConflictError as exc:
        raise HTTPException(
            status_code=409, detail="客户端消息 ID 已用于不同内容。"
        ) from exc
    except SQLAlchemyError as exc:
        raise storage_unavailable() from exc
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return MessageResponse.model_validate(result.message)


@router.get("/{conversation_id}/messages", response_model=MessageList)
def get_messages(
    conversation_id: uuid.UUID,
    db: Database,
    current_user: CurrentUser,
    offset: PageOffset = 0,
    limit: PageLimit = 100,
) -> MessageList:
    try:
        items = list_messages(db, current_user.id, conversation_id, offset, limit)
    except ConversationNotFoundError as exc:
        raise not_found() from exc
    except SQLAlchemyError as exc:
        raise storage_unavailable() from exc
    return MessageList(items=items, offset=offset, limit=limit)