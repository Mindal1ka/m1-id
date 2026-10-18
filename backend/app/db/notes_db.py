"""Окрема БД нотаток і паролів (`notes.db`, лежить поруч з основною `m1id.db`).

Чому окремо: приватні дані юзера (тексти нотаток, шифровані паролі) не
змішуються з сесіями/кешем MyStat — їх зручно бекапити, переносити й
чистити окремо. Зв'язку з `users` через FK немає (різні файли БД):
`user_id` — просто число, власника перевіряє роутер.

Міграція. Раніше таблиці `notes` і `vault_entries` лежали в `m1id.db`.
При першому старті `init_notes_db()` ПЕРЕНОСИТЬ їх у `notes.db` (ідентифікатори
зберігаються), перевіряє, що кожен id на місці, і лише тоді видаляє старі
таблиці з `m1id.db`. Якщо щось пішло не так — старі таблиці лишаються
недоторканими, а спроба повторюється при наступному старті.
"""
from __future__ import annotations

import logging
from collections.abc import Generator
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.core.config import get_settings
from app.db.models import utcnow

_log = logging.getLogger("m1id.notes_db")


class NotesBase(DeclarativeBase):
    pass


class Note(NotesBase):
    """Нотатка користувача (Markdown). Належить юзеру M1 ID, не акаунту."""

    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class VaultEntry(NotesBase):
    """Запис сховища паролів. Назва/сайт і група — відкритим текстом (для
    списку й пошуку); усі поля (логін, пароль, email, опис…) — одним
    Fernet-шифротекстом `fields_enc` (JSON-масив у порядку показу)."""

    __tablename__ = "vault_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    grp: Mapped[str] = mapped_column(String(60), default="")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    fields_enc: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class NoteFile(NotesBase):
    """Файл користувача (вкладка «Файли»). Байти лежать у fs itstep (як
    вкладення домашки), у БД — лише метадані й пряме посилання `url`.
    `token` — публічний ідентифікатор для нотаток (`file:<token>`); власника
    перевіряє роутер, чужий і неіснуючий токен однаково дають 404."""

    __tablename__ = "note_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    token: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(String(2000), default="")
    orig_name: Mapped[str] = mapped_column(String(255), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    content_type: Mapped[str] = mapped_column(String(120), default="")
    kind: Mapped[str] = mapped_column(String(8), default="file")  # file | zip
    parts_json: Mapped[str] = mapped_column(Text, default="[]")   # імена файлів у zip
    url: Mapped[str] = mapped_column(String(600), default="")
    account_id: Mapped[int] = mapped_column(Integer, default=0)   # mystat_accounts.id
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# ------------------------------------------------------------------ engine

def notes_db_path() -> Path:
    """notes.db лежить поруч з основною БД (backend/)."""
    main_url = get_settings().db_url
    if main_url.startswith("sqlite"):
        main_path = main_url.split("///")[-1]
        if main_path and main_path != ":memory:":
            p = Path(main_path)
            if not p.is_absolute():
                p = Path.cwd() / p
            return p.parent / "notes.db"
    return Path.cwd() / "notes.db"


_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine():
    global _engine
    if _engine is None:
        path = notes_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{path.as_posix()}",
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(_engine, "connect")
        def _pragma(dbapi_connection, _record):
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

    return _engine


def _sessionmaker() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False)
    return _SessionLocal


def get_notes_db() -> Generator[Session, None, None]:
    """FastAPI-залежність: сесія до notes.db."""
    db = _sessionmaker()()
    try:
        yield db
    finally:
        db.close()


# ------------------------------------------------------------------ міграція

_MOVED_TABLES = ("notes", "vault_entries")


def _migrate_from_main() -> None:
    """Переносить `notes` і `vault_entries` з m1id.db у notes.db."""
    from app.db.base import engine as main_engine

    insp = inspect(main_engine)
    present = [t for t in _MOVED_TABLES if insp.has_table(t)]
    if not present:
        return

    counts: dict[str, int] = {}
    old_ids: dict[str, set[int]] = {}
    with main_engine.connect() as src, get_engine().begin() as dst:
        for t in present:
            new_cols = {c["name"] for c in inspect(get_engine()).get_columns(t)}
            cols = [c["name"] for c in insp.get_columns(t) if c["name"] in new_cols]
            rows = src.execute(text(f"SELECT {', '.join(cols)} FROM {t}")).mappings().all()
            old_ids[t] = {int(r["id"]) for r in rows}
            counts[t] = len(rows)
            if rows:
                dst.execute(
                    text(
                        f"INSERT OR IGNORE INTO {t} ({', '.join(cols)}) "
                        f"VALUES ({', '.join(':' + c for c in cols)})"
                    ),
                    [dict(r) for r in rows],
                )

    # перевірка: кожен старий id мусить бути в новій БД
    with get_engine().connect() as dst:
        for t in present:
            got = {int(r[0]) for r in dst.execute(text(f"SELECT id FROM {t}"))}
            missing = old_ids[t] - got
            if missing:
                raise RuntimeError(
                    f"міграція {t}: у notes.db бракує {len(missing)} записів — "
                    "старі таблиці НЕ видаляю")

    with main_engine.begin() as conn:
        for t in present:
            conn.execute(text(f"DROP TABLE {t}"))
    _log.info(
        "нотатки перенесено з m1id.db у %s: %s",
        notes_db_path().name,
        ", ".join(f"{t}={counts[t]}" for t in present),
    )
    print(f"[M1 ID] нотатки/паролі перенесено в {notes_db_path().name}: "
          + ", ".join(f"{t}={counts[t]}" for t in present))


def init_notes_db() -> None:
    """Створює notes.db і, якщо треба, переносить старі дані. Не кидає
    винятків назовні: збій міграції не повинен валити весь бекенд."""
    NotesBase.metadata.create_all(get_engine())
    try:
        _migrate_from_main()
    except Exception:
        _log.exception("міграція нотаток у notes.db не вдалася — "
                       "старі таблиці лишились у m1id.db, повторю при наступному старті")
