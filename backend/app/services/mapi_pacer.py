"""Pacер mapi-запитів фонового poller'а — режим «по запитах».

Ідея: замість «вікно ділиться на акаунти, всередині слота — пачка
запитів» вікно ділиться на ЗАПИТИ: якщо юзерів N і в кожного ~K
запитів, то інтервал = window / (N*K), і кожен запит отримує власний
момент часу. mapi бачить рівний потік (1 запит раз на інтервал)
незалежно від кількості акаунтів — жодних пачок, менший ризик
rate-limit на боці mapi.

Використання (лише фоновий цикл poller'а):
    pacer = RequestPacer(window / total_requests)
    ...
    await pacer.slot()      # перед кожним mapi-викликом (у fetch_one)

Інтерактивні запити (сайт, сокет fast-path) pacер НЕ проходять — там
користувач чекає на відповідь, штучна затримка недоречна.

Якщо перерва між циклами більша за вікно — таймлайн продовжується з
моменту виклику (at = max(_next, now)), тому pacер ніколи не «наздоганяє»
старі слоти після простою.
"""
from __future__ import annotations

import asyncio
import time


class RequestPacer:
    """Роздає слоти часу з фіксованим інтервалом. Перший запит — одразу."""

    def __init__(self, interval: float) -> None:
        self._interval = max(0.0, float(interval))
        self._next: float | None = None
        self._lock = asyncio.Lock()

    @property
    def interval(self) -> float:
        return self._interval

    async def slot(self) -> None:
        """Зайняти наступний слот (може зачекати до одного інтервалу)."""
        if self._interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            at = self._next if self._next is not None else now
            if at < now:  # після паузи (тихі години, повільний цикл)
                at = now
            self._next = at + self._interval
        delay = at - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)