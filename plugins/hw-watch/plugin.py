"""Плагін «hw-watch»: дедлайни домашки + вкладка з лічильником.

Хук-конвенція: функції on_event / on_ui / on_command_<cmd> / on_button_<id>
отримують ctx (ctx.event, ctx.payload, ctx.params, ctx.settings, ctx.storage)
і повертають dict: data / text / notify / storage.
ctx.storage — dict (або порожній dict), ctx.payload може бути порожнім.
"""
import html
import json
from datetime import datetime

# Статус завдання «до виконання» у даних homework (нормалізація app_data).
HW_STATUS_TODO = 3
DEFAULT_HOURS = 24.0
MAX_HOURS = 24.0 * 30
MAX_LINES = 5


def _dict(value):
    """Лише dict, інакше порожній dict (payload/storage можуть бути None)."""
    return value if isinstance(value, dict) else {}


def _to_float(value, default=0.0):
    """Безпечне float(): None, рядки-сміття, NaN/inf -> default."""
    try:
        num = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if num != num or num in (float("inf"), float("-inf")):
        return default
    return num


def _load_storage(raw):
    """storage як dict; рядок JSON або пошкоджені дані -> {}."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return _dict(json.loads(raw))
        except ValueError:
            return {}
    return {}


def _esc(value):
    """Екранування для Telegram HTML (поля йдуть з даних MyStat)."""
    return html.escape(str(value if value is not None else ""))


def on_event(ctx):
    if ctx.event != "homework.deadline_soon":
        return {}
    settings = _dict(ctx.settings)
    hours = min(max(_to_float(settings.get("hours_before"), DEFAULT_HOURS),
                    0.0), MAX_HOURS)
    prefix = str(settings.get("prefix") or "📚")[:8]
    items = _dict(ctx.payload).get("items")
    if not isinstance(items, list):
        items = []
    lines = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rem = _to_float(item.get("remaining_h"), 0.0)
        if 0 < rem <= hours:
            lines.append(f"• {_esc(item.get('subject'))} - "
                         f"{_esc(item.get('title'))} "
                         f"(до {_esc(item.get('due'))})")
    if not lines:
        return {}
    text = f"{_esc(prefix)} ⏰ Дедлайн близько!\n" + "\n".join(
        lines[:MAX_LINES])
    return {"notify": [{"text": text, "priority": "critical"}]}


def on_ui(ctx):
    homework = _dict(_dict(ctx.payload).get("homework"))
    items = homework.get("items")
    if not isinstance(items, list):
        items = []
    pending = [i for i in items
               if isinstance(i, dict) and i.get("status") == HW_STATUS_TODO]
    count = len(pending)

    state = _load_storage(ctx.storage)
    today = datetime.now().date().isoformat()
    last_day = state.get("last_day")
    result = {}
    if last_day != today:
        # Новий день: попереднє значення стає «минулого разу», а поточне
        # запам'ятовується ОДИН раз за добу (а не на кожному відкритті).
        prev = _to_float(state.get("last_count"), 0.0)
        prev_count = int(prev)
        result["storage"] = {"prev_count": prev_count,
                             "last_count": count, "last_day": today}
    else:
        prev_count = int(_to_float(state.get("prev_count"), 0.0))

    result["data"] = {
        "type": "stat",
        "label": "Невиконана домашка",
        "value": count,
        "extra": f"минулого разу: {prev_count}",
    }
    return result
