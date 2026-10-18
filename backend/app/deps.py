"""Загальні залежності FastAPI: реєстр, налаштування, БД, поточний користувач."""
from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.responses import ApiError
from app.core.security import session_user_from_token
from app.db.base import SessionLocal as _session_factory
from app.db.models import User
from app.spec.registry import SpecRegistry

_bearer = HTTPBearer(auto_error=False)


def get_registry(request: Request) -> SpecRegistry:
    return request.app.state.registry


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db() -> Generator[Session, None, None]:
    db = _session_factory()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """401 в єдиному конверті, якщо немає/битий токен чи користувач.

    Auth v2: Bearer — це довгоживучий сесійний токен, валідність
    перевіряється за БД (таблиця sessions). Жодних JWT/ротацій:
    токен переживає рестарти, багато вкладок і воркерів без конфліктів."""
    if credentials is None:
        raise ApiError(401, "not_authenticated", "authorization",
                       "missing_bearer_token")
    user = session_user_from_token(db, credentials.credentials)
    if user is None:
        raise ApiError(401, "invalid_token", "authorization",
                       "access_token_invalid_or_expired")
    return user
