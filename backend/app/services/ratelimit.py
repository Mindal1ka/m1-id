"""Простий in-memory rate-limit для чутливих роутів (register/login),
per-користувацькі ліміти на важких роутах (proxy /api/app/*) та
лічильник невдалих входів за логіном (backoff).

У проді з >1 воркером потрібен redis — стани не розділяються між процесами.
"""
from __future__ import annotations

import ipaddress
import threading
import time
from collections import OrderedDict, deque

from fastapi import Depends, Request

from app.core.config import get_settings
from app.core.responses import ApiError
from app.deps import get_current_user
from app.db.models import User

# key -> (deque міток часу, довжина вікна в секундах).
# Вікно зберігаємо разом із бакетом: різні ліміти мають різні вікна, і
# прибирання за вікном «поточного» виклику видаляло б чужі бакети.
_buckets: dict[str, tuple[deque[float], int]] = {}
_lock = threading.Lock()
_last_prune = 0.0
_PRUNE_EVERY = 30.0
_MAX_BUCKETS = 100_000


# ------------------------------------------------------------ IP клієнта


def _valid_ip(value: str) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def _normalize_ip(ip: str) -> str:
    """IPv6 групуємо по /64: один абонент має цілу підмережу адрес, і
    без цього ліміт обходиться ротацією адреси в межах /64."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if addr.version == 6:
        return str(ipaddress.ip_network(f"{addr}/64", strict=False)
                   .network_address) + "/64"
    return ip


def client_ip(request: Request) -> str:
    """IP клієнта для лімітів.

    Заголовки проксі враховуємо ЛИШЕ при M1ID_TRUSTED_PROXY=1 (прод:
    Cloudflare -> Caddy -> app). Інакше клієнт сам підробить будь-який
    заголовок, тож беремо адресу TCP-піра.
    Порядок при довіреному проксі:
      1) CF-Connecting-IP — Cloudflare ставить його сам і перезаписує
         клієнтський;
      2) X-Forwarded-For: проксі ДОДАЮТЬ адресу свого піра в кінець, тож
         лівий хід підробляється клієнтом. Беремо запис, що додав
         крайній довірений хоп: parts[-trusted_proxy_hops];
      3) адреса TCP-піра."""
    settings = get_settings()
    peer = request.client.host if request.client else "unknown"
    if settings.trusted_proxy:
        cf = _valid_ip(request.headers.get("cf-connecting-ip") or "")
        if cf:
            return _normalize_ip(cf)
        xff = request.headers.get("x-forwarded-for") or ""
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        hops = max(1, int(getattr(settings, "trusted_proxy_hops", 1) or 1))
        if parts:
            ip = _valid_ip(parts[-hops] if len(parts) >= hops else parts[0])
            if ip:
                return _normalize_ip(ip)
    return _normalize_ip(peer)


# Зворотна сумісність зі старою назвою
_client_key = client_ip


# ------------------------------------------------------------ ядро


def _prune_locked(now: float) -> None:
    dead = [k for k, (q, window) in _buckets.items()
            if not q or q[-1] < now - window]
    for k in dead:
        del _buckets[k]
    if len(_buckets) > _MAX_BUCKETS:
        # аварійна межа пам'яті: лишаємо найсвіжіші
        keep = sorted(_buckets.items(), key=lambda kv: kv[1][0][-1],
                      reverse=True)[:_MAX_BUCKETS // 2]
        _buckets.clear()
        _buckets.update(keep)


def _hit(key: str, times: int, per_seconds: int) -> None:
    global _last_prune
    now = time.time()
    with _lock:
        if now - _last_prune > _PRUNE_EVERY:
            _prune_locked(now)
            _last_prune = now
        entry = _buckets.get(key)
        if entry is None:
            entry = (deque(), per_seconds)
            _buckets[key] = entry
        bucket = entry[0]
        while bucket and bucket[0] < now - per_seconds:
            bucket.popleft()
        if len(bucket) >= times:
            raise ApiError(
                429, "rate_limited", "__all__",
                f"too_many_requests, retry_in_{per_seconds}s",
            )
        bucket.append(now)


def _route_name(request: Request) -> str:
    """Стабільне ім'я роуту: шаблон шляху (/api/v1/files/{slug}), а не
    фактичний URL — інакше ліміт обходиться підстановкою різних slug."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return f"{request.method}:{path or request.url.path}"


def rate_limit(times: int = 10, per_seconds: int = 60,
               name: str | None = None):
    """Ковзне вікно на IP + ім'я лімітера. `name` — явний стабільний ключ
    (наприклад "public_links" для всіх публічних посилань); без нього
    береться шаблон шляху роуту. Для MVP достатньо; у проді — redis."""

    def dependency(request: Request) -> None:
        _hit(f"ip:{client_ip(request)}|{name or _route_name(request)}",
             times, per_seconds)

    return Depends(dependency)


def rate_limit_user(times: int = 300, per_seconds: int = 60,
                    name: str | None = None):
    """Ліміт на КОРИСТУВАЧА (не IP): захищає mapi від нестриманих клієнтів.
    get_current_user кешується FastAPI на запит — зайвого ходу в БД немає.
    Ключ = користувач + ім'я лімітера. Без `name` ім'я виводиться з
    параметрів (times/per_seconds): лімітери з однаковими параметрами
    ділять бакет (спільна квота), різні — ні (інакше один deque ганявся
    б із різними times і ліміти псували б один одного)."""
    limiter = name or f"u{times}/{per_seconds}"

    def dependency(request: Request,
                   user: User = Depends(get_current_user)) -> None:
        _hit(f"user:{user.id}|{limiter}", times, per_seconds)

    return Depends(dependency)


# ------------------------------------------------------------ backoff входу
# Лічильник невдалих входів за ЛОГІНОМ (на додачу до ліміту за IP):
# розподілений підбір пароля з багатьох IP до одного акаунта.
# Після _FREE_FAILS невдач вхід блокується з експоненційною паузою
# (30с, 60с, 120с ... до 15 хв) від останньої невдачі. Успішний вхід
# скидає лічильник.

_FAIL_WINDOW = 900.0          # невдачі старші за 15 хв забуваються
_FREE_FAILS = 5               # без пауз
_MAX_LOCK = 900.0
_MAX_FAIL_KEYS = 20_000

_fails: "OrderedDict[str, tuple[int, float]]" = OrderedDict()
_fails_lock = threading.Lock()


def _fail_key(login: str) -> str:
    return (login or "").strip().lower()[:255]


def login_backoff_check(login: str) -> None:
    """Кидає 429, якщо для логіна діє пауза після серії невдач."""
    key = _fail_key(login)
    now = time.time()
    with _fails_lock:
        rec = _fails.get(key)
        if rec is None:
            return
        count, last = rec
        if now - last > _FAIL_WINDOW:
            del _fails[key]
            return
        if count < _FREE_FAILS:
            return
        lock = min(30.0 * (2 ** (count - _FREE_FAILS)), _MAX_LOCK)
        wait = last + lock - now
    if wait > 0:
        raise ApiError(429, "login_locked", "login",
                       f"too_many_failed_logins, retry_in_{int(wait) + 1}s")


def login_backoff_fail(login: str) -> None:
    key = _fail_key(login)
    now = time.time()
    with _fails_lock:
        rec = _fails.get(key)
        count = 0 if rec is None or now - rec[1] > _FAIL_WINDOW else rec[0]
        _fails[key] = (count + 1, now)
        _fails.move_to_end(key)
        if len(_fails) > _MAX_FAIL_KEYS:
            # спершу протухлі, далі — найстаріші за порядком вставки
            for k in [k for k, (_, t) in _fails.items()
                      if now - t > _FAIL_WINDOW]:
                del _fails[k]
            while len(_fails) > _MAX_FAIL_KEYS:
                _fails.popitem(last=False)


def login_backoff_reset(login: str) -> None:
    with _fails_lock:
        _fails.pop(_fail_key(login), None)
