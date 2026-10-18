"""Плагіни: об'єднане «живлення» даних разом із Telegram-циклом.

Раніше плагіни мали ВЛАСНИЙ цикл (120с, get_payloads без force). Це
дублювало запити до mapi: TG-полер і плагін-полер окремо тягнули ті самі
секції того самого акаунта, а частота (120с проти 1800с) відрізнялась.

Тепер (єдина архітектура «як у ТГ»):
  • цикл даних живе в telegram/poller.py: секції TG-конфіга і секції
    плагінів об'єднуються в ОДИН набір запитів на акаунт (force=True,
    30-хв вікно) — є ТГ і плагіни → один прохід обслуговує обидва;
  • свіжі дані з сайту/сокета (app_data.on_fresh_data) теж годують
    плагіни — той самий хук, що й для детектів ТГ;
  • тут лишаються: збір секцій плагінів (sections_by_account, з кешем 60с)
    і щоденний прохід on_daily (викликається з tg run_daily о 06:00).
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta

from sqlalchemy import select

from app.plugins.access import effective_permissions, may_run
from app.plugins.manifest import sections_for
from app.plugins.store import PluginInstall, PluginMeta, new_session

_log = logging.getLogger("m1id.plugins")

# Кеш збіру секцій: on_fresh_data може прилетіти часто (авто-оновлення
# сайту кожні 5 хв × юзери), а реєстр плагінів міняється рідко.
_SECS_CACHE_TTL = 60.0
_secs_cache: tuple[float, dict[int, list[str]]] | None = None


def _monday() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


def _collect_sections() -> dict[int, list[str]]:
    """Реєстр плагінів → {account_id: секції} для юзерів з активними
    плагінами з hook on_event (враховує account_seqs інсталяцій)."""
    try:
        db = new_session()
    except Exception as exc:
        _log.warning("plugin poller: plugins.db недоступна: %r", exc)
        return {}
    by_user: dict[int, list[tuple[list[str], list[int]]]] = {}
    try:
        rows = (db.execute(
            select(PluginMeta, PluginInstall)
            .join(PluginInstall, PluginInstall.plugin_id == PluginMeta.id)
            .where(PluginInstall.enabled == True))  # noqa: E712
            .all())
    except Exception as exc:
        _log.warning("plugin poller: реєстр недоступна: %r", exc)
        return {}
    finally:
        db.close()
    # user_id → [(perms, acc_seqs)]
    for meta, inst in rows:
        man = meta.manifest or {}
        hooks = man.get("hooks") or {}
        # лише дозволи, які юзер прийняв, і лише плагіни, яким дозволено
        # виконуватись для цього юзера (верифікація/автор/адмін)
        perms = effective_permissions(man.get("permissions"),
                                      inst.accepted_permissions)
        if not hooks.get("on_event") or not perms                 or not may_run(meta, inst.user_id):
            continue
        by_user.setdefault(inst.user_id, []).append(
            (perms, [int(x) for x in (inst.account_seqs or [])]))
    if not by_user:
        return {}

    from app.db.base import SessionLocal
    from app.db.models import MystatAccount

    mdb = SessionLocal()
    try:
        accs = (mdb.query(MystatAccount)
                .filter(MystatAccount.user_id.in_(list(by_user)),
                        MystatAccount.status != "disabled")
                .all())
    finally:
        mdb.close()
    monday_iso = _monday().isoformat()
    out: dict[int, list[str]] = {}
    for acc in accs:
        seq = getattr(acc, "user_seq", None)
        wanted: set[str] = set()
        for perms, acc_seqs in by_user.get(acc.user_id, []):
            if seq is not None and acc_seqs and int(seq) not in acc_seqs:
                continue  # ця інсталяція не обробляє даний акаунт
            wanted.update(sections_for(perms, monday_iso))
        if wanted:
            out[acc.id] = sorted(wanted)
    return out


def sections_by_account() -> dict[int, list[str]]:
    """{account_id: секції плагінів} з кешем 60с (реєстр міняється рідко,
    а хук on_fresh_data викликається на кожну свіжу порцію з сайту)."""
    global _secs_cache
    import time

    now = time.monotonic()
    if _secs_cache is not None and now - _secs_cache[0] < _SECS_CACHE_TTL:
        return _secs_cache[1]
    out = _collect_sections()
    _secs_cache = (now, out)
    return out


async def _daily_pass() -> None:
    """Раз на добу: хук on_daily для плагінів, що його декларують."""
    from app.plugins.service import dispatch_daily

    db = new_session()
    try:
        rows = (db.execute(
            select(PluginInstall.user_id, PluginInstall.plugin_id)
            .where(PluginInstall.enabled == True))  # noqa: E712
            .all())
    finally:
        db.close()
    seen: set[tuple[int, str]] = set()
    for uid, pid in rows:
        if (uid, pid) in seen:
            continue
        seen.add((uid, pid))
        try:
            await dispatch_daily(pid, uid)
        except Exception as exc:
            _log.warning("plugin on_daily %s/%s failed: %r", pid, uid, exc)