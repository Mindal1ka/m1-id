"""Маскування секретів у логах (фіксує H5).

aiogram-винятки через %r містять method.url виду
https://api.telegram.org/bot<TOKEN>/getMe — токен осідав у лог-файлах.
TokenMaskFilter маскує /bot<token>/ у будь-якому повідомленні логера
(і сам токен з налаштувань, і generic-патерн bot<digits>:<secret>).
Фільтр встановлюється на всіх логерах telegram/ і plugins/ —
див. install_masking() / _log.addFilter у кожному модулі.
"""
from __future__ import annotations

import logging
import re

# generic-патерн: bot123456:AAExxxxx... (URL aiogram, токени у тексті)
_BOT_TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]{10,}")

_configured_token: str | None = None


def _configured() -> str | None:
    global _configured_token
    if _configured_token is None:
        try:
            from app.core.config import get_settings
            _configured_token = (get_settings().telegram_bot_token
                                 or "").strip() or None
        except Exception:
            _configured_token = ""
    return _configured_token or None


def sanitize(text: str) -> str:
    """Прибрати токен бота з довільного тексту (лог-повідомлення,
    str(exc), %r-представлення)."""
    s = str(text)
    tok = _configured()
    if tok:
        s = s.replace(tok, "<bot-token>")
        # і закодовані варіанти (url-encoding у шляхах/запитах)
        for enc_tok in (tok.replace(":", "%3A"), tok.replace(":", ":")):
            if enc_tok != tok:
                s = s.replace(enc_tok, "<bot-token>")
    s = _BOT_TOKEN_RE.sub("bot<TOKEN>", s)
    return s


class TokenMaskFilter(logging.Filter):
    """Обгортає повідомлення лога через sanitize() до запису."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            rendered = record.getMessage()
            record.msg = sanitize(rendered)
            record.args = None
        except Exception:
            pass
        return True


def install_masking(logger: logging.Logger) -> None:
    """Повісити маскувальний фільтр (ідемпотентно)."""
    for f in logger.filters:
        if isinstance(f, TokenMaskFilter):
            return
    logger.addFilter(TokenMaskFilter())