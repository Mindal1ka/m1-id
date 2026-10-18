"""Оркестрація виконання плагінів: збір аргументів (сліпі дані,
налаштування, storage), запуск хука, застосування результату
(персист storage, дії notify), cooldown-тротлінг подій.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict
from datetime import date, timedelta

from app.plugins import notify
from app.plugins.access import effective_permissions, may_run
from app.plugins.manifest import sections_for
from app.plugins.runner import run_hook
from app.plugins.sanitizer import Redactor, blind_payloads
from app.plugins.store import PluginInstall, PluginMeta, new_session
from app.telegram.logmask import install_masking

_log = logging.getLogger("m1id.plugins")
install_masking(_log)

# Кеші обмежені за розміром (LRU): інакше ключі (plugin, event, user, params)
# росли б без меж.
_CACHE_MAX = 4096


class _LRU(OrderedDict):
    """OrderedDict з витісненням найстаріших записів."""

    def put(self, key, value) -> None:
        self[key] = value
        self.move_to_end(key)
        while len(self) > _CACHE_MAX:
            self.popitem(last=False)


# cooldown подій: не частіше 1 запуску на (plugin, event, user) за 60с
_last_runs: _LRU = _LRU()
_COOLDOWN_S = 60.0
# ui_request: кеш результату на 3с (юзер може мити вкладку)
_last_ui: _LRU = _LRU()
_UI_COOLDOWN_S = 3.0
# Серіалізація «прочитати свіжий storage → злити патч → записати» на
# (user, plugin): паралельні хуки не затирають зміни один одного.
_storage_lock = threading.Lock()


def _monday_iso() -> str:
    today = date.today()
    return (today - timedelta(days=today.weekday())).isoformat()


def _cooldown_ok(key: tuple, cooldown: float) -> bool:
    now = time.monotonic()
    last = _last_runs.get(key)
    if last is not None and now - last < cooldown:
        return False
    _last_runs.put(key, now)
    return True


def _get_install(db, user_id: int, plugin_id: str) -> PluginInstall | None:
    return (db.query(PluginInstall)
            .filter(PluginInstall.user_id == user_id,
                    PluginInstall.plugin_id == plugin_id,
                    PluginInstall.enabled == True)  # noqa: E712
            .first())


def _get_meta(db, plugin_id: str) -> PluginMeta | None:
    return db.get(PluginMeta, plugin_id)


def _chat_id_for(user_id: int) -> int | None:
    """chat_id юзера: спершу tg link, потім конфіг акаунта."""
    from app.db.base import SessionLocal
    from app.db.models import TelegramAccountConfig, TelegramLink
    db = SessionLocal()
    try:
        link = (db.query(TelegramLink)
                .filter(TelegramLink.user_id == user_id).first())
        if link is not None and link.chat_id:
            return int(link.chat_id)
        cfg = (db.query(TelegramAccountConfig)
               .filter(TelegramAccountConfig.user_id == user_id,
                       TelegramAccountConfig.chat_id != 0)
               .first())
        return int(cfg.chat_id) if cfg else None
    finally:
        db.close()


async def _account_seqs_for(user_id: int, plugin_id: str) -> list[int]:
    """Які акаунти (user_seq) опрацьовує плагін: [] = усі."""
    db = new_session()
    try:
        inst = (db.query(PluginInstall)
                .filter_by(user_id=user_id, plugin_id=plugin_id).first())
        return list(inst.account_seqs or []) if inst else []
    finally:
        db.close()


class _BlindPayload(dict):
    """Сліпі дані + Redactor, яким їх створено (для unredact виходу)."""
    redactor: Redactor | None = None


async def _payload_for(meta: PluginMeta, user_id: int,
                       account_seqs: list[int] | None = None,
                       perms: list[str] | None = None) -> dict:
    """Сліпі дані секцій за ПЕРЕТИНОМ дозволів маніфесту й прийнятих юзером
    (perms; None -> усі дозволи маніфесту, лише для зворотної сумісності).

    account_seqs — вибрані юзером акаунти (порожньо = перший акаунт).
    """
    if perms is None:
        perms = meta.manifest.get("permissions") or []
    secs = sections_for(perms, _monday_iso())
    if not secs:
        return _BlindPayload()
    from app.db.base import SessionLocal
    from app.db.models import MystatAccount
    from app.services import app_data
    db = SessionLocal()
    try:
        q = (db.query(MystatAccount)
             .filter(MystatAccount.user_id == user_id,
                     MystatAccount.status != "disabled"))
        if account_seqs:
            q = q.filter(MystatAccount.user_seq.in_(account_seqs))
        acc = q.order_by(MystatAccount.user_seq).first()
        if acc is None:
            return _BlindPayload()
        payloads = await app_data.get_payloads(db, acc, secs)
    finally:
        db.close()
    blind, red = blind_payloads(user_id, meta.id, payloads)
    out = _BlindPayload(blind)
    out.redactor = red
    return out


def _settings(inst: PluginInstall | None) -> dict:
    return ((inst.settings if inst else None) or {})


def _load_json_dict(raw) -> dict:
    """storage у БД — JSON-рядок; пошкоджений/не-об'єкт -> {}."""
    try:
        val = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return val if isinstance(val, dict) else {}


def _snapshot(plugin_id: str, user_id: int) -> dict:
    """Знімок мета+інсталяції для запуску. Ключ 'error' — причина відмови
    (плагіна/інсталяції немає, не верифікований)."""
    db = new_session()
    try:
        meta = _get_meta(db, plugin_id)
        inst = _get_install(db, user_id, plugin_id)
        if meta is None:
            return {"error": "plugin_not_found"}
        if inst is None:
            return {"error": "not_installed"}
        manifest = meta.manifest or {}
        if not may_run(meta, user_id):
            return {"error": "plugin_unverified"}
        perms = effective_permissions(manifest.get("permissions"),
                                      inst.accepted_permissions)
        return {
            "meta": meta, "manifest": manifest, "perms": perms,
            "settings": _settings(inst),
            "storage": _load_json_dict(inst.storage),
            "account_seqs": list(inst.account_seqs or []),
            "limit_kb": int(manifest.get("storage_limit_kb", 64) or 64),
        }
    finally:
        db.close()


def _merge_storage(plugin_id: str, user_id: int, patch: dict,
                   limit_kb: int) -> bool:
    """Злити патч у СВІЖИЙ storage під локом. -> False, якщо перевищено ліміт."""
    with _storage_lock:
        db = new_session()
        try:
            row = _get_install(db, user_id, plugin_id)
            if row is None:
                return True
            merged = {**_load_json_dict(row.storage), **patch}
            raw = json.dumps(merged, ensure_ascii=False).encode("utf-8")
            if len(raw) > limit_kb * 1024:
                return False
            row.storage = raw.decode("utf-8")
            db.commit()
            return True
        finally:
            db.close()


async def _run_and_apply(plugin_id: str, user_id: int, hook: str,
                         trigger: str, trigger_detail: str,
                         args: dict, redactor: Redactor | None = None
                         ) -> dict:
    """Спільний хвіст: перевірки доступу -> резерв квот -> запуск хука ->
    persist storage -> дії notify -> лог.

    Дії плагіна прив'язані до прийнятих дозволів: storage — лише з
    «storage», notify — лише з «notify:telegram»."""
    snap = await asyncio.to_thread(_snapshot, plugin_id, user_id)
    if "error" in snap:
        return {"ok": False, "error": snap["error"]}
    manifest, perms = snap["manifest"], snap["perms"]
    if trigger == "button":
        known = {str(b.get("id")) for b in manifest.get("tg_buttons") or []
                 if isinstance(b, dict)}
        if str(args.get("button") or "") not in known:
            return {"ok": False, "error": "unknown_button"}

    args.setdefault("settings", snap["settings"])
    args.setdefault("storage",
                    snap["storage"] if "storage" in perms else {})
    limit_kb = snap["limit_kb"]

    try:
        notify.check_and_reserve(plugin_id, user_id)
    except notify.RateLimitExceeded as exc:
        return {"ok": False, "error": str(exc)}

    resp = await asyncio.to_thread(
        run_hook, plugin_id, hook, args, user_id, trigger, trigger_detail)
    if not resp.get("ok"):
        return resp

    result = resp.get("result") or {}
    # Redactor: плагін бачив псевдоніми (#T1) — у виході повертаємо реальні
    # значення (лише text/data/notify; storage лишається «сліпим»).
    if redactor is not None:
        for key in ("text", "data"):
            if key in result:
                result[key] = redactor.unredact_obj(result[key])
        if isinstance(result.get("notify"), list):
            result["notify"] = redactor.unredact_obj(result["notify"])
        resp["result"] = result

    # 1) storage-патч (з обмеженням розміру)
    patch = result.get("storage")
    if isinstance(patch, dict) and patch and "storage" in perms:
        fits = await asyncio.to_thread(
            _merge_storage, plugin_id, user_id, patch, limit_kb)
        if not fits:
            _log.warning("plugin %s user %s: storage перевищує %sКБ — "
                         "зміни відкинуто", plugin_id, user_id, limit_kb)
            resp["storage_overflow"] = True
    # 2) notify-дії -> черга з лімітами. T2: слот на ПЕРШЕ повідомлення
    # уже зарезервовано check_and_reserve() вище — резерви не задвоюються.
    first_slot_used = False
    items = result.get("notify") if "notify:telegram" in perms else None
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not item.get("text"):
            continue
        chat_id = _chat_id_for(user_id)
        if chat_id is None:
            break
        if first_slot_used:
            try:
                notify.check_and_reserve(plugin_id, user_id)
            except notify.RateLimitExceeded as exc:
                _log.info("notify blocked: plugin=%s user=%s (%s)",
                          plugin_id, user_id, exc)
                break
        first_slot_used = True
        notify.queue_notify(plugin_id, user_id, chat_id,
                            str(item["text"]),
                            str(item.get("priority") or "info"))
    return resp


def _quick_check(plugin_id: str, user_id: int) -> dict | None:
    """Знімок інсталяції або None (немає / вимкнено / не верифіковано) —
    без запуску коду."""
    snap = _snapshot(plugin_id, user_id)
    return None if "error" in snap else snap


async def dispatch_event(plugin_id: str, user_id: int, event: str,
                         payload: dict,
                         redactor: Redactor | None = None) -> dict | None:
    """on_event: подія poller/сокета -> запуск плагіна (cooldown 60с).

    payload уже відфільтрований за дозволами плагіна (events.py)."""
    snap = _quick_check(plugin_id, user_id)
    if snap is None:
        return None
    if not (snap["manifest"].get("hooks") or {}).get("on_event"):
        return None
    if not _cooldown_ok((plugin_id, "event", event, user_id), _COOLDOWN_S):
        return None
    return await _run_and_apply(
        plugin_id, user_id, hook="on_event", trigger="on_event",
        trigger_detail=event[:96],
        args={"event": event, "payload": payload}, redactor=redactor)


async def dispatch_daily(plugin_id: str, user_id: int) -> dict | None:
    """on_daily: раз на добу (з плагін-полера) -> payload за дозволами."""
    snap = _quick_check(plugin_id, user_id)
    if snap is None or not (snap["manifest"].get("hooks")
                            or {}).get("on_daily"):
        return None
    if not _cooldown_ok((plugin_id, "daily", user_id), 20 * 3600.0):
        return None
    payload = await _payload_for(snap["meta"], user_id,
                                 snap["account_seqs"], snap["perms"])
    return await _run_and_apply(
        plugin_id, user_id, hook="on_daily", trigger="on_daily",
        trigger_detail="daily", args={"payload": payload},
        redactor=getattr(payload, "redactor", None))


async def run_tg_command(plugin_id: str, user_id: int, command: str,
                         args_text: str) -> str:
    """TG-команда /<cmd> -> хук on_command_<cmd> -> текст у чат."""
    unavailable = ("⚠️ Плагін недоступний. Увімкніть його на сайті "
                   "(вкладка «Плагіни»).")
    snap = _quick_check(plugin_id, user_id)
    if snap is None:
        return unavailable
    declared = {str(c.get("command")) for c in
                snap["manifest"].get("tg_commands") or []
                if isinstance(c, dict)}
    if command not in declared:
        return unavailable
    payload = await _payload_for(snap["meta"], user_id,
                                 snap["account_seqs"], snap["perms"])
    resp = await _run_and_apply(
        plugin_id, user_id,
        hook=f"on_command_{command}", trigger="tg_command",
        trigger_detail=f"/{command}",
        args={"event": "tg_command", "args_text": args_text,
              "payload": payload},
        redactor=getattr(payload, "redactor", None))
    if not resp.get("ok"):
        err = str(resp.get("error") or "")
        if "RateLimitExceeded" in err:
            return ("🚫 Ліміт повідомлень вичерпано (60/год). "
                    "Спробуйте пізніше.")
        return f"⚠️ Помилка плагіна: {err[:300]}"
    return str((resp.get("result") or {}).get("text")
               or "✅ Готово.")


def _ui_key(plugin_id: str, user_id: int, params: dict) -> tuple:
    """Ключ кешу UI: параметри входять у ключ (різні params — різні дані)."""
    try:
        raw = json.dumps(params or {}, ensure_ascii=False, sort_keys=True,
                         default=str)
    except (TypeError, ValueError):
        raw = repr(params)
    return (plugin_id, "ui", user_id,
            hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest())


async def run_ui_request(plugin_id: str, user_id: int, params: dict) -> dict:
    """Вкладка/віджет плагіна відкрита юзером -> on_ui (кеш 3с).
    Потребує інсталяції (enabled) і права запуску (верифікація)."""
    params = params if isinstance(params, dict) else {}
    snap = _quick_check(plugin_id, user_id)
    if snap is None:
        return {"ok": False, "error": "not_installed"}
    ckey = _ui_key(plugin_id, user_id, params)
    cached = _last_ui.get(ckey)
    if cached and time.monotonic() - cached[0] < _UI_COOLDOWN_S:
        return cached[1]
    payload = await _payload_for(snap["meta"], user_id,
                                 snap["account_seqs"], snap["perms"])
    resp = await _run_and_apply(
        plugin_id, user_id, hook="on_ui", trigger="ui",
        trigger_detail=json.dumps(params, ensure_ascii=False)[:90],
        args={"event": "ui", "params": params, "payload": payload},
        redactor=getattr(payload, "redactor", None))
    if not resp.get("ok"):
        out = {"ok": False, "error": str(resp.get("error") or "")[:300]}
    else:
        out = {"ok": True,
               "data": (resp.get("result") or {}).get("data")}
    _last_ui.put(ckey, (time.monotonic(), out))
    return out
