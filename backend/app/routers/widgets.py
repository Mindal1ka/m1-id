"""Хмарні розкладки віджетів Головної (cloud widgets).

GET /api/widgets/layouts  → збережені розкладки юзера для всіх класів
                            пристроїв {phone, tablet, desktop}
PUT  /api/widgets/layouts → зберегти розкладку (уся картка цілком;
                            фронт шле оновлення по debounce)
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.responses import ApiError, ok
from app.db.models import User, WidgetLayout
from app.deps import get_current_user, get_db

router = APIRouter(prefix="/api/widgets", tags=["widgets"])

# Валідація вхідного JSON: класи пристроїв + віджети (відомі ключі,
# span 3..12, h 70..1000). М'яка валідація: незнане відкидаємо, а не 422.
DEVICE_CLASSES = ("phone", "tablet", "desktop")
KNOWN_WIDGET_KEYS = {
    "stats", "deadlines", "lessons", "marks", "activity", "news", "board",
}
MAX_LAYOUT_BYTES = 32 * 1024


def _clean_widget(w: dict) -> dict | None:
    if not isinstance(w, dict):
        return None
    key = w.get("key")
    if key not in KNOWN_WIDGET_KEYS:
        return None
    span = w.get("span")
    if not isinstance(span, int) or span < 3 or span > 12:
        return None
    out: dict = {"key": key, "span": span}
    h = w.get("h")
    if isinstance(h, (int, float)) and 70 <= h <= 1000:
        out["h"] = int(h)
    return out


def _clean_layout(raw: dict) -> dict:
    out: dict = {}
    for cls in DEVICE_CLASSES:
        arr = raw.get(cls)
        if not isinstance(arr, list):
            continue
        cleaned = [c for c in (_clean_widget(w) for w in arr) if c]
        if cleaned:
            out[cls] = cleaned
    return out


def _load(db: Session, user_id: int) -> WidgetLayout | None:
    return (db.query(WidgetLayout)
            .filter(WidgetLayout.user_id == user_id).first())


class LayoutIn(BaseModel):
    layout: dict


@router.get("/layouts")
async def get_layouts(user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)) -> dict:
    row = _load(db, user.id)
    raw = row.layout_json if row else "{}"
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        data = {}
    return ok({
        "layouts": data if isinstance(data, dict) else {},
        "updated_at": row.updated_at.isoformat(timespec="seconds")
        if row else None,
    })


@router.put("/layouts")
async def put_layouts(body: LayoutIn,
                      user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)) -> dict:
    cleaned = _clean_layout(body.layout)
    raw = json.dumps(cleaned, ensure_ascii=False)
    if len(raw.encode("utf-8")) > MAX_LAYOUT_BYTES:
        raise ApiError(413, "layout_too_large", "layout",
                       "widget_layout_exceeds_32kb")
    row = _load(db, user.id)
    if row is None:
        row = WidgetLayout(user_id=user.id, layout_json=raw)
        db.add(row)
    else:
        row.layout_json = raw
    db.commit()
    return ok({"layouts": cleaned})
