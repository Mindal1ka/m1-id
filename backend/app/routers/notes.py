"""Нотатки (Markdown) і сховище паролів користувача.
Дані лежать в окремій БД `notes.db` (app/db/notes_db.py), не в m1id.db.

Нотатки:  GET/POST /api/notes, GET/PUT/DELETE /api/notes/{id}
Паролі:   GET/POST /api/vault, GET/PUT/DELETE /api/vault/{id}

Паролі: назва/сайт і група лежать відкритим текстом (список, пошук), а всі
поля запису (логін, пароль, email, телефон, опис, власні) — одним
Fernet-шифротекстом (ключ: M1ID_TOKEN_ENC_KEY або файл .token_key, як у
токенів MyStat). Список віддає значення «секретних» полів порожніми; повне
значення повертає лише GET /api/vault/{id}.
"""
from __future__ import annotations

import json
import re
import secrets
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.responses import ApiError, ok
from app.core.security import decrypt_secret, encrypt_secret
from app.db.models import User
from app.db.notes_db import Note, VaultEntry, get_notes_db
from app.deps import get_current_user

router = APIRouter(prefix="/api", tags=["notes"])

MAX_NOTES = 2000
MAX_VAULT = 1000
MAX_BODY = 50_000
MAX_FIELDS = 40
MAX_VALUE = 4_000
PREVIEW_LEN = 160

FieldKind = Literal["login", "password", "email", "phone", "url", "text", "secret"]
SECRET_KINDS = {"password", "secret"}


def _iso(dt) -> str:
    return dt.isoformat(timespec="seconds") if dt else ""


# ------------------------------------------------------------------ нотатки

class NoteIn(BaseModel):
    title: str = Field("", max_length=200)
    body: str = Field("", max_length=MAX_BODY)
    pinned: bool = False


_MD_NOISE = re.compile(
    r"^\s*(?:[-*+]\s+\[[ xX]\]|[-*+]|\d+\.|>|#{1,3})\s+", re.M)


_FILE_REF = re.compile(r"file:[A-Za-z0-9]{16}")


def _preview(body: str) -> str:
    """Початок тексту без розмітки — для картки в списку."""
    out = []
    for ch in _FILE_REF.sub("📎", _MD_NOISE.sub("", body[:800])):
        out.append(" " if ch in "#*_`>~[]()\n\r\t" else ch)
    return " ".join("".join(out).split())[:PREVIEW_LEN]


def _note_row(n: Note, full: bool = False) -> dict:
    d = {
        "id": n.id,
        "title": n.title,
        "preview": _preview(n.body),
        "pinned": bool(n.pinned),
        "updated_at": _iso(n.updated_at),
        "created_at": _iso(n.created_at),
    }
    if full:
        d["body"] = n.body
    return d


def _own_note(db: Session, user: User, note_id: int) -> Note:
    n = db.get(Note, note_id)
    if n is None or n.user_id != user.id:
        raise ApiError(404, "not_found", "id", "note_not_found")
    return n


@router.get("/notes")
async def notes_list(q: str = "", user: User = Depends(get_current_user),
                     db: Session = Depends(get_notes_db)) -> dict:
    qry = db.query(Note).filter(Note.user_id == user.id)
    q = q.strip()[:100]
    if q:
        esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{esc}%"
        qry = qry.filter(or_(Note.title.ilike(like, escape="\\"),
                             Note.body.ilike(like, escape="\\")))
    rows = qry.order_by(Note.pinned.desc(), Note.updated_at.desc()).limit(MAX_NOTES).all()
    return ok({"items": [_note_row(n) for n in rows]})


@router.post("/notes")
async def notes_create(body: NoteIn, user: User = Depends(get_current_user),
                       db: Session = Depends(get_notes_db)) -> dict:
    cnt = db.query(func.count(Note.id)).filter(Note.user_id == user.id).scalar() or 0
    if cnt >= MAX_NOTES:
        raise ApiError(409, "limit", "notes", "notes_limit_reached")
    n = Note(user_id=user.id, title=body.title.strip(), body=body.body,
             pinned=body.pinned)
    db.add(n)
    db.commit()
    return ok(_note_row(n, full=True))


@router.get("/notes/{note_id}")
async def notes_get(note_id: int, user: User = Depends(get_current_user),
                    db: Session = Depends(get_notes_db)) -> dict:
    return ok(_note_row(_own_note(db, user, note_id), full=True))


@router.put("/notes/{note_id}")
async def notes_update(note_id: int, body: NoteIn,
                       user: User = Depends(get_current_user),
                       db: Session = Depends(get_notes_db)) -> dict:
    n = _own_note(db, user, note_id)
    n.title = body.title.strip()
    n.body = body.body
    n.pinned = body.pinned
    db.commit()
    return ok(_note_row(n, full=True))


@router.delete("/notes/{note_id}")
async def notes_delete(note_id: int, user: User = Depends(get_current_user),
                       db: Session = Depends(get_notes_db)) -> dict:
    db.delete(_own_note(db, user, note_id))
    db.commit()
    return ok({"deleted": True})


# ------------------------------------------------------------------ паролі

class FieldIn(BaseModel):
    id: str = Field("", max_length=32)
    kind: FieldKind = "text"
    label: str = Field("", max_length=60)
    value: str = Field("", max_length=MAX_VALUE)


class VaultIn(BaseModel):
    title: str = Field("", max_length=200)
    group: str = Field("", max_length=60)
    pinned: bool = False
    fields: list[FieldIn] = Field(default_factory=list, max_length=MAX_FIELDS)


def _pack_fields(fields: list[FieldIn]) -> str:
    out = []
    seen: set[str] = set()
    for f in fields:
        fid = f.id if f.id and f.id not in seen else secrets.token_hex(4)
        seen.add(fid)
        out.append({"id": fid, "kind": f.kind, "label": f.label.strip(),
                    "value": f.value})
    return encrypt_secret(json.dumps(out, ensure_ascii=False))


def _unpack_fields(enc: str) -> list[dict] | None:
    """None — ключ шифрування змінився, розшифрувати неможливо."""
    if not enc:
        return []
    try:
        data = json.loads(decrypt_secret(enc))
    except ValueError:
        return None
    return data if isinstance(data, list) else []


def _vault_row(e: VaultEntry, reveal: bool = False) -> dict:
    fields = _unpack_fields(e.fields_enc)
    broken = fields is None
    fields = fields or []
    out_fields = []
    for f in fields:
        secret = f.get("kind") in SECRET_KINDS
        out_fields.append({
            "id": f.get("id", ""),
            "kind": f.get("kind", "text"),
            "label": f.get("label", ""),
            # у списку секрети не віддаємо; has_value — щоб показати крапки
            "value": "" if (secret and not reveal) else f.get("value", ""),
            "has_value": bool(f.get("value")),
        })
    return {
        "id": e.id,
        "title": e.title,
        "group": e.grp,
        "pinned": bool(e.pinned),
        "fields": out_fields,
        "broken": broken,
        "updated_at": _iso(e.updated_at),
    }


def _own_entry(db: Session, user: User, entry_id: int) -> VaultEntry:
    e = db.get(VaultEntry, entry_id)
    if e is None or e.user_id != user.id:
        raise ApiError(404, "not_found", "id", "vault_entry_not_found")
    return e


@router.get("/vault")
async def vault_list(user: User = Depends(get_current_user),
                     db: Session = Depends(get_notes_db)) -> dict:
    rows = (db.query(VaultEntry).filter(VaultEntry.user_id == user.id)
            .order_by(VaultEntry.pinned.desc(), VaultEntry.title.asc())
            .limit(MAX_VAULT).all())
    return ok({"items": [_vault_row(e) for e in rows]})


@router.post("/vault")
async def vault_create(body: VaultIn, user: User = Depends(get_current_user),
                       db: Session = Depends(get_notes_db)) -> dict:
    cnt = db.query(func.count(VaultEntry.id)).filter(
        VaultEntry.user_id == user.id).scalar() or 0
    if cnt >= MAX_VAULT:
        raise ApiError(409, "limit", "vault", "vault_limit_reached")
    e = VaultEntry(user_id=user.id, title=body.title.strip(),
                   grp=body.group.strip(), pinned=body.pinned,
                   fields_enc=_pack_fields(body.fields))
    db.add(e)
    db.commit()
    return ok(_vault_row(e, reveal=True))


@router.get("/vault/{entry_id}")
async def vault_get(entry_id: int, user: User = Depends(get_current_user),
                    db: Session = Depends(get_notes_db)) -> dict:
    return ok(_vault_row(_own_entry(db, user, entry_id), reveal=True))


@router.put("/vault/{entry_id}")
async def vault_update(entry_id: int, body: VaultIn,
                       user: User = Depends(get_current_user),
                       db: Session = Depends(get_notes_db)) -> dict:
    e = _own_entry(db, user, entry_id)
    e.title = body.title.strip()
    e.grp = body.group.strip()
    e.pinned = body.pinned
    e.fields_enc = _pack_fields(body.fields)
    db.commit()
    return ok(_vault_row(e, reveal=True))


@router.delete("/vault/{entry_id}")
async def vault_delete(entry_id: int, user: User = Depends(get_current_user),
                       db: Session = Depends(get_notes_db)) -> dict:
    db.delete(_own_entry(db, user, entry_id))
    db.commit()
    return ok({"deleted": True})
