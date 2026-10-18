"""M1 ID backend — точка входу.

Lifespan: ініціалізація БД + завантаження OpenAPI-спеки в SpecRegistry
по ланцюжку URL → кеш → файл (README «Джерело OpenAPI-спеки»).
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.responses import install_handlers
from app.db.base import init_db
from app.routers import (
    accounts,
    app_api,
    auth_m1,
    auth_qr,
    extras,
    mystat_proxy,
    nutrition,
    system,
    telegram,
    plugins as plugins_router,
)
from app.services import notify_socket
from app.services import mystat_client as ms
from app.services import app_data
from app.telegram import poller
from app.spec.registry import SpecRegistry
from app.telegram import runtime as tg_runtime

_log = logging.getLogger("m1id")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    init_db()

    # окрема БД нотаток і паролів (notes.db) + одноразовий перенос зі старої
    from app.db.notes_db import init_notes_db
    init_notes_db()

    # окрема БД плагінів (plugins.db) + черга сповіщень
    from app.plugins.store import init_plugin_db
    from app.plugins import notify as plugin_notify
    init_plugin_db()
    outbox_task = asyncio.create_task(plugin_notify.outbox_flusher())
    # періодичне прибирання прострочених/відкликаних сесій
    purge_task = asyncio.create_task(_session_purge_loop())

    # окрема БД коротких посилань M1 Provider (links.db)
    from app.services.links import init_links_db
    init_links_db()

    registry = SpecRegistry()
    # m1-id/openapi.json — кореневий снапшот як fallback
    root_snapshot = Path(__file__).resolve().parents[2] / "openapi.json"
    source = registry.load_chain(
        spec_url=settings.spec_url,
        cache_dir=settings.spec_cache_dir,
        primary_file=Path(settings.spec_file),
        fallback_files=[root_snapshot],
    )
    app.state.settings = settings
    app.state.registry = registry
    st = registry.stats()
    print(f"[{settings.project_name}] БД: {settings.db_url}")
    print(f"[{settings.project_name}] спека: {st['operations']} операцій / "
          f"{st['paths']} шляхів / {st['schemas']} схем ← {source}")

    # ── прод-попередження (fail-loud перед публікацією) ──
    if settings.secret_key == "dev-insecure-change-me":
        print("[M1 ID] NOTE: M1ID_SECRET_KEY не задано — ключ підписів "
              "згенеровано в backend/.jwt_key (переживає рестарти). "
              "Для проду задай ключ в env і зроби бекап .jwt_key/.token_key.")
    try:
        from app.services import demo_schedule  # noqa: F401
        if settings.demo_schedule:
            print("[M1 ID] WARNING: УВІМКНЕНО ДЕМО-ХУК розкладу "
                  "(services/demo_schedule.py) — тиждень 2026-08-24 віддає "
                  "фейкові дані! Лише для навантажувального тесту.")
        else:
            print("[M1 ID] NOTE: demo_schedule.py знайдено, але вимкнено "
                  "(увімкнути: M1ID_DEMO_SCHEDULE=1). Перед продом файл "
                  "краще видалити.")
    except ImportError:
        pass

    # ── Telegram-бот (aiogram 3): живе в тому самому процесі, доступ до БД ──
    try:
        await asyncio.wait_for(tg_runtime.start_telegram(), timeout=25)
    except asyncio.TimeoutError:
        _log.warning("Telegram: ініціалізація не вклалась у 25с — "
                     "бот не запущено (перезапустіть сервіс)")
    except Exception as exc:  # fail-soft: API важливіший за бота
        _log.warning("Telegram: старт не вдався: %r", exc)

    # ── Notify-сокет MyStat: миттєві події + Автооцінювання («Додаткові») ──
    try:
        await asyncio.wait_for(notify_socket.start_all(), timeout=25)
    except asyncio.TimeoutError:
        _log.warning("Socket: ініціалізація не вклалась у 25с — "
                     "сокет не запущено (перезапустіть сервіс)")
    except Exception as exc:  # fail-soft: API важливіший за сокет
        _log.warning("Socket: старт не вдався: %r", exc)

    # ── Єдине життя сайту і бота: свіжі дані з mapi (хтось із сайту /
    #    сокета / циклу витягнув) → Telegram-poller одразу ганяє детекти
    #    по них. Без цього бот дізнавався про зміни лише на своєму
    #    30-хвилинному циклі, наче живе окремо від бекенду.
    app_data.on_fresh_data(poller.on_fresh_data)
    # Збір фото викладачів з відповідей оцінок/ДЗ (раз на добу на акаунт, у фоні)
    from app.services import teacher_photos
    app_data.on_fresh_data(teacher_photos.on_fresh_data)

    # ── Плагіни живляться зі спільного TG-циклу (telegram/poller.py:
    #    секції ТГ і плагінів об'єднані в один набір запитів) + хука
    #    on_fresh_data вище. Окремий плагін-полер прибрано — дублював
    #    запити до mapi.

    try:
        yield
    finally:
        # B8 fix: не лише .cancel() — чекаємо скасування задач, щоб
        # фонові цикли коректно завершились і БД-сесії закрились
        async def _await_cancel(task):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

        await asyncio.gather(
            _await_cancel(outbox_task),
            _await_cancel(purge_task),
            return_exceptions=True,
        )
        await notify_socket.stop_all()
        await tg_runtime.stop_telegram()
        await ms.close_async_client()
        # H3 fix: закриваємо спільний клієнт завантажень медіа links
        from app.services.links import close_dl_client
        await close_dl_client()
        _log.info("shutdown: httpx-пул закрито")


async def _session_purge_loop() -> None:
    """Раз на 6 годин прибирає прострочені/відкликані сесії (старт — одразу)."""
    from app.core.security import purge_stale_sessions
    from app.db.base import SessionLocal

    def _run() -> int:
        db = SessionLocal()
        try:
            return purge_stale_sessions(db)
        finally:
            db.close()

    while True:
        try:
            n = await asyncio.to_thread(_run)
            if n:
                _log.info("sessions: прибрано %d прострочених/відкликаних", n)
        except Exception as exc:  # fail-soft
            _log.warning("sessions: прибирання не вдалось: %r", exc)
        await asyncio.sleep(6 * 3600)


# ---------------------------------------------------------- access-лог

async def access_log_middleware(request: Request, call_next):
    """Короткий access-лог: метод, шлях, статус, тривалість.
    Тіло й заголовки (Authorization!) у лог не потрапляють — правило README."""
    t0 = time.perf_counter()
    response = await call_next(request)
    dt_ms = (time.perf_counter() - t0) * 1000
    path = request.url.path
    if not path.startswith("/api/health"):  # health пінгується часто
        _log.info("%s %s -> %s (%.0f ms)",
                  request.method, path, response.status_code, dt_ms)
    return response


def create_app() -> FastAPI:
    settings = get_settings()
    docs_on = bool(settings.docs_enabled or settings.debug)
    app = FastAPI(
        title=f"{settings.project_name} Backend",
        version=settings.version,
        description=(
            "Шлюз-структуризатор MyStat: акаунти M1 ID, spec-driven проксі "
            "та нормалізація відповідей у конверт {ok, data, meta, error}."
        ),
        lifespan=lifespan,
        # Swagger/ReDoc/openapi.json лише в дев-режимі або за M1ID_DOCS_ENABLED
        docs_url="/docs" if docs_on else None,
        redoc_url="/redoc" if docs_on else None,
        openapi_url="/openapi.json" if docs_on else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # expose: фронт читає X-File-Name в'ювера файлів (ім'я з
        # Content-Disposition апстріма) і Content-Disposition при
        # крос-доменному API (mapi.<domain>) — без цього браузер
        # блокує 200-відповідь (net::ERR_FAILED) і PDF/фото «не відкриваються».
        expose_headers=["X-File-Name", "Content-Disposition", "Content-Type"],
    )
    app.middleware("http")(access_log_middleware)

    install_handlers(app)

    app.include_router(system.router)
    app.include_router(auth_m1.router)
    app.include_router(auth_qr.router)
    app.include_router(accounts.router)
    app.include_router(app_api.router)
    app.include_router(nutrition.router)
    app.include_router(mystat_proxy.router)
    app.include_router(telegram.router)

    # Перегляд файлів ДЗ у браузері (proxy fs*.itstep.org → стрім)
    from app.routers import fileview as fileview_router
    app.include_router(fileview_router.router)
    
    from app.routers import widgets as widgets_router
    app.include_router(widgets_router.router)
    from app.routers import appearance as appearance_router
    app.include_router(appearance_router.router)
    from app.routers import notes as notes_router
    app.include_router(notes_router.router)
    from app.routers import notefiles as notefiles_router
    app.include_router(notefiles_router.router)
    app.include_router(extras.router)
    from app.routers import ws_sync
    app.include_router(ws_sync.router)
    app.include_router(plugins_router.router)
    from app.routers import teacher_photos as teacher_photos_router
    app.include_router(teacher_photos_router.router)

    # M1 Provider: публічний шлях /api/v1/files/* (без auth — slug і є секрет)
    # Один домен (m1id.xyz): фронт/воркер + цей самий бекенд. /api/v1/files/*
    # НЕ має оброблятися Cloudflare-воркером — має проксюватись на бекенд
    # (в CF: маршрут воркера з exclude /api/v1/files/* або правило проксі).
    from app.routers import links as links_router
    app.include_router(links_router.public_router)
    app.include_router(links_router.router)
    return app


app = create_app()
