"""Права доступу до плагінів: адміни, власники, видимість, право запуску.

Адмін визначається ЛИШЕ конфігом (без неявного «user_id == 1»):
  • settings.admin_user_ids  (env M1ID_ADMIN_USER_IDS, через кому/крапку з комою);
  • settings.admin_usernames (env M1ID_ADMIN_USERNAMES) — якщо поля немає в
    config.py, читаємо змінну середовища напряму (локальний fallback).
Порожній конфіг = адмінів немає (верифікація недоступна, запускаються
лише власні плагіни автора та верифіковані).
"""
from __future__ import annotations

import logging
import os

_log = logging.getLogger("m1id.plugins")


def _split(raw) -> list[str]:
    return [p.strip() for p in str(raw or "").replace(";", ",").split(",")
            if p.strip()]


def admin_ids() -> set[int]:
    from app.core.config import get_settings
    raw = getattr(get_settings(), "admin_user_ids", "") \
        or os.environ.get("M1ID_ADMIN_USER_IDS", "")
    ids: set[int] = set()
    for part in _split(raw):
        if (part.isascii() and part.isdigit()):
            ids.add(int(part))
    return ids


def admin_usernames() -> set[str]:
    from app.core.config import get_settings
    raw = getattr(get_settings(), "admin_usernames", "") \
        or os.environ.get("M1ID_ADMIN_USERNAMES", "")
    return {p.lower() for p in _split(raw)}


def is_admin_user(user) -> bool:
    """user — ORM-об'єкт User (id, username_lower/username)."""
    if user is None:
        return False
    if user.id in admin_ids():
        return True
    name = str(getattr(user, "username_lower", "")
               or getattr(user, "username", "") or "").lower()
    return bool(name) and name in admin_usernames()


def is_admin_user_id(user_id: int) -> bool:
    """Те саме за одним user_id (для сервісного шару без ORM-об'єкта)."""
    if user_id in admin_ids():
        return True
    names = admin_usernames()
    if not names:
        return False
    try:
        from app.db.base import SessionLocal
        from app.db.models import User
        db = SessionLocal()
        try:
            row = db.get(User, user_id)
            return bool(row) and str(row.username_lower or "").lower() in names
        finally:
            db.close()
    except Exception as exc:  # основна БД недоступна — не адмін
        _log.warning("admin lookup failed: %r", exc)
        return False


def may_run(meta, user_id: int) -> bool:
    """Чи може плагін виконуватись для цього юзера: верифікований,
    або юзер — його автор чи адмін (для тестування власного коду)."""
    if bool(getattr(meta, "verified", False)):
        return True
    if getattr(meta, "uploaded_by", 0) == user_id:
        return True
    return is_admin_user_id(user_id)


def effective_permissions(manifest_perms, accepted) -> list[str]:
    """Дозволи, що реально діють: перетин маніфесту (що плагін просить)
    і PluginInstall.accepted_permissions (що юзер прийняв)."""
    wanted = [p for p in (manifest_perms or []) if isinstance(p, str)]
    given = {p for p in (accepted or []) if isinstance(p, str)}
    return [p for p in wanted if p in given]
