"""Хмарні налаштування оформлення (тема / акцент / анімація появи).

GET /api/appearance  → збережений вибір юзера
PUT  /api/appearance → зберегти (уся картка цілком; фронт шле оновлення
                        по debounce). М'яка валідація: незнане відкидаємо.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.responses import ApiError, ok
from app.db.models import AppearancePref, User
from app.deps import get_current_user, get_db

router = APIRouter(prefix="/api/appearance", tags=["appearance"])

MAX_PREF_BYTES = 4 * 1024

KNOWN_MODES = {"dark", "light", "neon"}
KNOWN_ACCENTS = {
    "violet", "indigo", "ocean", "teal", "mint", "sun",
    "coral", "fire", "orchid", "amethyst", "rose", "magenta",
}
KNOWN_ANIMS = {"off", "fade", "rise", "slide", "pop"}


def _clean_pref(raw: dict) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    if raw.get("mode") in KNOWN_MODES:
        out["mode"] = raw["mode"]
    if raw.get("accent") in KNOWN_ACCENTS:
        out["accent"] = raw["accent"]
    if raw.get("anim") in KNOWN_ANIMS:
        out["anim"] = raw["anim"]
    if isinstance(raw.get("hoverGlow"), bool):
        out["hoverGlow"] = raw["hoverGlow"]
    if isinstance(raw.get("aurora"), bool):
        out["aurora"] = raw["aurora"]
    return out


def _load(db: Session, user_id: int) -> AppearancePref | None:
    return (db.query(AppearancePref)
            .filter(AppearancePref.user_id == user_id).first())


class PrefIn(BaseModel):
    pref: dict


@router.get("")
async def get_pref(user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> dict:
    row = _load(db, user.id)
    try:
        data = json.loads(row.pref_json) if row else {}
    except (TypeError, ValueError):
        data = {}
    return ok({
        "pref": data if isinstance(data, dict) else {},
        "updated_at": row.updated_at.isoformat(timespec="seconds")
        if row else None,
    })


@router.put("")
async def put_pref(body: PrefIn,
                   user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)) -> dict:
    cleaned = _clean_pref(body.pref)
    raw = json.dumps(cleaned, ensure_ascii=False)
    if len(raw.encode("utf-8")) > MAX_PREF_BYTES:
        raise ApiError(413, "pref_too_large", "pref",
                       "appearance_pref_exceeds_4kb")
    row = _load(db, user.id)
    if row is None:
        row = AppearancePref(user_id=user.id, pref_json=raw)
        db.add(row)
    else:
        row.pref_json = raw
    db.commit()
    return ok({"pref": cleaned})
