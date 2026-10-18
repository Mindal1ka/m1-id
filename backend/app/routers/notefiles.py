"""Файли користувача (вкладка «Нотатки» → «Файли») і прикріплення до нотаток.

GET    /api/files              — мої файли (+ у яких нотатках використані)
POST   /api/files              — multipart `files[]`, `name`, `description`;
                                 `?__account=<user_seq>` — активний акаунт MyStat
GET    /api/files/{token}      — один файл (лише власник)
PUT    /api/files/{token}      — перейменувати / змінити опис
DELETE /api/files/{token}      — видалити (fs itstep — за можливості)

Зберігання — fs itstep, як вкладення домашки (`links.upload_fs_file`): GET
/user/file-token → POST multipart. fs приймає один файл за раз, тому кілька
файлів пакуються в один zip з одним токеном. У нотатці файл — це `file:<token>`
(16 символів [A-Za-z0-9], ~95 біт). Токен лише ідентифікує запис: власника
перевіряємо щоразу, чужий і неіснуючий токени дають однакову 404 — перебір
токенів не розкриває існування файлів.
"""
from __future__ import annotations

import asyncio
import io
import json
import mimetypes
import re
import secrets
import string
import zipfile

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.responses import ApiError, ok
from app.db.models import User
from app.db.notes_db import Note, NoteFile, get_notes_db
from app.deps import get_current_user, get_db
from app.routers.links import _own_account
from app.services import links
from app.services.app_data import _safe_filename
from app.services.ratelimit import rate_limit_user

router = APIRouter(prefix="/api/files", tags=["files"])

MAX_FILE = 25 * 1024 * 1024        # як у домашках: ≤25 МБ на файл і на zip
MAX_FILES = 50
MAX_TOTAL = 60 * 1024 * 1024       # сумарно за один аплоад
MAX_USER_FILES = 500
# Видалення з fs itstep ВИМКНЕНО (рішення власника): DELETE лише прибирає
# запис у нас, файл на fs лишається. Увімкнути: True (спершу запустити
# scripts/probe_fs_delete.py, щоб переконатись, що fs дійсно видаляє).
FS_DELETE_ENABLED = False
TOKEN_RE = re.compile(r"^[A-Za-z0-9]{16}$")
REF_RE = re.compile(r"file:([A-Za-z0-9]{16})")
_ALPHABET = string.ascii_letters + string.digits


def _iso(dt) -> str:
    return dt.isoformat(timespec="seconds") if dt else ""


def _new_token(db: Session) -> str:
    for _ in range(10):
        t = "".join(secrets.choice(_ALPHABET) for _ in range(16))
        if db.query(NoteFile.id).filter(NoteFile.token == t).first() is None:
            return t
    raise ApiError(500, "token_generation_failed", "__all__", "try_again")


def _view(f: NoteFile, notes: list[dict] | None = None) -> dict:
    try:
        parts = json.loads(f.parts_json or "[]")
    except ValueError:
        parts = []
    return {
        "token": f.token,
        "name": f.name,
        "description": f.description,
        "orig_name": f.orig_name,
        "size": f.size,
        "content_type": f.content_type,
        "kind": f.kind,
        "parts": parts if isinstance(parts, list) else [],
        "url": f.url,
        "created_at": _iso(f.created_at),
        "updated_at": _iso(f.updated_at),
        "notes": notes or [],
    }


def _usage(db: Session, user_id: int) -> dict[str, list[dict]]:
    """token → нотатки користувача, де є `file:<token>`."""
    out: dict[str, list[dict]] = {}
    rows = (db.query(Note.id, Note.title, Note.body)
            .filter(Note.user_id == user_id, Note.body.contains("file:")).all())
    for nid, title, body in rows:
        for tok in set(REF_RE.findall(body or "")):
            out.setdefault(tok, []).append({"id": nid, "title": title})
    return out


def _own(db: Session, user: User, token: str) -> NoteFile:
    f = None
    if TOKEN_RE.match(token or ""):
        f = db.query(NoteFile).filter(NoteFile.token == token).first()
    if f is None or f.user_id != user.id:
        raise ApiError(404, "not_found", "token", "file_not_found")
    return f


@router.get("")
async def files_list(user: User = Depends(get_current_user),
                     db: Session = Depends(get_notes_db)) -> dict:
    rows = (db.query(NoteFile).filter(NoteFile.user_id == user.id)
            .order_by(NoteFile.created_at.desc(), NoteFile.id.desc()).all())
    usage = _usage(db, user.id)
    return ok({"items": [_view(f, usage.get(f.token)) for f in rows]})


@router.get("/{token}")
async def files_get(token: str, user: User = Depends(get_current_user),
                    db: Session = Depends(get_notes_db)) -> dict:
    f = _own(db, user, token)
    return ok(_view(f, _usage(db, user.id).get(f.token)))


def _pack_zip(items: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for name, data in items:
            base = name
            n = 1
            while base.lower() in used:     # однакові імена → name (2).ext
                n += 1
                dot = name.rfind(".")
                base = (f"{name[:dot]} ({n}){name[dot:]}" if dot > 0
                        else f"{name} ({n})")
            used.add(base.lower())
            zf.writestr(base, data)
    return buf.getvalue()


async def _read_limited(up: UploadFile) -> bytes:
    data = bytearray()
    while True:
        chunk = await up.read(1024 * 1024)
        if not chunk:
            break
        data += chunk
        if len(data) > MAX_FILE:
            raise ApiError(413, "file_too_large", "files",
                           f"{up.filename or 'file'}: max_25mb")
    return bytes(data)


@router.post("", dependencies=[rate_limit_user(times=30, per_seconds=600,
                                               name="files_upload")])
async def files_upload(request: Request,
                       files: list[UploadFile],
                       name: str = Form("", max_length=200),
                       description: str = Form("", max_length=2000),
                       __account: int | None = None,
                       user: User = Depends(get_current_user),
                       main_db: Session = Depends(get_db),
                       db: Session = Depends(get_notes_db)) -> dict:
    """Завантажити файл (або кілька → один zip) в fs itstep."""
    try:
        if int(request.headers.get("content-length") or 0) > MAX_TOTAL + 2 * 1024 * 1024:
            raise ApiError(413, "payload_too_large", "files", "max_60mb")
    except ValueError:
        pass
    if not files:
        raise ApiError(422, "file_required", "files", "no_files")
    if len(files) > MAX_FILES:
        raise ApiError(422, "too_many_files", "files", "max_50_files")
    cnt = db.query(func.count(NoteFile.id)).filter(
        NoteFile.user_id == user.id).scalar() or 0
    if cnt >= MAX_USER_FILES:
        raise ApiError(409, "limit", "files", "files_limit_reached")
    acc = _own_account(main_db, user, __account)

    items: list[tuple[str, bytes, str]] = []
    total = 0
    for up in files:
        data = await _read_limited(up)
        if not data:
            raise ApiError(422, "file_required", "files",
                           f"{up.filename or 'file'}: empty_file")
        total += len(data)
        if total > MAX_TOTAL:
            raise ApiError(413, "payload_too_large", "files", "max_60mb")
        ctype = (up.content_type
                 or mimetypes.guess_type(up.filename or "")[0]
                 or "application/octet-stream")
        items.append((_safe_filename(up.filename), data, ctype))

    name = name.strip()
    if len(items) == 1:
        fname, data, ctype = items[0]
        kind, parts = "file", []
    else:
        title = _safe_filename(name or "files")
        fname = title if title.lower().endswith(".zip") else f"{title}.zip"
        data = await asyncio.to_thread(_pack_zip, [(n, d) for n, d, _ in items])
        ctype, kind, parts = "application/zip", "zip", [n for n, _d, _c in items]
        if len(data) > MAX_FILE:
            raise ApiError(413, "file_too_large", "files", f"{fname}: max_25mb")

    url = await links.upload_fs_file(acc, fname, data, ctype)

    row = NoteFile(
        user_id=user.id, token=_new_token(db),
        name=(name or (fname if kind == "file" else f"Архів ({len(parts)} файлів)"))[:200],
        description=description.strip()[:2000], orig_name=fname[:255],
        size=len(data), content_type=ctype[:120], kind=kind,
        parts_json=json.dumps(parts, ensure_ascii=False), url=url[:600],
        account_id=acc.id)
    db.add(row)
    db.commit()
    return ok(_view(row))


class FileEdit(BaseModel):
    name: str = Field("", max_length=200)
    description: str = Field("", max_length=2000)


@router.put("/{token}")
async def files_update(token: str, body: FileEdit,
                       user: User = Depends(get_current_user),
                       db: Session = Depends(get_notes_db)) -> dict:
    f = _own(db, user, token)
    f.name = body.name.strip() or f.orig_name or f.name
    f.description = body.description.strip()
    db.commit()
    return ok(_view(f, _usage(db, user.id).get(f.token)))


@router.delete("/{token}")
async def files_delete(token: str, __account: int | None = None,
                       user: User = Depends(get_current_user),
                       main_db: Session = Depends(get_db),
                       db: Session = Depends(get_notes_db)) -> dict:
    """Видаляє запис у нас. Файл на fs itstep зараз НЕ видаляється
    (`FS_DELETE_ENABLED = False`), тож `remote_deleted` завжди false. Нотатки з `file:<token>` не чіпаємо —
    у них фронт покаже «файл видалено»."""
    f = _own(db, user, token)
    from app.db.models import MystatAccount
    acc = (main_db.query(MystatAccount)
           .filter(MystatAccount.id == f.account_id,
                   MystatAccount.user_id == user.id).first())
    if acc is None:
        try:
            acc = _own_account(main_db, user, __account)
        except ApiError:
            acc = None
    remote = False
    if FS_DELETE_ENABLED and acc is not None and f.url:
        remote = await links.delete_fs_file(acc, f.url)
    db.delete(f)
    db.commit()
    return ok({"deleted": True, "remote_deleted": remote})
