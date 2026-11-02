"""Account and server-side login-session operations."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from life_agent.db.models import LoginSession, User
from life_agent.modules.auth.security import (
    generate_session_secret,
    hash_password,
    hash_session_secret,
    verify_password,
)


class DuplicateUsernameError(ValueError):
    """Raised when a normalized username is already registered."""


class InvalidCredentialsError(ValueError):
    """Raised for an unknown user or incorrect password."""


@dataclass(frozen=True)
class CreatedSession:
    secret: str
    expires_at: datetime


def register_user(db: Session, username: str, password: str) -> User:
    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateUsernameError from exc
    db.refresh(user)
    return user


def authenticate_user(db: Session, username: str, password: str) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not user.is_active or not verify_password(
        user.password_hash, password
    ):
        raise InvalidCredentialsError
    return user


def create_login_session(
    db: Session, user: User, max_age_seconds: int
) -> CreatedSession:
    secret = generate_session_secret()
    expires_at = datetime.now(UTC) + timedelta(seconds=max_age_seconds)
    db.add(
        LoginSession(
            user_id=user.id,
            token_hash=hash_session_secret(secret),
            expires_at=expires_at,
        )
    )
    db.commit()
    return CreatedSession(secret, expires_at)


def resolve_session_user(db: Session, secret: str) -> User | None:
    now = datetime.now(UTC)
    return db.scalar(
        select(User)
        .join(LoginSession)
        .where(
            LoginSession.token_hash == hash_session_secret(secret),
            LoginSession.revoked_at.is_(None),
            LoginSession.expires_at > now,
            User.is_active.is_(True),
        )
    )


def revoke_login_session(db: Session, secret: str) -> None:
    db.execute(
        update(LoginSession)
        .where(
            LoginSession.token_hash == hash_session_secret(secret),
            LoginSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    db.commit()