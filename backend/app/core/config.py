"""Конфігурація M1 ID backend. Усі змінні оточення — з префіксом M1ID_."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/
BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="M1ID_", env_file=BASE_DIR / ".env", extra="ignore"
    )

    project_name: str = "M1 ID"
    version: str = "0.1.0"
    # prod-дефолт: False. Дев-скрипти задають M1ID_DEBUG=1 (start.bat,
    # smoke-тести). Відладкові фічі (link-token) вимкнені на проді.
    debug: bool = False

    # --- Спека (див. README: «Джерело OpenAPI-спеки») ---
    spec_url: str | None = None
    spec_file: Path = BASE_DIR / "openapi_snapshot" / "openapi.json"
    spec_cache_dir: Path = BASE_DIR / ".spec_cache"

    # --- Безпека ---
    secret_key: str = "dev-insecure-change-me"  # не використовується напряму: security.jwt_secret()
    token_enc_key: str = ""  # порожньо → авто-ключ у backend/.token_key
    refresh_token_expire_days: int = 30  # TTL сесії (sliding)

    # --- БД (рішення №2: SQLite; Postgres потім — один рядок) ---
    db_url: str = f"sqlite:///{(BASE_DIR / 'm1id.db').as_posix()}"

    # --- Інше ---
    email_mx_check: bool = True  # перевіряти MX-записи домену під час реєстрації
    # Зібрані фото викладачів (services/teacher_photos.py). env: M1ID_TEACHER_PHOTOS_DIR
    teacher_photos_dir: Path = BASE_DIR / "data" / "teacher_photos"
    # ДЕМО-хук розкладу (services/demo_schedule.py): фейковий тиждень
    # 24–30.08.2026 для навантажувального тесту. На проді НЕ вмикати.
    demo_schedule: bool = False

    # --- MyStat (живий API; шляхи вже містять /v1/...) ---
    mystat_api_base: str = "https://mapi.itstep.org"
    default_language: str = "uk"
    sync_timeout_seconds: float = 15.0

    # --- Мережа ---
    # Домен проєкту: з .env (M1ID_DOMAIN). З нього генеруються CORS-origin
    # і посилання на фронт для бота — зміна домену = один параметр.
    domain: str = "m1id.xyz"
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # За довіреним проксі (Cloudflare): rate-limit бере CF-Connecting-IP.
    # Вимкнено за замовчуванням — вмикати ЛИШЕ коли сервіс реально стоїть
    # за довіреним проксі, інакше клієнт підробить свій IP у лімітах.
    trusted_proxy: bool = False
    # Скільки довірених проксі-хопів у ланцюжку X-Forwarded-For (рахуючи
    # справа). Caddy напряму від клієнта = 1; Cloudflare -> Caddy без
    # CF-Connecting-IP = 2. Використовується лише при trusted_proxy=1.
    trusted_proxy_hops: int = 1

    # Swagger UI (/docs, /redoc) і /openapi.json: вимкнено за замовчуванням
    # на проді; у дев-режимі (debug) вмикається автоматично.
    # env: M1ID_DOCS_ENABLED=1
    docs_enabled: bool = False

    # --- Telegram-бот (aiogram 3, живе в тому самому процесі, що й API) ---
    # Токен від @BotFather. Порожньо → бот повністю вимкнений (API працює).
    telegram_bot_token: str = ""
    # FoodStep (foodstep.online) — їдальня Полтавської філії
    foodstep_base_url: str = "https://foodstep.online"
    foodstep_menu_ttl_minutes: int = 120  # кеш меню на сервері: 2 години
    # Цикл оновлення даних для сповіщень (сек). Запити всіх акаунтів
    # розмазуються рівномірно по цьому вікні; акаунти обробляються
    # по черзі (без рандому). 1800 = раз на 30 хвилин.
    telegram_poll_seconds: int = 1800
    # Режим розмазування фонових mapi-запитів poller'а:
    #   account — вікно ділиться на акаунти (слоти по юзерах; запити юзера
    #             всередині слота летять пачкою) — стара поведінка;
    #   request — вікно ділиться на ЗАПИТИ (1 запит раз на
    #             window/total_requests, рівний потік без пачок).
    #   Рекомендовано при зростанні кількості юзерів.
    # env: M1ID_POLL_PACE=account|request
    poll_pace: str = "account"
    # Посилання на фронт (кнопки «M1 ID» у боті та на сайті).
    # Порожньо → обчислюється з domain: https://<domain>
    telegram_site_url: str = ""

    # user_id адміністраторів (верифікація плагінів, видалення чужих плагінів)
    admin_user_ids: str = ""


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    domain = settings.domain.lower().strip()
    # CORS + посилання на фронт — похідні від домену (один параметр у .env).
    # Дві зони: фронт <domain> + API mapi.<domain>. Більше нічого.
    generated = [
        f"https://{domain}",
        f"https://www.{domain}",
        f"https://mapi.{domain}",
    ]
    settings.cors_origins = list(dict.fromkeys(settings.cors_origins + generated))
    # Домен коротких посилань M1 Provider (dz-хост) — прибрано:
    # тепер УСЕ живе на одному домені (M1ID_DOMAIN): фронт, API і
    # короткі посилання /api/v1/files/<slug>. Cloudflare-воркер
    # (фронт m1id.xyz) має ігнорувати шлях /api/v1/files/* —
    # не качати, не запускати, не оновлювати; він проксюється
    # напряму на бекенд.
    if not settings.telegram_site_url:
        settings.telegram_site_url = f"https://{domain}"
    return settings
