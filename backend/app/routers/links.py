"""M1 Provider: роутери посилань.

Публічні (БЕЗ auth — вчитель ходить анонімно, slug і є секретом):
  GET  /api/v1/files/{slug}            → 302 або сторінка-галерея
  GET  /api/v1/files/{slug}/media/{i}  → байти медіа (кеш 60 с)
  GET  /api/v1/files/{slug}/download   → 302 на оригінал (fs itstep)

Авторизовані (власник):
  GET    /api/links?homework_id=&__account=   → посилання ДЗ + статистика
  PATCH  /api/links/{slug}                    → змінити target_url
  DELETE /api/links/{slug}                    → вилучити (active=False)
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.responses import ApiError, ok
from app.db.models import MystatAccount, User
from app.deps import get_current_user, get_db
from app.services import links
from app.services import ratelimit as _rl

def _public_limit(name: str, times: int = 30, per_seconds: int = 60):
    """Rate-limit публічного роуту зі СТАБІЛЬНИМ ключем (IP + ім'я роуту).

    rate_limit() додає в ключ request.url.path, що містить slug, — тож
    перебір slug-ів обходив ліміт (кожен slug мав власний бакет).
    TODO: коли ratelimit.py отримає параметр стабільного ключа — перейти на нього."""

    def dependency(request: Request) -> None:
        _rl._hit(f"{_rl._client_key(request)}:links:{name}", times, per_seconds)

    return Depends(dependency)


public_router = APIRouter(prefix="/api/v1/files", tags=["M1 Provider"])
router = APIRouter(prefix="/api/links", tags=["M1 Provider"])


def _load(db, slug: str) -> links.M1Link:
    row = db.get(links.M1Link, slug)
    if row is None:
        raise ApiError(404, "link_not_found", "slug", "посилання не знайдено")
    return row


# ---------------------------------------------------------------- публічні

@public_router.get("/{slug}", dependencies=[_public_limit("open")])
async def open_link(slug: str):
    db = links.new_session()
    try:
        row = _load(db, slug)
        # N-M8 fix: синхронний шлях (register_open: 2 DB-сесії + TG-конфіг)
        # знято з event loop у threadpool — анонімний трафік із SQLite
        # busy_timeout більше не підвішує loop.
        # loop передаємо явно: у worker-потоці get_running_loop() недоступний
        loop = asyncio.get_running_loop()
        return await asyncio.to_thread(links.handle_open, row, False, loop)
    finally:
        db.close()


@public_router.get("/{slug}/media/{index}",
                   dependencies=[_public_limit("media", 120, 60)])
async def open_media(slug: str, index: int):
    db = links.new_session()
    try:
        row = _load(db, slug)
        return await links.handle_media(row, index)
    finally:
        db.close()


@public_router.get("/{slug}/download",
                   dependencies=[_public_limit("download")])
async def download(slug: str):
    db = links.new_session()
    try:
        row = _load(db, slug)
        loop = asyncio.get_running_loop()
        return await asyncio.to_thread(links.handle_open, row, True, loop)
    finally:
        db.close()


# ------------------------------------------------------------- авторизовані

def _own_account(db: Session, user: User, account_id: int | None
                 ) -> MystatAccount:
    q = db.query(MystatAccount).filter(MystatAccount.user_id == user.id)
    if account_id is not None:
        acc = q.filter(MystatAccount.user_seq == account_id).first()
    else:
        acc = q.order_by(MystatAccount.id).first()
    if acc is None:
        raise ApiError(404, "account_not_found", "__all__",
                       "link_mystat_account_first")
    return acc


@router.get("")
async def my_links(homework_id: int | None = None,
                   __account: int | None = None,
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)) -> dict:
    """Посилання користувача (опційно одного ДЗ) зі статистикою."""
    acc = _own_account(db, user, __account)
    ldb = links.new_session()
    try:
        q = (ldb.query(links.M1Link)
             .filter(links.M1Link.user_id == user.id,
                     links.M1Link.account_id == acc.id))
        if homework_id is not None:
            q = q.filter(links.M1Link.homework_id == homework_id)
        rows = q.order_by(links.M1Link.created_at.desc()).all()
        return ok({"items": [links.link_view(r) for r in rows]})
    finally:
        ldb.close()


class LinkPatch(BaseModel):
    target_url: str


@router.patch("/{slug}")
async def patch_link(slug: str, body: LinkPatch,
                     db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)) -> dict:
    """Змінити ціль посилання (редагування у карточці ДЗ)."""
    url = body.target_url.strip()
    if len(url) > 2048:
        raise ApiError(422, "link_invalid", "target_url", "url_too_long")
    try:
        # http/https, дозволені порти, хост резолвиться лише у публічні IP
        await links.assert_public_url(url)
    except links.UnsafeUrl:
        raise ApiError(422, "link_invalid", "target_url",
                       "must_be_public_http_or_https_url")
    ldb = links.new_session()
    try:
        row = _load(ldb, slug)
        if row.user_id != user.id:
            raise ApiError(403, "forbidden", "slug", "not_your_link")
        row.target_url = url
        ldb.commit()
        return ok(links.link_view(row))
    finally:
        ldb.close()


@router.post("/{slug}/file")
async def upload_link_file(slug: str, file: UploadFile,
                           __account: int | None = None,
                           db: Session = Depends(get_db),
                           user: User = Depends(get_current_user)) -> dict:
    """Замінити ціль посилання файлом: завантажуємо в fs itstep
    (як при здачі) і зберігаємо пряме посилання. Акаунт — активний у
    застосунку (`__account` = user_seq); без нього — перший."""
    acc = _own_account(db, user, __account)
    # N-M4: перевірка власності slug ДО upload_fs_file — інакше не-власник
    # міг би залити 25МБ на fs itstep від імені чужого акаунта, і лише
    # потім отримати 403
    ldb = links.new_session()
    try:
        row = _load(ldb, slug)
        if row.user_id != user.id:
            raise ApiError(403, "forbidden", "slug", "not_your_link")
    finally:
        ldb.close()
    data = await file.read()
    if not data:
        raise ApiError(422, "file_required", "file", "empty_file")
    if len(data) > 25 * 1024 * 1024:
        raise ApiError(413, "file_too_large", "file", "max_25mb")
    fs_link = await links.upload_fs_file(
        acc, file.filename or "solution", data, file.content_type)
    ldb = links.new_session()
    try:
        row = _load(ldb, slug)
        row.target_url = fs_link
        row.kind = "file"
        ldb.commit()
        return ok(links.link_view(row))
    finally:
        ldb.close()


@router.delete("/{slug}")
async def revoke_link(slug: str, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)) -> dict:
    """Вилучити посилання: актив=False (сама стрічка в ДЗ лишається,
    але відкриття показує «вилучено»)."""
    ldb = links.new_session()
    try:
        row = _load(ldb, slug)
        if row.user_id != user.id:
            raise ApiError(403, "forbidden", "slug", "not_your_link")
        row.active = False
        ldb.commit()
        return ok(links.link_view(row))
    finally:
        ldb.close()
