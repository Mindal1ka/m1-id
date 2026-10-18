"""Deep-link прив'язки Telegram: https://t.me/<bot>?start=<uid>-<ts_hex>-<hmac32>.

Підпис рахується від jwt-секрету + часу видачі: посилання живе _PAYLOAD_TTL
(24 год). Без часової мітки payload був вічним bearer-токеном: QR/URL з
вкладки «Telegram» міг потрапити на скріншот/в чат, і будь-хто через місяці
переприв'язав би сповіщення на СВІЙ чат (start_handler перезаписує chat_id).
Тепер застаріле посилання просто відхилене — на сайті генерується свіже.

T5: сигнатура — ПОВНИХ 32 hex-символи (були 10 hex = 40 біт, що
піддавалось brute-force в межах 24 год). Старі 10-символьні ланки
просто перестають валідуватися — на сайті генерується нова.

Формат: «123-18f2a4c0-a1b2c3d4e5…» (uid-hex-час-hmac32 від uid+час).
"""
from __future__ import annotations

import hashlib
import hmac
import time

from app.core.security import jwt_secret

# Строк дії deep-link. Свіжа ланка генерується на кожен запит
# /api/telegram/status, тому 24 год вистачає з запасом.
_PAYLOAD_TTL = 24 * 3600
_SIG_LEN = 32  # T5: повний HMAC-SHA256hex, обрізаний до 128 біт


def _signature(user_id: int, issued: int) -> str:
    msg = f"m1id-tg:{user_id}:{issued}".encode("utf-8")
    return hmac.new(jwt_secret().encode("utf-8"), msg,
                    hashlib.sha256).hexdigest()[:_SIG_LEN]


def make_start_payload(user_id: int) -> str:
    """user.id → payload для ?start=... (напр. «123-18f2a4c0-a1b2c3d4e5»)."""
    issued = int(time.time())
    return f"{user_id}-{issued:x}-{_signature(user_id, issued)}"


def parse_start_payload(payload: str) -> int | None:
    """Payload з /start → user.id або None (бітий підпис / протух)."""
    payload = (payload or "").strip()
    parts = payload.split("-")
    if len(parts) != 3:
        return None
    uid_raw, ts_raw, sig = parts
    if not (uid_raw.isascii() and uid_raw.isdigit()) or not ts_raw:
        return None
    try:
        issued = int(ts_raw, 16)
    except ValueError:
        return None
    user_id = int(uid_raw)
    if not hmac.compare_digest(sig, _signature(user_id, issued)):
        return None
    if time.time() - issued > _PAYLOAD_TTL:
        return None  # посилання протухло — потрібне нове з сайту
    return user_id
