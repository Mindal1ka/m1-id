"""Єдине джерело часу для всього бекенда (fix B6).

Проблема: у різних модулях (app_api, mystat_proxy, notify_socket,
telegram/poller, links, auth_m1) час брався то як `datetime.now()`
(ЛОКАЛЬНА зона сервера), то як `datetime.now(timezone.utc)` — змішування
UTC і локального часу «зсуває» дати розкладу, снапшоти та тихі години,
якщо сервер не в UTC.

Правило: УСІ часові мітки в БД і логіці — наївний UTC
(`datetime.utcnow()`-семантика, бо SQLite не зберігає tzinfo).
Для показу користувачу конвертуй у локальну зону лише на межі
(серіалізація відповіді/Telegram-повідомлення).

Використовуй саме цей хелпер замість `datetime.now()` напряму.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


# ── Fallback-зона на випадок відсутності бази часових поясів ──
# Windows без pip-пакета `tzdata` (або системи без tz database) кидає
# ZoneInfoNotFoundError → раніше це падало цілим backend'ом на імпорті.
# Fallback реалізує офіційні правила Kyiv: EET (UTC+2) взимку, EEST (UTC+3)
# улітку — перехід останньої неділі березня 03:00 UTC → 04:00 UTC
# останньої неділі жовтня (same official rule, що й у tz database).


class _KyivRules(tzinfo):  # type: ignore[name-defined]
	"""Мінімальний tzinfo з офіційними правилами Europe/Kyiv (EET/EEST)."""

	def _is_dst(self, dt: datetime) -> bool:
		if dt.tzinfo is not None:
			dt = dt.replace(tzinfo=None)
		year = dt.year

		def _last_sunday(month: int) -> int:
			# остання неділя місяця
			d = datetime(year, month + 1, 1) - timedelta(days=1) \
				if month < 12 else datetime(year, 12, 31)
			return d.day - ((d.weekday() + 1) % 7)

		start = datetime(year, 3, _last_sunday(3), 3, 0)      # 03:00 UTC
		end = datetime(year, 10, _last_sunday(10), 4, 0)      # 04:00 UTC
		return start <= dt < end

	def utcoffset(self, dt: datetime | None) -> timedelta:
		return timedelta(hours=3 if dt is not None and self._is_dst(dt) else 2)

	def dst(self, dt: datetime | None) -> timedelta:
		return timedelta(hours=1) if dt is not None and self._is_dst(dt) \
			else timedelta()

	def tzname(self, dt: datetime | None) -> str:
		return 'EEST' if dt is not None and self._is_dst(dt) else 'EET'


try:
	# Проєктна зона: усі «людські» межі часу (тихі години, сесії, показ
	# користувачу) рахуємо за Києвом, незалежно від таймзони сервера.
	KYIV = ZoneInfo('Europe/Kyiv')
except ZoneInfoNotFoundError:
	# tzdata відсутній (типово: Windows без `pip install tzdata`).
	# Не валім імпорт — бермо fallback з офіційними правилами EET/EEST.
	KYIV = _KyivRules()  # type: ignore[assignment]


def naive_utcnow() -> datetime:
    """Наївний UTC «now» — єдиний формат часових міток у БД."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def naive_kyiv_now() -> datetime:
    """Наївний київський час «now» — для логіки добових меж
    (тихі години, добові ліміти, «сьогодні» тощо)."""
    return datetime.now(KYIV).replace(tzinfo=None)


def utc_to_kyiv(dt: datetime | None) -> datetime | None:
    """Конвертація наївного UTC (як у БД) → наївний київський час
    (для показу користувачу / TG-повідомлень)."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(KYIV).replace(tzinfo=None)


def kyiv_to_utc(dt: datetime) -> datetime:
    """Зворотна конвертація наївного київського часу → наївний UTC (БД)."""
    return dt.replace(tzinfo=KYIV).astimezone(timezone.utc).replace(tzinfo=None)
