"""Minimal account and server-side session endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import SQLAlchemyError

from life_agent.api.dependencies import CurrentUser, Database
from life_agent.core.config import Settings, get_settings
from life_agent.modules.auth.schemas import Credentials, UserResponse
from life_agent.modules.auth.service import (
    DuplicateUsernameError,
    InvalidCredentialsError,
    authenticate_user,
    create_login_session,
    register_user,
    revoke_login_session,
)

router = APIRouter()


def require_trusted_origin(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> None:
    origin = request.headers.get("origin")
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site == "cross-site" or (origin and origin not in settings.trusted_origins):
        raise HTTPException(status_code=403, detail="跨站状态变更请求已拒绝。")


def set_session_cookie(
    response: Response, settings: Settings, secret: str
) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=secret,
        max_age=settings.session_cookie_max_age_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )


@router.post(
    "/auth/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_trusted_origin)],
)
def register(credentials: Credentials, db: Database) -> UserResponse:
    try:
        return UserResponse.model_validate(
            register_user(db, credentials.username, credentials.password)
        )
    except DuplicateUsernameError as exc:
        raise HTTPException(status_code=409, detail="用户名已注册。") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="认证存储暂时不可用。") from exc


@router.post(
    "/auth/login",
    response_model=UserResponse,
    dependencies=[Depends(require_trusted_origin)],
)
def login(
    credentials: Credentials,
    response: Response,
    db: Database,
    settings: Annotated[Settings, Depends(get_settings)],
) -> UserResponse:
    try:
        user = authenticate_user(db, credentials.username, credentials.password)
        created_session = create_login_session(
            db, user, settings.session_cookie_max_age_seconds
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=401, detail="用户名或密码错误。") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="认证存储暂时不可用。") from exc
    set_session_cookie(response, settings, created_session.secret)
    return UserResponse.model_validate(user)


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_trusted_origin)],
)
def logout(
    request: Request,
    response: Response,
    db: Database,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    session_secret = request.cookies.get(settings.session_cookie_name)
    try:
        if session_secret:
            revoke_login_session(db, session_secret)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="认证存储暂时不可用。") from exc
    response.delete_cookie(
        settings.session_cookie_name,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )


@router.get("/me", response_model=UserResponse)
def me(current_user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(current_user)