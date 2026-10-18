"""Сповіщення від плагінів у Telegram з жорсткими лімітами.

Ліміти:
  • 60 повідомлень/год на ЮЗЕРА (усі плагіни разом);
  • 30 повідомлень/год на ПЛАГІН (один плагін не з'їдає квоту юзера);
  • Telegram RetryAfter → повідомлення лишається у черзі з retry_at;
  • при вичерпанні квоти запис отримує статус 'blocked' (лог лишається),
    плагін на етапі виконання отримує RateLimitExceeded у результаті.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from app.plugins.store import NotifyOutbox, new_session
from app.telegram.logmask import install_masking

_log = logging.getLogger("m1id.plugins")
install_masking(_log)  # H5: маскуємо токен бота у логах

USER_LIMIT = 60        # повідомлень/год на юзера (усі плагіни)
PLUGIN_LIMIT = 30      # повідомлень/год на плагін
FLUSH_EVERY_S = 2.0

_buckets: dict[str, deque[float]] = {}
# T1: _buckets мутується і з event loop, і з флашера — threading.Lock
# гарантує атомарність _hit з будь-якого потоку (deque сам по собі
# не потокобезпечний для складених операцій popleft+append)
_sync_lock = threading.Lock()


class RateLimitExceeded(Exception):
    """Плагіну віддається у результаті виконання як error."""


def _hit(key: str, limit: int) -> bool:
    now = time.monotonic()
    with _sync_lock:  # T1: мутації квот — під локом
        q = _buckets.setdefault(key, deque())
        while q and q[0] < now - 3600:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


def _peek(key: str, limit: int) -> bool:
    """N-M2 fix: перевірка без списання — чи є вільне місце у квоті."""
    now = time.monotonic()
    with _sync_lock:
        q = _buckets.get(key)
        while q and q[0] < now - 3600:
            q.popleft()
        return q is None or len(q) < limit


def check_and_reserve(plugin_id: str, user_id: int) -> None:
    """Синхронна ПЕРЕВІРКА квот (викликається runner'ом).
    Кидає RateLimitExceeded, якщо ліміт вичерпано.

    N-M2 fix: тут квота НЕ списується — раніше списання відбувалось
    двічі (тут і у флашері), тож фактичний ліміт був 30/год замість 60.
    Реальне списання тепер відбувається один раз — у queue_notify,
    коли повідомлення фактично потрапляє у чергу."""
    if not _peek(f"u{user_id}", USER_LIMIT):
        raise RateLimitExceeded(
            f"RateLimitExceeded: ліміт {USER_LIMIT} повід./год на користувача вичерпано")
    if not _peek(f"p{plugin_id}:u{user_id}", PLUGIN_LIMIT):
        raise RateLimitExceeded(
            f"RateLimitExceeded: ліміт {PLUGIN_LIMIT} повід./год на плагін «{plugin_id}» вичерпано")


def queue_notify(plugin_id: str, user_id: int, chat_id: int, text: str,
                 priority: str = "info") -> None:
    """Поставити повідомлення у чергу (викликається ПІСЛЯ run_hook).

    N-M2 fix: списання квоти — ЄДИНИМ місцем, тут. Якщо місця немає,
    запис одразу отримує статус 'blocked' (лог лишається, як і було)."""
    allowed = _hit(f"u{user_id}", USER_LIMIT) and \
        _hit(f"p{plugin_id}:u{user_id}", PLUGIN_LIMIT)
    db = new_session()
    try:
        db.add(NotifyOutbox(plugin_id=plugin_id, user_id=user_id,
                            chat_id=chat_id, text=str(text)[:4000],
                            priority=priority,
                            status="pending" if allowed else "blocked"))
        db.commit()
        if not allowed:
            _log.info("outbox: blocked at enqueue (rate limit) "
                      "plugin=%s user=%s", plugin_id, user_id)
    finally:
        db.close()


async def _flush_once() -> None:
    from app.telegram import bot as tg_bot

    db = new_session()
    try:
        rows = (db.query(NotifyOutbox)
                .filter(NotifyOutbox.status == "pending")
                .order_by(NotifyOutbox.id)
                .limit(20).all())
        for item in rows:
            if item.retry_at and item.retry_at > datetime.now(timezone.utc):
                continue
            # N-M2 fix: повторне списання у флашері прибрано — квоту
            # списано один раз у queue_notify при постановці в чергу.
            try:
                await tg_bot.send_text(item.chat_id, item.text)
                item.status = "sent"
            except Exception as exc:
                wrapped = wrap_send_exception(exc)
                if isinstance(wrapped, TelegramRetryAfter):
                    item.retry_at = datetime.now(timezone.utc) + timedelta(
                        seconds=wrapped.retry_after + 1)
                    _log.info("tg flood: retry in %.0fs", wrapped.retry_after)
                else:
                    item.status = "failed"
                    _log.warning("outbox send failed: %r", exc)
        db.commit()
    finally:
        db.close()


class TelegramRetryAfter(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"retry after {retry_after}s")
        self.retry_after = retry_after


# bot.send_text кидає aiogram-виняток RetryAfter — обгортаємо на нашу
# (щоб не тягнути aiogram у синхронні шари плагінів)
def wrap_send_exception(exc: Exception) -> Exception:
    name = type(exc).__name__
    if "RetryAfter" in name:
        retry = getattr(exc, "retry_after", 5)
        return TelegramRetryAfter(int(retry))
    return exc


async def outbox_flusher() -> None:
    """Живе у lifespan: флашить чергу кожні 2с."""
    while True:
        try:
            await _flush_once()
        except Exception as exc:  # черга важлива, але не смертельна
            _log.warning("outbox flush error: %r", exc)
        await asyncio.sleep(FLUSH_EVERY_S)