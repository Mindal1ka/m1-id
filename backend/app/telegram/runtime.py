"""Життєвий цикл Telegram-бота: старт/стоп разом із FastAPI (lifespan).

Бот живе В ТОМУ Ж ПРОЦЕСІ, що й API: доступ до БД - прямий (SessionLocal),
дані MyStat - через спільний шар app_data. Токен - M1ID_TELEGRAM_BOT_TOKEN
(.env). Порожній токен / відсутній aiogram / невдалий getMe → бот
вимкнено, API працює як завжди (fail-soft).

Захист від дубля: ексклюзивний файловий lock (.tg_bot.lock) - якщо під
навантаженням API підніметься кілька воркерів, polling триматиме лише
перший (інакше Telegram віддає 409 на другий getUpdates).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

from app.core.config import BASE_DIR, get_settings
from app.telegram.logmask import install_masking

_log = logging.getLogger("m1id.tg")
install_masking(_log)  # H5: не логувати токен бота (aiogram-винятки містять url)

_lock_file = None          # тримаємо об'єкт - поки живий, lock діє
_tasks: set[asyncio.Task] = set()
_bot = None                # aiogram Bot | None
_username: str | None = None
_ondemand_ts = 0.0         # тротлінг on-demand getMe у статусі сайту


def bot_username() -> str | None:
    """Ім'я бота (з getMe під час старту) - для deep-link на сайті."""
    global _username
    if _username:
        return _username
    try:
        from app.telegram import bot as bot_mod
        return bot_mod.current_username()
    except Exception:
        return None


def is_running() -> bool:
    return bool(_tasks) and _bot is not None


def _try_file_lock(path: Path):
    """Ексклюзивний lock першим прибіжшим воркером (Windows: msvcrt)."""
    try:
        f = open(path, "w+")
    except OSError:
        return None
    try:
        if sys.platform == "win32":
            import msvcrt

            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        f.seek(0)
        f.truncate()
        f.write(str(os.getpid()))
        f.flush()
        return f
    except OSError:
        f.close()
        return None


async def start_telegram() -> None:
    """Виклик з lifespan. Ніколи не кидає виключень назовні."""
    global _bot, _username, _tasks, _lock_file
    settings = get_settings()
    token = (settings.telegram_bot_token or "").strip()
    if not token:
        _log.info("Telegram: M1ID_TELEGRAM_BOT_TOKEN не задано - бот вимкнено")
        return

    _lock_file = _try_file_lock(BASE_DIR / ".tg_bot.lock")
    if _lock_file is None:
        _log.info("Telegram: інший воркер уже тримає бота - тут не стартуємо")
        return

    try:
        from aiogram import Bot, Dispatcher
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode
        from aiogram.types import BotCommand
    except ImportError as exc:
        _log.warning("Telegram: aiogram не встановлено (%r) - бот вимкнено "
                     "(pip install -r requirements.txt)", exc)
        return

    from app.telegram import bot as bot_mod
    from app.telegram import poller as poller_mod

    bot = None
    try:
        bot = Bot(token=token, default=DefaultBotProperties(
            parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
        me = await bot.get_me()
    except Exception as exc:
        _log.error("Telegram: бота не запущено (getMe не вдався: %r) - "
                   "перевірте M1ID_TELEGRAM_BOT_TOKEN", exc)
        if bot is not None:
            try:
                await bot.session.close()
            except Exception:
                pass
        return

    _bot = bot
    _username = me.username
    bot_mod.bind(bot, me.username)

    dp = Dispatcher()
    # ВАЖЛИВО: foodstep ПЕРШИМ — інакше catch-all команд плагінів у
    # bot.router (F.text.regexp ^/...) проковтує /foodstep до нього.
    from app.telegram import foodstep_bot as fs_bot
    dp.include_router(fs_bot.router)
    dp.include_router(bot_mod.router)    # TG-команди плагінів (реєстр у plugins.db): реєструємо хендлери
    try:
        bot_mod.register_plugin_commands()
    except Exception as exc:
        _log.warning("Telegram: plugin commands не зареєстровано: %r", exc)
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Прив'язка акаунта / меню"),
            BotCommand(command="homework", description="Домашні завдання"),
            BotCommand(command="marks", description="Останні 50 оцінок"),
            BotCommand(command="schedule", description="Розклад: сьогодні й тиждень"),
            BotCommand(command="leaderboard", description="Лідерборд"),
            BotCommand(command="settings", description="Налаштування сповіщень"),
            BotCommand(command="foodstep", description="🍴 Харчування: замовити / автозаказ"),
            BotCommand(command="help", description="Довідка"),
        ])
    except Exception as exc:
        _log.warning("Telegram: set_my_commands не вдався: %r", exc)

    _tasks = {
        asyncio.create_task(dp.start_polling(bot, handle_signals=False),
                            name="tg-polling"),
        asyncio.create_task(poller_mod.run_poller(), name="tg-poller"),
        asyncio.create_task(poller_mod.run_daily(), name="tg-daily"),
    }
    # планувальник автозаказа FoodStep (хвилинний тік)
    from app.telegram import foodstep_sched as fs_sched
    _tasks.add(asyncio.create_task(fs_sched.run_scheduler(),
                                   name="fs-scheduler"))

    def _done(t: asyncio.Task) -> None:
        global _tasks, _bot
        if t.cancelled():
            _tasks.discard(t)
            return
        exc = t.exception()
        if exc is not None:
            _log.error("Telegram: задача %s впала: %r", t.get_name(), exc)
        # мертва задача не має лишатися у _tasks: інакше is_running()
        # назавжди бреше «працює», і сайт/тест-повідомлення йдуть у мертвого бота
        _tasks.discard(t)
        if t.get_name() == "tg-polling" and _bot is not None:
            # впав сам polling (напр. токен відкликано) — бот більше не живий:
            # чесно скидаємо статус (перезапуск лише рестартом сервісу)
            dead = _bot
            _bot = None

            async def _close() -> None:
                try:
                    await dead.session.close()
                except Exception:
                    pass

            try:
                asyncio.get_running_loop().create_task(_close())
            except RuntimeError:
                pass

    for t in _tasks:
        t.add_done_callback(_done)
    _log.info("Telegram: бот @%s запущено (polling + poller + daily 06:00)",
              me.username)


async def stop_telegram() -> None:
    global _tasks, _bot
    for t in _tasks:
        t.cancel()
    if _tasks:
        await asyncio.gather(*_tasks, return_exceptions=True)
    _tasks = []
    if _bot is not None:
        try:
            await _bot.session.close()
        except Exception:
            pass
    _bot = None
    _log.info("Telegram: бот зупинено")


async def send_to_chat(chat_id: int, text: str, kb=None) -> None:
    """Тестове сповіщення з сайту (POST /api/telegram/test)."""
    if not is_running():
        raise RuntimeError("telegram_bot_not_running")
    from app.telegram import bot as bot_mod

    await bot_mod.send_text(chat_id, text, kb)


async def ensure_username() -> str | None:
    """Ім'я бота для сайту, якщо lifespan-старт ще не встиг (лінke-вікно)."""
    global _username, _ondemand_ts
    if _username:
        return _username
    token = (get_settings().telegram_bot_token or "").strip()
    if not token:
        return None
    if time.monotonic() - _ondemand_ts < 60:  # не молотимо Telegram щозапиту
        return None
    _ondemand_ts = time.monotonic()
    try:
        from aiogram import Bot

        async def _fetch() -> str | None:
            async with Bot(token) as b:
                me = await b.get_me()
                return me.username

        _username = await asyncio.wait_for(_fetch(), timeout=10)
        return _username
    except Exception as exc:
        _log.warning("Telegram: on-demand getMe не вдався: %r", exc)
        return None
