"""Pydantic-моделі запитів M1 ID auth."""
from __future__ import annotations

from pydantic import BaseModel, Field


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=32,
                          pattern=r"^[A-Za-z0-9_.\-]+$")
    password: str = Field(min_length=8, max_length=128)
    email: str = Field(min_length=5, max_length=255)


class LoginIn(BaseModel):
    """login — ім'я користувача АБО e-mail (як в оригінальному MyStat)."""

    login: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=16, max_length=64)


class LogoutIn(RefreshIn):
    pass


class SessionRevokeIn(BaseModel):
    """Кік конкретної сесії (за її id = колишнім refresh-токеном)."""
    session_id: str = Field(min_length=16, max_length=64)


class SessionsRevokeOthersIn(BaseModel):
    """Кік усіх сесій, КРІМ поточної (keep = свій живий refresh-токен)."""
    keep: str = Field(min_length=16, max_length=64)
