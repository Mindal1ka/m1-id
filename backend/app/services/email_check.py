"""Перевірка e-mail «чи існує в природі» без SMTP-листів (рішення №7).

Ланцюг: синтаксис RFC → одноразові домени → DNS (MX, із fallback на A).
"""
from __future__ import annotations

import re
import time

import dns.exception
import dns.resolver

_EMAIL_RE = re.compile(
    r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)

# Невеликий вбудований блоклист; у проді можна винести у файл/таблицю.
_DISPOSABLE_DOMAINS = {
    "mailinator.com", "10minutemail.com", "guerrillamail.com", "yopmail.com",
    "temp-mail.org", "tempmail.com", "throwawaymail.com", "getnada.com",
    "dispostable.com", "sharklasers.com", "trashmail.com", "fakeinbox.com",
}

_resolver = dns.resolver.Resolver(configure=True)
_resolver.lifetime = 3.0

# TTL-кеш DNS-результатів за доменом: повторні реєстрації з того самого
# домену не б'ють DNS (і не займають threadpool на 3–9 секунд).
_DNS_CACHE: dict[str, tuple[float, tuple[bool, str | None]]] = {}
_DNS_TTL = 600.0


def check_email(email: str) -> tuple[bool, str | None]:
    """→ (валідний?, код помилки|None). Помилки: invalid_email_format,
    disposable_email, email_domain_not_found, email_domain_unreachable."""
    email = email.strip().lower()

    if not _EMAIL_RE.match(email):
        return False, "invalid_email_format"

    domain = email.rsplit("@", 1)[1]
    if domain in _DISPOSABLE_DOMAINS:
        return False, "disposable_email"

    now = time.monotonic()
    cached = _DNS_CACHE.get(domain)
    if cached is not None and now - cached[0] < _DNS_TTL:
        return cached[1]

    result = _dns_check(domain)
    if len(_DNS_CACHE) > 4096:  # страховка від росту
        _DNS_CACHE.clear()
    if result != (False, "email_domain_unreachable"):
        # таймаут DNS НЕ кешуємо: секундний збій резолвера не має
        # різати весь домен на 10 хвилин для всіх, хто реєструється.
        # NXDOMAIN/одноразові кешувати можна — вони стабільні.
        _DNS_CACHE[domain] = (now, result)
    return result


def _dns_check(domain: str) -> tuple[bool, str | None]:
    try:
        if _resolver.resolve(domain, "MX"):
            return True, None
    except dns.resolver.NXDOMAIN:
        return False, "email_domain_not_found"
    except (dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        pass  # MX немає — за RFC допустимий fallback на A-запис
    except dns.exception.Timeout:
        return False, "email_domain_unreachable"

    # A і AAAA перевіряємо ОКРЕМИМИ try: раніше `A or AAAA` не обчислював
    # AAAA, бо resolve("A") кидав NoAnswer раніше за `or` —
    # IPv6-only домени (валідні за RFC) відхилялися дарма.
    for rrtype in ("A", "AAAA"):
        try:
            if _resolver.resolve(domain, rrtype):
                return True, None
        except dns.resolver.NXDOMAIN:
            return False, "email_domain_not_found"
        except dns.exception.Timeout:
            return False, "email_domain_unreachable"
        except (dns.resolver.NoAnswer, dns.resolver.NoNameservers):
            continue  # цього запису немає — перевіряємо наступну
    return False, "email_domain_not_found"
