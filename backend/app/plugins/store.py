"""Окрема БД під плагіни (plugins.db): метадані, файли, інсталяції,
логи запусків, черга TG-повідомлень, реєстр TG-команд.

Основна БД (m1id.db) плагінних таблиць не містить — ізоляція збоїв:
падіння/зіпсуття плагінної бази не зачіпає акаунти й сповіщення.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, \
    Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings


class PluginBase(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def plugins_db_path() -> Path:
    """plugins.db лежить поруч з основною БД (backend/)."""
    main_url = get_settings().db_url
    if main_url.startswith("sqlite"):
        main_path = main_url.split("///")[-1]
        if main_path and main_path != ":memory:":
            p = Path(main_path)
            if not p.is_absolute():
                p = Path.cwd() / p
            return p.parent / "plugins.db"
    return Path.cwd() / "plugins.db"


_engine = None
_SessionLocal: sessionmaker | None = None


def get_engine():
    global _engine
    if _engine is None:
        path = plugins_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{path}",
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(_engine, "connect")
        def _pragma(dbapi_connection, _record):
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

    return _engine


def get_sessionmaker() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False)
    return _SessionLocal


def new_session():
    return get_sessionmaker()()


def init_plugin_db() -> None:
    PluginBase.metadata.create_all(get_engine())
    # легка міграція для вже існуючих БД (нові колонки)
    from sqlalchemy import text
    with get_engine().connect() as conn:
        cols = {r[1] for r in conn.execute(
            text("PRAGMA table_info(plugin_meta)")).fetchall()}
        if "visibility" not in cols:
            conn.execute(text(
                "ALTER TABLE plugin_meta ADD COLUMN visibility VARCHAR(16) "
                "NOT NULL DEFAULT 'public'"))
        if "share_token" not in cols:
            conn.execute(text(
                "ALTER TABLE plugin_meta ADD COLUMN share_token VARCHAR(48)"
                " NOT NULL DEFAULT ''"))
        if "account_seqs" not in {r[1] for r in conn.execute(
                text("PRAGMA table_info(plugin_installs)")).fetchall()}:
            conn.execute(text(
                "ALTER TABLE plugin_installs ADD COLUMN account_seqs JSON"
                " NOT NULL DEFAULT '[]'"))
        conn.commit()


# ---------------------------------------------------------------- моделі

class PluginMeta(PluginBase):
    """Плагін у «маркетплейсі» (зареєстрований на сервері)."""
    __tablename__ = "plugin_meta"

    id = Column(String(48), primary_key=True)  # slug з маніфеста
    name = Column(String(96), nullable=False)
    version = Column(String(24), nullable=False)
    author = Column(String(96), nullable=False, default="")
    description = Column(Text, nullable=False, default="")
    verified = Column(Boolean, nullable=False, default=False)
    manifest = Column(JSON, nullable=False)
    code_hash = Column(String(64), nullable=False, default="")
    uploaded_by = Column(Integer, nullable=False, default=0)
    uploaded_at = Column(DateTime(timezone=True), default=utcnow)
    # видимість у маркетплейсі: public | link (лише за share-посиланням) | private
    visibility = Column(String(16), nullable=False, default="public")
    share_token = Column(String(48), nullable=False, default="")


class PluginFile(PluginBase):
    """Файли плагіна (plugin.py, index.html, icon.png у base64...)."""
    __tablename__ = "plugin_files"

    plugin_id = Column(String(48), primary_key=True)
    path = Column(String(128), primary_key=True)  # 'plugin.py' / 'index.html'
    content = Column(Text, nullable=False)
    encoding = Column(String(8), nullable=False, default="utf-8")


class PluginInstall(PluginBase):
    """Пер-юзерна інсталяція: увімкнено, згода на дозволи, налаштування."""
    __tablename__ = "plugin_installs"

    user_id = Column(Integer, primary_key=True)
    plugin_id = Column(String(48), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=True)
    accepted_permissions = Column(JSON, nullable=False, default=list)
    settings = Column(JSON, nullable=False, default=dict)
    storage = Column(Text, nullable=False, default="{}")  # JSON key-value
    installed_at = Column(DateTime(timezone=True), default=utcnow)
    # Які акаунти MyStat (user_seq) опрацьовує плагін: [] = усі акаунти юзера
    account_seqs = Column(JSON, nullable=False, default=list)


class PluginRun(PluginBase):
    """Лог виконань (дебаг + аудит верифікації)."""
    __tablename__ = "plugin_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plugin_id = Column(String(48), nullable=False)
    user_id = Column(Integer, nullable=False)
    trigger = Column(String(32), nullable=False)
    trigger_detail = Column(String(96), nullable=False, default="")
    ok = Column(Boolean, nullable=False, default=False)
    duration_ms = Column(Integer, nullable=False, default=0)
    outcome = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow)


class NotifyOutbox(PluginBase):
    """Черга TG-повідомлень від плагінів (флашиться async-таскою)."""
    __tablename__ = "notify_outbox"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plugin_id = Column(String(48), nullable=False)
    user_id = Column(Integer, nullable=False)
    chat_id = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    priority = Column(String(16), nullable=False, default="info")
    status = Column(String(16), nullable=False, default="pending")
    retry_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class TgCommand(PluginBase):
    """Глобальний реєстр TG-команд плагінів (унікальність при аплоаді)."""
    __tablename__ = "tg_commands"

    command = Column(String(32), primary_key=True)
    plugin_id = Column(String(48), nullable=False)
    description = Column(String(64), nullable=False, default="")


class TgButton(PluginBase):
    """Реєстр callback-кнопок плагінів (callback_data: plg:<id>:<button>)."""
    __tablename__ = "tg_buttons"

    plugin_id = Column(String(48), primary_key=True)
    button_id = Column(String(32), primary_key=True)
    label = Column(String(64), nullable=False, default="")