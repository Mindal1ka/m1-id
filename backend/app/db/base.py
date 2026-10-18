"""SQLAlchemy: engine + сесії. SQLite зараз, Postgres — один рядок конфіга."""
from __future__ import annotations

import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings


_log = logging.getLogger("m1id.db")

# Біти PRAGMA user_version — прапорці одноразових міграцій
# (щоб важкі/небезпечні кроки не виконувались на кожному старті).
_UV_DUP_SNAPSHOTS = 0x100   # дедуплікація снапшотів
_UV_SESSIONS_V3 = 0x200     # сесії: sha256-хеш токена + public_id (усі сесії скинуто)
_UV_AUTOEVAL_RESET = 0x400  # auto_eval_log: status='error' -> 'pending'
_UV_USER_SEQ_DENSE = 0x800  # одноразова перенумерація user_seq 1..N


class Base(DeclarativeBase):
    pass


def _build_engine():
    settings = get_settings()
    kwargs: dict = {}
    if settings.db_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(settings.db_url, **kwargs)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


from sqlalchemy import event  # noqa: E402


@event.listens_for(engine, "connect")
def _sqlite_fk_on(dbapi_connection, _record):  # вмикаємо FK-каскади в SQLite
    if engine.dialect.name == "sqlite":
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        # WAL: читачі не блокують письменника (і навпаки) — снапшоти
        # пишуться синком паралельно з видачею даних /api/app/*.
        # busy_timeout: чекаємо звільнення блокування замість миттєвого
        # "database is locked" під час піків запису.
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


def _sqlite_file_path():
    """Шлях до файлу SQLite з db_url (None — якщо не файлова БД)."""
    from pathlib import Path

    from sqlalchemy.engine import make_url

    if not engine.dialect.name == "sqlite":
        return None
    database = make_url(get_settings().db_url).database
    if not database or database == ":memory:":
        return None
    p = Path(database)
    if not p.is_absolute():
        p = Path.cwd() / p  # відносний шлях — від CWD процесу (backend/)
    return p


def init_db() -> None:
    """Створити таблиці + легка міграція (alembic — коли схема стане
    нетривіальною). Якщо файла БД немає — створюється автоматично."""
    from app.db import models  # noqa: F401 — реєстрація моделей

    p = _sqlite_file_path()
    created = False
    if p is not None and not p.exists():
        created = True
        # осиротілі -wal/-shm від колишньої БД «воскресять» старі дані
        # або дадуть database-is-malformed — прибираємо ДО першого коннекта
        for suffix in ("-wal", "-shm"):
            orphan = p.with_name(p.name + suffix)
            if orphan.exists():
                orphan.unlink()
        p.parent.mkdir(parents=True, exist_ok=True)

    Base.metadata.create_all(engine)
    _migrate_sqlite(engine)
    if created:
        print(f"[M1 ID] файла БД не було — створена нова: {p}")


def _migrate_sqlite(engine) -> None:
    """Авто-міграції легких змін схеми.
    1) UNIQUE(account_id, section) на snapshots (README «Модель даних БД»).
    2) mystat_accounts.user_seq — публічна нумерація акаунтів усередині
       користувача (URL /app?account=N не світить глобальні PK і загальну
       кількість акаунтів у системі)."""
    if engine.dialect.name != "sqlite":
        return
    from sqlalchemy import text

    with engine.begin() as conn:
        # LOW fix: важкий DELETE-бекфілл дублікатів снапшотів виконуємо
        # ОДИН РАЗ — метаданний прапорець у PRAGMA user_version (bit 8).
        # На кожен старт він давав довгий startup-лок на великій БД.
        uv = conn.execute(text("PRAGMA user_version")).scalar() or 0
        dup_cleanup_done = bool(uv & _UV_DUP_SNAPSHOTS)
        new_flags = 0
        if not dup_cleanup_done:
            conn.execute(text("""
                DELETE FROM snapshots
                WHERE id NOT IN (SELECT MAX(id) FROM snapshots
                                 GROUP BY account_id, section)
            """))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_snapshots_account_section
            ON snapshots (account_id, section)
        """))

        cols = [r[1] for r in conn.execute(
            text("PRAGMA table_info(mystat_accounts)"))]
        if "user_seq" not in cols:
            conn.execute(text(
                "ALTER TABLE mystat_accounts "
                "ADD COLUMN user_seq INTEGER NOT NULL DEFAULT 1"))
        # Foodstep: мітки «вже повідомлено/виконано» автозаказа — у БД,
        # щоб рестарт процесу не спамив попередженням по колу.
        fs_cols = [r[1] for r in conn.execute(
            text("PRAGMA table_info(foodstep_configs)"))]
        if fs_cols and "fired_marks" not in fs_cols:
            conn.execute(text(
                "ALTER TABLE foodstep_configs "
                "ADD COLUMN fired_marks TEXT DEFAULT '{}'"))
        if "mystat_login" not in cols:
            conn.execute(text(
                "ALTER TABLE mystat_accounts "
                "ADD COLUMN mystat_login VARCHAR(64) NOT NULL DEFAULT ''"))
        # Telegram v2: налаштування сповіщень переїхали з telegram_links
        # у telegram_account_configs (свій конфіг на кожен акаунт).
        # Legacy NOT NULL-колонки в links заважають INSERT'ам нової моделі
        # (немає DDL-дефолтів) — чистимо.
        tg_cols = [r[1] for r in conn.execute(
            text("PRAGMA table_info(telegram_links)"))]
        # DROP COLUMN потребує SQLite >= 3.35; на старішій — пропускаємо
        # (легасі-колонки лише залишаться, робота не ламається).
        import sqlite3
        can_drop = sqlite3.sqlite_version_info >= (3, 35, 0)
        for col in ("notify_homework", "notify_rating",
                    "notify_schedule_week", "notify_schedule_day",
                    "notify_schedule_daily", "notify_marks",
                    "notify_leaderboard", "leaderboard_mine_only",
                    "notify_shop", "quiet_hours"):
            if col in tg_cols:
                if not can_drop:
                    _log.warning("SQLite %s < 3.35: колонку telegram_links.%s "
                                 "не видалено", sqlite3.sqlite_version, col)
                    continue
                try:
                    conn.execute(text(
                        f'ALTER TABLE telegram_links DROP COLUMN "{col}"'))
                except Exception as exc:  # fail-soft: не валимо старт
                    _log.warning("DROP COLUMN %s не вдався: %r", col, exc)
        # Telegram v3: повідомляти про автооцінені уроки (вкладка «Додаткові»)
        tgcfg_cols = [r[1] for r in conn.execute(
            text("PRAGMA table_info(telegram_account_configs)"))]
        if tgcfg_cols and "notify_auto_eval" not in tgcfg_cols:
            conn.execute(text(
                "ALTER TABLE telegram_account_configs "
                "ADD COLUMN notify_auto_eval BOOLEAN DEFAULT 0"))
        # Нагадування про дедлайни ДЗ (окремий тумблер, дефолт УВІМКНЕНО)
        if tgcfg_cols and "notify_deadlines" not in tgcfg_cols:
            conn.execute(text(
                "ALTER TABLE telegram_account_configs "
                "ADD COLUMN notify_deadlines BOOLEAN DEFAULT 1"))
        # Telegram v4: вибір ЯКИЙ лідерборд моніторити (scope:period,
        # '' = усі). Слайси динамічні (школа/академія), тому - два рядки.
        for _lb_col in ("lb_scope", "lb_period"):
            if tgcfg_cols and _lb_col not in tgcfg_cols:
                conn.execute(text(
                    f"ALTER TABLE telegram_account_configs "
                    f"ADD COLUMN {_lb_col} VARCHAR(32) DEFAULT ''"))
        # M1 Provider: сповіщення про відкриття посилання ДЗ (дефолт УВІМКНЕНО)
        if tgcfg_cols and "notify_link_open" not in tgcfg_cols:
            conn.execute(text(
                "ALTER TABLE telegram_account_configs "
                "ADD COLUMN notify_link_open BOOLEAN DEFAULT 1"))
        # Самолікування журналу автооцінок (ОДИН раз, за user_version):
        # рядки, застряглі в 'error' без коду — це відповіді 205 Reset
        # Content (успіх, який старий код рахував помилкою). Повертаємо
        # в чергу. Раніше це виконувалось на кожному старті й воскрешало
        # справжні помилки в 'pending'.
        if not (uv & _UV_AUTOEVAL_RESET):
            aelog_cols = [r[1] for r in conn.execute(
                text("PRAGMA table_info(auto_eval_log)"))]
            if aelog_cols and "error_code" in aelog_cols:
                conn.execute(text(
                    "UPDATE auto_eval_log SET status = 'pending' "
                    "WHERE status = 'error' AND error_code IS NULL"))
            new_flags |= _UV_AUTOEVAL_RESET
        # бекфілл логіна зі снапшота профілю: get-personal-data віддає
        # username ТОП-РІВНЕМ (перевірено живою відповіддю 2026-08-29):
        # {"id":..., "id_user_storage":..., "username":"mende_io35", ...}
        conn.execute(text("""
            UPDATE mystat_accounts SET mystat_login = COALESCE((
                SELECT json_extract(s.payload, '$.username')
                FROM snapshots s
                WHERE s.account_id = mystat_accounts.id
                  AND s.section = 'profile'
                  AND json_extract(s.payload, '$.username') IS NOT NULL
                LIMIT 1
            ), '') WHERE mystat_login = ''
        """))
        # FoodStep: варіації тепер знають свого постачальника (можна
        # тримати варіації з різних їдалень одночасно).
        fsvar_cols = [r[1] for r in conn.execute(
            text("PRAGMA table_info(foodstep_variations)"))]
        if fsvar_cols and "supplier" not in fsvar_cols:
            conn.execute(text(
                "ALTER TABLE foodstep_variations "
                "ADD COLUMN supplier VARCHAR(32) NOT NULL DEFAULT 'dumpling'"))
        # Сесії: last_seen_at + public_id (публічний id сесії для UI)
        sess_cols = [r[1] for r in conn.execute(
            text("PRAGMA table_info(sessions)"))]
        if sess_cols and "last_seen_at" not in sess_cols:
            conn.execute(text(
                "ALTER TABLE sessions "
                "ADD COLUMN last_seen_at DATETIME NULL"))
        if sess_cols and "public_id" not in sess_cols:
            conn.execute(text(
                "ALTER TABLE sessions ADD COLUMN public_id VARCHAR(32) NULL"))
        # Одноразово: токени сесій більше не зберігаються у відкритому
        # вигляді (id = sha256). Старі рядки містять plaintext-токени,
        # тому всі існуючі сесії анулюємо (користувачі увійдуть заново).
        if sess_cols and not (uv & _UV_SESSIONS_V3):
            conn.execute(text("DELETE FROM sessions"))
        if sess_cols:
            new_flags |= _UV_SESSIONS_V3
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_sessions_public_id "
                "ON sessions (public_id)"))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_sessions_expires_at "
                "ON sessions (expires_at)"))
        # Одноразова щільна перенумерація 1..N усередині користувача.
        # ВАЖЛИВО: не на кожному старті — user_seq вже використовується
        # як стабільний посилальний id (PluginInstall.account_seqs,
        # M1Link.account_seq, URL), після видалень діри допустимі.
        if not (uv & _UV_USER_SEQ_DENSE):
            conn.execute(text("""
                UPDATE mystat_accounts SET user_seq = (
                    SELECT COUNT(*) FROM mystat_accounts AS t2
                    WHERE t2.user_id = mystat_accounts.user_id
                      AND t2.id <= mystat_accounts.id
                )
            """))
            new_flags |= _UV_USER_SEQ_DENSE
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_accounts_user_seq
            ON mystat_accounts (user_id, user_seq)
        """))
        # Позначаємо виконані одноразові кроки (біти PRAGMA user_version)
        if not dup_cleanup_done:
            new_flags |= _UV_DUP_SNAPSHOTS
        if new_flags & ~uv:
            conn.execute(text(f"PRAGMA user_version = {uv | new_flags}"))
