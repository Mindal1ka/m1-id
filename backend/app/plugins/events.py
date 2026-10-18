"""Шина подій: ядро (poller/сокет) емітить події → активні плагіни.

Події (payload — сліпі дані):
  data.fresh              — свіжі секції даних {sections, data}
  homework.deadline_soon  — щойно виявлені дедлайни {items}

Лямбда-модель: плагін прокидається, відпрацьовує (≤2с), вбивається.
Помилки плагінів не впливають на poller.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.plugins.access import effective_permissions
from app.plugins.manifest import SECTIONS_BY_PERM
from app.plugins.sanitizer import blind_payloads
from app.plugins.service import dispatch_event
from app.plugins.store import PluginInstall, PluginMeta, new_session

_log = logging.getLogger("m1id.plugins")

_tasks: set = set()


def _plugins_with_on_event(user_id: int) -> list[tuple[str, list, list]]:
    """Активні (enabled) плагіни юзера з hook on_event →
    [(id, account_seqs, ефективні_дозволи)].

    Ефективні дозволи = маніфест ∩ прийняте юзером (accepted_permissions).
    Ніколи не кидає: відсутня/неініціалізована plugins.db → порожній список.
    """
    try:
        db = new_session()
    except Exception as exc:
        _log.warning("plugin event lookup (db open) failed: %r", exc)
        return []
    try:
        rows = (db.execute(
            select(PluginMeta.id, PluginMeta.manifest,
                   PluginInstall.account_seqs,
                   PluginInstall.accepted_permissions)
            .join(PluginInstall, PluginInstall.plugin_id == PluginMeta.id)
            .where(PluginInstall.user_id == user_id,
                   PluginInstall.enabled == True))  # noqa: E712
            .all())
        return [(pid, acc or [],
                 effective_permissions((man or {}).get("permissions"),
                                       accepted))
                for pid, man, acc, accepted in rows
                if (man or {}).get("hooks", {}).get("on_event")]
    except Exception as exc:
        _log.warning("plugin event lookup failed: %r", exc)
        return []
    finally:
        db.close()


def _allowed_sections(perms: list[str]) -> set[str]:
    out: set[str] = set()
    for perm in perms:
        out.update(SECTIONS_BY_PERM.get(perm, []))
    return out


def _base_section(name: str) -> str:
    """'schedule_week@2026-10-12' -> 'schedule_week'."""
    return str(name).split("@", 1)[0]


def filter_payload_for(event: str, payload: dict,
                       perms: list[str]) -> dict | None:
    """Залишає в payload лише те, що дозволено правами плагіна.

    → відфільтрований payload або None, якщо плагіну нічого не належить
    (тоді подію йому не доставляємо).
      data.fresh              — секції за SECTIONS_BY_PERM;
      homework.deadline_soon  — потребує homework:read;
      інші події              — порожній payload (нічого зайвого)."""
    if event == "data.fresh":
        allowed = _allowed_sections(perms)
        data = payload.get("data") or {}
        kept = {sec: val for sec, val in data.items()
                if _base_section(sec) in allowed}
        if not kept:
            return None
        sections = [s for s in (payload.get("sections") or [])
                    if _base_section(s) in allowed]
        return {"sections": sections, "data": kept}
    if event == "homework.deadline_soon":
        if "homework:read" not in perms:
            return None
        return {"items": list(payload.get("items") or [])}
    return {}


def _spawn(coro) -> None:
    import asyncio
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def emit_account_event(account_id: int, user_id: int, sections: list[str],
                       payloads: dict, account_seq: int | None = None) -> None:
    """Хук від poller.on_fresh_data: прибули свіжі секції даних."""
    if not sections:
        return
    _spawn(_safe_dispatch_user(
        user_id, "data.fresh", {"sections": sections, "data": payloads},
        account_seq))


def emit_deadlines(user_id: int, items: list[dict],
                   account_seq: int | None = None) -> None:
    """Щойно виявлені дедлайни домашки (з _detect_deadlines)."""
    if items:
        _spawn(_safe_dispatch_user(user_id, "homework.deadline_soon",
                                   {"items": items}, account_seq))


async def _safe_dispatch_user(user_id: int, event: str, payload: dict,
                              account_seq: int | None = None) -> None:
    try:
        for pid, acc_seqs, perms in _plugins_with_on_event(user_id):
            # фільтр акаунтів: account_seqs порожній = усі акаунти юзера
            if (account_seq is not None and acc_seqs
                    and int(account_seq) not in acc_seqs):
                continue
            # фільтр за дозволами: плагін отримує лише свої секції
            part = filter_payload_for(event, payload, perms)
            if part is None:
                continue
            # сліпий API: псевдонімізація окремо під КОЖЕН плагін,
            # redactor йде в dispatch для unredact виходу
            if event == "data.fresh":
                bdata, red = blind_payloads(user_id, pid, part["data"])
                blind = {"sections": part["sections"], "data": bdata}
            else:
                blind, red = blind_payloads(user_id, pid, part)
            await dispatch_event(pid, user_id, event, blind, redactor=red)
    except Exception as exc:
        _log.warning("plugin event %s failed: %r", event, exc)
