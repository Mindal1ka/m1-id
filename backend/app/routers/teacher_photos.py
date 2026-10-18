"""Публічна видача зібраних фото викладачів (services/teacher_photos.py).

Без auth: фото вантажить звичайний <img src>, а ключ — випадковий
public_key (не перебирається). Самі файли й так публічні в MyStat."""
from __future__ import annotations

import re

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.core.responses import ApiError
from app.services import teacher_photos

router = APIRouter(prefix="/api/teacher-photos", tags=["teacher-photos"])

_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{4,40}$")


@router.get("/{key}")
async def teacher_photo(key: str) -> FileResponse:
    if not _KEY_RE.fullmatch(key):
        raise ApiError(404, "not_found", "key", "photo_not_found")
    found = teacher_photos.file_for_key(key)
    if found is None:
        raise ApiError(404, "not_found", "key", "photo_not_found")
    path, ctype = found
    if ctype not in teacher_photos.ALLOWED_TYPES:
        raise ApiError(404, "not_found", "key", "photo_not_found")
    # ключ змінюється разом із файлом не завжди (той самий рядок БД),
    # тож кешуємо на добу, а не назавжди
    return FileResponse(path, media_type=ctype,
                        headers={"Cache-Control": "public, max-age=86400",
                                 "X-Content-Type-Options": "nosniff",
                                 "Content-Security-Policy":
                                     "default-src 'none'; sandbox"})
