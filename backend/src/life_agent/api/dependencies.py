"""Trusted request context dependencies."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from life_agent.core.config import Settings, get_settings
from life_agent.db.models import User
from life_agent.db.session import get_db
from life_agent.modules.auth.service import resolve_session_user

Database = Annotated[Session, Depends(get_db)]


def get_current_user(
    request: Request,
    db: Database,
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    session_secret = request.cookies.get(settings.session_cookie_name)
    try:
        user = resolve_session_user(db, session_secret) if session_secret else None
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="认证存储暂时不可用。",
        ) from exc
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要有效登录会话。",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]