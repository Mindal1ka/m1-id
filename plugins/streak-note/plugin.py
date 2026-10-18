"""Плагін «streak-note»: нотатки юзера (storage) + команда /notes.

ctx — об'єкт з атрибутами (ctx.storage, ctx.payload, ...) і методом
ctx.get(ключ, за_замовчуванням). ctx.storage — dict з БД інсталяції.
"""
import html
import json

MAX_NOTE_LEN = 200            # символів на одну нотатку
MAX_NOTES = 50                # скільки нотаток тримаємо
STORAGE_LIMIT_BYTES = 8 * 1024   # = storage_limit_kb (8) з manifest.json
SHOWN_NOTES = 10


def _load(storage):
    """Список нотаток зі storage; dict, JSON-рядок або сміття -> список."""
    data = storage
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return []
    if not isinstance(data, dict):
        return []
    notes = data.get("notes")
    if not isinstance(notes, list):
        return []
    return [str(n) for n in notes if isinstance(n, (str, int, float))]


def _fit(notes):
    """Лишає останні MAX_NOTES нотаток і відкидає найстаріші, доки
    серіалізований storage не вміститься в STORAGE_LIMIT_BYTES."""
    notes = notes[-MAX_NOTES:]
    while notes:
        raw = json.dumps({"notes": notes}, ensure_ascii=False)
        if len(raw.encode("utf-8")) <= STORAGE_LIMIT_BYTES:
            break
        notes = notes[1:]
    return notes


def on_command_notes(ctx):
    notes = _load(ctx.storage)
    text = (ctx.get("args_text") or "").strip()
    if text:
        if len(text) > MAX_NOTE_LEN:
            return {"text": f"⚠️ Нотатка задовга: {len(text)} із "
                            f"{MAX_NOTE_LEN} символів."}
        notes = _fit(notes + [text])
        if not notes or notes[-1] != text:
            return {"text": "⚠️ Нотатка не вміщається у сховище."}
        return {"text": f"📝 Збережено ({len(notes)})",
                "storage": {"notes": notes}}
    if not notes:
        return {"text": "Нотаток немає. Напиши /notes <текст>, щоб зберегти."}
    # Telegram працює в режимі HTML: нотатки екрануємо
    lines = "\n".join(f"• {html.escape(n)}" for n in notes[-SHOWN_NOTES:])
    return {"text": "📝 <b>Твої нотатки</b>\n" + lines}


def on_ui(ctx):
    notes = _load(ctx.storage)
    # у вкладці це «сирий» текст (рендериться як textContent), без екранування
    return {"data": {"type": "list", "label": "Мої нотатки",
                     "items": [{"title": n} for n in notes[-SHOWN_NOTES:]]}}
