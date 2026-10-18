"""Моделі БД M1 ID. Схема описана в README («Модель даних БД»)."""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    """Наївний UTC: SQLite не зберігає tzinfo — порівнюємо однаково всюди."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    """Акаунт M1 ID — єдиний вхід у нашу систему."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    username_lower: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    settings_json: Mapped[str] = mapped_column(Text, default="{}")


class RefreshSession(Base):
    """Сесія користувача. Токен у БД НЕ зберігається: `id` = sha256(токен)
    у hex (64 символи). Публічний ідентифікатор для UI (`/sessions`, кік) —
    окреме поле `public_id`, з токеном не пов'язане."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 hex
    public_id: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, default=lambda: secrets.token_hex(16)
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    user_agent: Mapped[str] = mapped_column(String(255), default="")
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


class MystatAccount(Base):
    """Підключений акаунт MyStat. Пароль НЕ зберігаємо — лише токен (рішення №1)."""

    __tablename__ = "mystat_accounts"
    # Публічний номер акаунта ВСЕРЕДИНІ користувача (1..N): URL /app?account=N,
    # __account, /api/accounts/N кажуть лише «мій N-й». Глобальний PK
    # назовні не світиться — ніхто не дізнається загальну кількість акаунтів.
    __table_args__ = (
        UniqueConstraint("user_id", "user_seq", name="uq_accounts_user_seq"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    user_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    label: Mapped[str] = mapped_column(String(120), default="")
    branch_alias: Mapped[str] = mapped_column(String(16), default="", index=True)
    logbook_id: Mapped[str] = mapped_column(String(64), default="")
    id_user_storage: Mapped[str] = mapped_column(String(64), default="")
    fio: Mapped[str] = mapped_column(String(255), default="")
    mystat_login: Mapped[str] = mapped_column(String(64), default="")
    photo_url: Mapped[str] = mapped_column(Text, default="")
    access_token_enc: Mapped[str] = mapped_column(Text, default="")
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    status: Mapped[str] = mapped_column(
        String(20), default="active"
    )  # active | needs_relogin | disabled
    language: Mapped[str] = mapped_column(String(8), default="uk")
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


class Snapshot(Base):
    """Кеш відповідей Sync Engine — основа офлайну й миттєвого завантаження."""

    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("mystat_accounts.id", ondelete="CASCADE"), index=True
    )
    section: Mapped[str] = mapped_column(String(64))
    payload: Mapped[str] = mapped_column(Text, default="null")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TelegramLink(Base):
    """Прив'язка користувача M1 ID до чату Telegram.

    Прив'язка — через deep-link із підписаного payload (HMAC від jwt-секрету),
    див. app/telegram/linking.py. Один користувач = один чат; повторний
    /start з новим чатом переносить прив'язку. Налаштування сповіщень живуть
    ОКРЕМО на кожному акаунті MyStat — TelegramAccountConfig.
    """

    __tablename__ = "telegram_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    bot_username: Mapped[str] = mapped_column(String(64), default="")
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TelegramAccountConfig(Base):
    """Налаштування сповіщень для КОНКРЕТНОГО акаунта MyStat.

    Конфіги розділені: увімкнено на одному акаунті — не значить увімкнено на
    іншому. Повідомлення різних акаунтів ідуть окремими повідомленнями (з
    логіном акаунта в заголовку). quiet_hours = «не смикати mapi і не
    слати 23:00-05:00»; уранці цикл порівняє стан із вечірнім і пришле
    все накоплене однією пачкою.
    """

    __tablename__ = "telegram_account_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("mystat_accounts.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # актуальний chat користувача — оновлюється при (пере)прив'язці
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True, default=0)

    quiet_hours: Mapped[bool] = mapped_column(Boolean, default=True)

    notify_homework: Mapped[bool] = mapped_column(Boolean, default=True)
    # нагадування про дедлайн ДЗ (за 24 год і за 3 год) — незалежний тумблер
    notify_deadlines: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_rating: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_schedule_week: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_schedule_day: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_schedule_daily: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_marks: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_leaderboard: Mapped[bool] = mapped_column(Boolean, default=False)
    # True = повідомляти лише коли змінилась МОЯ позиція; False = будь-яка зміна порядку
    leaderboard_mine_only: Mapped[bool] = mapped_column(Boolean, default=True)
    # який саме зріз лідерборда моніторити: "group:month" тощо.
    # '' (порожньо) = усі доступні зрізи (динамічні: школа/академія)
    lb_scope: Mapped[str] = mapped_column(String(32), default="")
    lb_period: Mapped[str] = mapped_column(String(32), default="")
    notify_shop: Mapped[bool] = mapped_column(Boolean, default=False)
    # повідомити в TG про успішне АВТООЦІНЮВАННЯ уроку (Додаткові → сокет)
    notify_auto_eval: Mapped[bool] = mapped_column(Boolean, default=False)
    # M1 Provider: сповіщати в TG, коли хтось відкрив наше посилання ДЗ
    # («Ваше завдання перевіряють»)
    notify_link_open: Mapped[bool] = mapped_column(Boolean, default=True)

class SocketAccountConfig(Base):
    """Налаштування вкладки «Додаткові» для КОНКРЕТНОГО акаунта MyStat.

    socket_enabled - жити з'єднання з notify-сокетом MyStat (миттєві
    події; замість очікування 30-хв циклу поллера - одразу точковий
    перезапит розділів). auto_eval - автоматично оцінювати 5/5 без
    коментаря кожен урок, що приходить сокетом (evaluation_notification).
    Поллер лишається як є - сокет лише «прискорювач».
    """

    __tablename__ = "socket_account_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("mystat_accounts.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    socket_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_eval: Mapped[bool] = mapped_column(Boolean, default=False)
    # на майбутнє: можливі інші налаштування оцінювання
    eval_mark_lesson: Mapped[int] = mapped_column(Integer, default=5)
    eval_mark_teach: Mapped[int] = mapped_column(Integer, default=5)
    eval_comment: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)


class AutoEvalLog(Base):
    """Журнал автооцінювання: dedupe по (account_id, lesson_id), щоб
    повторна подія сокета (reconnect/queue) не ставила другу оцінку,
    + відкладені оцінки на тихі години (status='pending')."""

    __tablename__ = "auto_eval_log"
    __table_args__ = (
        UniqueConstraint("account_id", "lesson_id",
                         name="uq_autoeval_account_lesson"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("mystat_accounts.id", ondelete="CASCADE"), index=True
    )
    lesson_id: Mapped[str] = mapped_column(String(64))
    theme: Mapped[str] = mapped_column(String(255), default="")
    teach_name: Mapped[str] = mapped_column(String(255), default="")
    mark_lesson: Mapped[int] = mapped_column(Integer, default=5)
    mark_teach: Mapped[int] = mapped_column(Integer, default=5)
    # pending → ok / already (84222) / closed (84223) / error
    status: Mapped[str] = mapped_column(String(16), default="pending")
    error_code: Mapped[int] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                                 default=utcnow)
    rated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
                                               nullable=True)


class TelegramPollState(Base):
    """«Пам'ять» опитувальника: останній знімок секції акаунта для детекту
    змін (хеші/списки id). Бот пам'ятає попередній стан між циклами
    і переживає рестарти — без нього кожен цикл виглядав би як «все змінилось».
    """

    __tablename__ = "telegram_poll_state"
    __table_args__ = (
        UniqueConstraint("account_id", "section", name="uq_tg_poll_account_section"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("mystat_accounts.id", ondelete="CASCADE"), index=True
    )
    section: Mapped[str] = mapped_column(String(48))
    payload: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WidgetLayout(Base):
    """Хмарні розкладки віджетів Головної: один рядок на юзера, JSON
    містить розкладки для всіх класів пристроїв:
    {"phone": [...], "tablet": [...], "desktop": [...]}.
    """

    __tablename__ = "widget_layouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    layout_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AppearancePref(Base):
    """Хмарні налаштування оформлення: один рядок на юзера, JSON:
    {"mode": "dark|light|neon", "accent": "...", "anim": "...",
     "hoverGlow": true|false}. Синхронізується так само, як розкладки
    віджетів: локальний кеш + debounce PUT + merge при логіні.
    """

    __tablename__ = "appearance_prefs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    pref_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# ------------------------------------------------------------------ FoodStep

class FoodstepConfig(Base):
    """Налаштування харчування (FoodStep) на користувача M1 ID.

    Пароль FoodStep шифрується тим самим Fernet-ключем, що й токени
    MyStat (encrypt_secret). На фронт ніколи не віддається — лише маска.
    """

    __tablename__ = "foodstep_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    password_enc: Mapped[str] = mapped_column(Text, default="")
    supplier: Mapped[str] = mapped_column(String(32), default="dumpling")
    # Автозаказ
    auto_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_mode: Mapped[str] = mapped_column(
        String(8), default="random"
    )  # random | fixed
    fixed_variation_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    order_time: Mapped[str] = mapped_column(String(5), default="08:00")
    notify_minutes: Mapped[int] = mapped_column(Integer, default=60)
    allow_weekends: Mapped[bool] = mapped_column(Boolean, default=False)
    skip_dates: Mapped[str] = mapped_column(Text, default="[]")  # JSON list "YYYY-MM-DD"
    # Мітки «вже повідомлено/виконано» автозаказа: JSON {"uid:iso:notify": 1, ...}.
    # У БД (а не в пам'яті), щоб рестарт процесу не спамив попередженням знову.
    fired_marks: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class FoodstepVariation(Base):
    """Варіація автозаказа: назва + набір страв JSON [{id, count}]."""

    __tablename__ = "foodstep_variations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64), default="")
    # Постачальник, з меню якого зібрана варіація («dumpling» | «provinces»).
    # Варіації різних постачальників живуть поруч, автозамовлення бере
    # постачальника САМЕ ВАРІАЦІЇ, а не глобальний конфіг.
    supplier: Mapped[str] = mapped_column(String(32), default="dumpling")
    items_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FoodstepOrder(Base):
    """Журнал замовлень харчування. FoodStep сам не віддає історії,
    тому це джерело правди. Унікальність (user_id, date) повторює
    бізнес-правило FoodStep «одне замовлення на дату»."""

    __tablename__ = "foodstep_orders"
    __table_args__ = (
        UniqueConstraint("user_id", "order_date", name="uq_fs_user_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    order_date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    supplier: Mapped[str] = mapped_column(String(32), default="")
    items_json: Mapped[str] = mapped_column(Text, default="[]")
    total: Mapped[int] = mapped_column(Integer, default=0)  # грн
    source: Mapped[str] = mapped_column(
        String(8), default="manual"
    )  # manual | auto
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QrLogin(Base):
    """Запит на вхід за QR: ПК показує QR, підтверджує вже залогінений
    пристрій (сайт або Telegram). У БД лише sha256 обох секретів:
    `id` = sha256(link-токен із QR), `poll_hash` = sha256(секрет, що знає
    лише вкладка-ініціатор). Сесію вкладка отримує одноразово, коли статус
    став approved."""

    __tablename__ = "qr_logins"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    poll_hash: Mapped[str] = mapped_column(String(64))
    code: Mapped[str] = mapped_column(String(2))  # код збігу (2 цифри)
    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
    # pending | approved | denied | consumed
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, default=None
    )
    approved_via: Mapped[str] = mapped_column(String(12), default="")
    req_ip: Mapped[str] = mapped_column(String(64), default="")
    req_ua: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class TeacherPhoto(Base):
    """База фото викладачів (services/teacher_photos.py).

    API MyStat не віддає фото викладачів у контактах — вони трапляються лише
    у відповідях оцінок і ДЗ. Збираємо їх, коли ці відповіді йдуть через наш
    сервер. Прив'язка: філія + ПІБ (як прийшло з MyStat, разом із «School»),
    id викладача (з контактів / ДЗ) і посилання MyStat — воно генерується
    випадково, тож нове посилання = викладач змінив фото → перезавантажуємо."""

    __tablename__ = "teacher_photos"
    __table_args__ = (
        UniqueConstraint("branch_alias", "teacher_name",
                         name="uq_teacher_photos_branch_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    branch_alias: Mapped[str] = mapped_column(String(32), index=True)
    teacher_name: Mapped[str] = mapped_column(String(255))
    teacher_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, default=None, index=True)
    source_url: Mapped[str] = mapped_column(String(512), default="")
    file_name: Mapped[str] = mapped_column(String(80), default="")
    content_type: Mapped[str] = mapped_column(String(64), default="image/jpeg")
    # публічний ключ для /api/teacher-photos/{key} (без auth: <img src>)
    public_key: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, default=lambda: secrets.token_urlsafe(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
