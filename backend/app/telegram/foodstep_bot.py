"""Telegram: розділ «Харчування» (FoodStep).

Флоу замовлення:
  /foodstep → 📅 Замовити → постачальник → меню списком → користувач пише
  набір через КОМИ: "1, 2 2, 15 3" (елемент, опційно кількість через
  пробіл) → вибір дат (інлайн-кнопки, мультивибір) → замовлення.

Автозамовлення налаштовується на сайті або тут; планувальник
(foodstep_scheduler) за N хвилин до спрацювання присилає попередження
з вибраною варіацією і кнопкою «Відмінити».
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date as _date, datetime, timedelta

from aiogram import BaseMiddleware, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, \
    InlineKeyboardMarkup, Message

from app.core.clock import naive_kyiv_now
from app.db.base import SessionLocal
from app.db.models import FoodstepConfig, FoodstepOrder, FoodstepVariation, \
    TelegramLink, User
from app.services import foodstep as fs
from app.telegram.bot import (_esc, _link_by_chat, _user_allowed, send_text,
                              site_url)

_log = logging.getLogger("m1id.tg.foodstep")

router = Router(name="foodstep")

WD_UK = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд")

# FSM у пам'яті: chat_id → стан замовлення (з TTL і верхньою межею розміру)
_sessions: dict[int, dict] = {}
_SESSION_TTL = 1800.0      # 30 хв без активності — сесія забувається
_SESSIONS_MAX = 1000


def _prune_sessions() -> None:
    now = time.monotonic()
    for k in [k for k, v in _sessions.items()
              if now - v.get("_ts", 0) > _SESSION_TTL]:
        _sessions.pop(k, None)
    if len(_sessions) > _SESSIONS_MAX:  # викидаємо найстаріші
        for k, _v in sorted(_sessions.items(),
                            key=lambda kv: kv[1].get("_ts", 0)
                            )[:len(_sessions) - _SESSIONS_MAX]:
            _sessions.pop(k, None)


def _sess(chat_id: int, create: bool = False) -> dict | None:
    """Сесія чату з перевіркою TTL; кожне звернення продовжує життя."""
    now = time.monotonic()
    st = _sessions.get(chat_id)
    if st is not None and now - st.get("_ts", 0) > _SESSION_TTL:
        _sessions.pop(chat_id, None)
        st = None
    if st is None:
        if not create:
            return None
        _prune_sessions()
        st = _sessions.setdefault(chat_id, {})
    st["_ts"] = now
    return st


# T6: ті самі правила доступу в групах, що й у bot.py — дані FoodStep
# (і дії від імені власника, зокрема замовлення за його паролем) бачить
# та виконує лише власник прив'язки.
def _denied(chat, from_id: int | None) -> bool:
    db = SessionLocal()
    try:
        if _link_by_chat(db, chat.id) is None:
            return False  # не прив'язаний — хендлер сам покаже підказку /start
        return not _user_allowed(db, chat, from_id)
    finally:
        db.close()


def _no_pl(chat) -> bool:
    """Прив'язаний користувач без жодного акаунта філії pl: FoodStep недоступний."""
    db = SessionLocal()
    try:
        link = _link_by_chat(db, chat.id)
        return link is not None and not fs.user_has_pl(db, link.user_id)
    finally:
        db.close()


NO_PL_TEXT = "🍴 Харчування недоступне: ваша філія не підтримується."


class _T6Guard(BaseMiddleware):
    """Inner-middleware: спрацьовує лише для хендлерів, чий фільтр збігся."""

    async def __call__(self, handler, event, data):
        if isinstance(event, CallbackQuery):
            chat = event.message.chat if event.message else None
            is_cb = True
        else:
            chat = getattr(event, "chat", None)
            is_cb = False
        from_id = event.from_user.id if getattr(event, "from_user", None) else None
        if chat is not None and _denied(chat, from_id):
            if is_cb:
                await event.answer("🔒 Лише для власника прив'язки",
                                   show_alert=True)
                return None
            if (getattr(event, "text", "") or "").startswith("/"):
                await event.answer("🔒 Дані доступні лише власнику прив'язки.")
                return None
            raise SkipHandler  # звичайний груповий текст не засмічуємо
        return await handler(event, data)


router.message.middleware(_T6Guard())
router.callback_query.middleware(_T6Guard())


def _fmt_d(d: _date) -> str:
    return d.strftime("%d.%m")


def _wd(d: _date) -> str:
    return WD_UK[d.weekday()]


def _day_label(d: _date) -> str:
    today = naive_kyiv_now().date()
    if d == today:
        return f"Сьогодні, {_fmt_d(d)}"
    if d == today + timedelta(days=1):
        return f"Завтра, {_fmt_d(d)}"
    return f"{_wd(d)}, {_fmt_d(d)}"


def _home_row() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="🏠 Головна", callback_data="home"),
            InlineKeyboardButton(text="🌐 M1 ID", url=site_url())]


def _kb(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    rows.append(_home_row())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _chat_of_user(db, user_id: int) -> int | None:
    link = db.query(TelegramLink).filter_by(user_id=user_id).first()
    return link.chat_id if link else None


def _user_of_chat(db, chat_id: int) -> User | None:
    link = _link_by_chat(db, chat_id)
    if link is None:
        return None
    return db.get(User, link.user_id)


def _cfg_of(db, user_id: int) -> FoodstepConfig:
    return fs.get_config(db, user_id)


# ---------------------------------------------------------------- головне меню


async def _main_menu(chat_id: int, edit_message: Message | None = None) -> None:
    db = SessionLocal()
    try:
        user = _user_of_chat(db, chat_id)
        if user is None:
            text = ("🍴 <b>Харчування (FoodStep)</b>\n\n"
                    "Спершу прив'яжи акаунт M1 ID: /start.")
            kb = _kb([])
            db.close()
            if edit_message is not None:
                try:
                    await edit_message.edit_text(text, reply_markup=kb)
                    return
                except Exception:
                    pass
            await send_text(chat_id, text, kb)
            return
        cfg = _cfg_of(db, user.id)
        pwd_ok = "✅" if cfg.password_enc else "❌"
        auto = "увімкнений" if cfg.auto_enabled else "вимкнений"
        text = (
            "🍴 <b>Харчування (FoodStep)</b>\n"
            f"Пароль: {pwd_ok}   Постачальник: {_esc(fs._SUPPLIER_TITLES.get(cfg.supplier, cfg.supplier))}\n"
            f"Автозамовлення: {auto} о {cfg.order_time}"
        )
        kb = _kb([
            [InlineKeyboardButton(text="📅 Замовити", callback_data="fs:ord")],
            [InlineKeyboardButton(text="📋 Мої замовлення", callback_data="fs:hist")],
            [InlineKeyboardButton(text="⚙️ Автозамовлення", callback_data="fs:auto")],
        ])
    finally:
        db.close()
    if edit_message is not None:
        try:
            await edit_message.edit_text(text, reply_markup=kb)
            return
        except Exception:
            pass
    await send_text(chat_id, text, kb)


@router.message(Command("foodstep"))
async def cmd_foodstep(message: Message) -> None:
    await _main_menu(message.chat.id)


# кнопка «🍴 Харчування» у меню /start (bot.menu_kb)
@router.callback_query(F.data == "fs:menu")
async def cb_menu(cb: CallbackQuery) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id if cb.message else cb.from_user.id
    await _main_menu(chat_id, cb.message)

# ---------------------------------------------------------------- вибір постачальника


@router.callback_query(F.data == "fs:ord")
async def cb_order(cb: CallbackQuery) -> None:
    await cb.answer()
    kb = _kb([[InlineKeyboardButton(text=f"{t}", callback_data=f"fs:sup:{s}")
               for s, t in (("dumpling", "🥟 Галушки"),
                            ("provinces", "🏞 Провінція"))]])
    await _edit_or_send(cb, "🍴 Обери постачальника:", kb)


async def _edit_or_send(cb: CallbackQuery, text: str,
                        kb: InlineKeyboardMarkup) -> None:
    if cb.message is not None:
        try:
            await cb.message.edit_text(text, reply_markup=kb)
            return
        except Exception:
            pass
        await cb.message.answer(text, reply_markup=kb)
    else:
        await send_text(cb.from_user.id if cb.from_user else 0, text, kb)


# ---------------------------------------------------------------- меню списком


@router.callback_query(F.data.startswith("fs:sup:"))
async def cb_supplier(cb: CallbackQuery) -> None:
    await cb.answer()
    supplier = (cb.data or "").split(":", 2)[2]
    try:
        menu = await fs.get_menu(supplier)
    except Exception:
        await _edit_or_send(cb, "⚠️ Меню недоступне (FoodStep не відповідає "
                                "або сайт змінився). Спробуй ще раз пізніше.",
                            _kb([[InlineKeyboardButton(
                                text="⬅️ Назад", callback_data="fs:ord")]]))
        return
    chat_id = cb.message.chat.id if cb.message else cb.from_user.id
    st = _sess(chat_id, create=True)
    st.update(step="basket", supplier=supplier, dishes=menu["dishes"],
              basket={}, dates=set())

    lines = [f"🍴 <b>{_esc(menu['supplier_title'])}</b> — меню",
             "Напиши список через коми: <code>1, 2 2, 15 3</code>",
             "(номер, через пробіл — кількість; якщо немає — 1 шт)\n"]
    n = 0
    for cat in menu["categories"]:
        if cat["name"]:
            lines.append(f"\n<b>{_esc(cat['name'])}</b>")
        for d in cat["dishes"]:
            n += 1
            d["_no"] = n
            lines.append(f"{n}. {_esc(d['title'])} — {d['price']} грн")
    st["max_no"] = n
    kb = _kb([
        [InlineKeyboardButton(text="✅ Далі → вибір дат", callback_data="fs:dts")],
        [InlineKeyboardButton(text="🔄 Інший постачальник", callback_data="fs:ord")],
    ])
    await _edit_or_send(cb, "\n".join(lines), kb)


# ---------------------------------------------------------------- парсинг вводу


def parse_basket(text: str, max_no: int) -> dict[int, int] | None:
    """'1, 2 2, 15 3' → {1:1, 2:2, 15:3}. None = не розібрали."""
    basket: dict[int, int] = {}
    for token in text.split(","):
        token = token.strip()
        if not token:
            return None
        parts = token.split()
        if len(parts) > 2:
            return None
        if not (parts[0].isascii() and parts[0].isdigit()):
            return None
        no = int(parts[0])
        if not 1 <= no <= max_no:
            return None
        count = 1
        if len(parts) == 2:
            if not (parts[1].isascii() and parts[1].isdigit()):
                return None
            count = int(parts[1])
            if not 1 <= count <= 20:
                return None
        basket[no] = basket.get(no, 0) + count
    return basket or None


def _basket_items(st: dict) -> list[dict]:
    items = []
    for no, count in sorted(st["basket"].items()):
        dish = st["dishes"][no - 1]
        items.append({"id": dish["id"], "count": count})
    return items


def _basket_text(st: dict) -> str:
    total = 0
    parts = []
    for no, count in sorted(st["basket"].items()):
        d = st["dishes"][no - 1]
        parts.append(f"{_esc(d['title'])} ×{count}")
        total += d["price"] * count
    return ", ".join(parts) + (f" — {total} грн" if total else "—")


@router.callback_query(F.data == "fs:clr")
async def cb_clear(cb: CallbackQuery) -> None:
    await cb.answer("Очищено")
    chat_id = cb.message.chat.id if cb.message else 0
    st = _sess(chat_id)
    if st:
        st["basket"] = {}
        st["dates"] = set()


# ---------------------------------------------------------------- вибір дат


@router.callback_query(F.data == "fs:dts")
async def cb_dates(cb: CallbackQuery) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id if cb.message else cb.from_user.id
    st = _sess(chat_id)
    if not st or not st.get("basket"):
        await _edit_or_send(cb, "Спершу обери страви 🍴", _kb(
            [[InlineKeyboardButton(text="⬅️ Назад", callback_data="fs:ord")]]))
        return
    db = SessionLocal()
    try:
        user = _user_of_chat(db, chat_id)
        ordered = fs.ordered_dates(
            db, user.id, naive_kyiv_now().date(),
            naive_kyiv_now().date() + timedelta(days=14)) if user else {}
    finally:
        db.close()

    def _date_btn(d: _date) -> InlineKeyboardButton:
        iso = d.isoformat()
        marks = []
        if iso in ordered:
            marks.append("✅")
        if iso in st["dates"]:
            marks.append("✔️")
        if d.weekday() >= 5:
            marks.append("🛌")
        return InlineKeyboardButton(
            text=f"{_wd(d)} {_fmt_d(d)}{''.join(marks)}",
            callback_data=f"fs:dt:{iso}")

    days = fs.next_days(14)
    rows = [_date_btn(d) for d in days]
    grid = [rows[i:i + 3] for i in range(0, len(rows), 3)]
    grid.append([InlineKeyboardButton(
        text=f"✅ Замовити ({len(st['dates'])} дат)",
        callback_data="fs:go"),
        InlineKeyboardButton(text="⬅️ Страви", callback_data="fs:ord")])
    dates_line = ", ".join(_fmt_d(_date.fromisoformat(x))
                           for x in sorted(st["dates"])) or "—"
    text = (f"🧺 {_basket_text(st)}\n\n📅 Обери дати (натискай по одній):\n"
            f"Вибрано: {dates_line}\n"
            "✅ — уже замовлено, 🛌 — вихідний")
    await _edit_or_send(cb, text, _kb(grid))


@router.callback_query(F.data.startswith("fs:dt:"))
async def cb_toggle_date(cb: CallbackQuery) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id if cb.message else 0
    st = _sess(chat_id)
    if not st:
        return
    iso = (cb.data or "").split(":", 2)[2]
    try:
        _date.fromisoformat(iso)
    except ValueError:
        return
    st.setdefault("dates", set()).symmetric_difference_update({iso})
    await cb_dates(cb)  # перемалювати


# ---------------------------------------------------------------- оформлення


@router.callback_query(F.data == "fs:go")
async def cb_submit(cb: CallbackQuery) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id if cb.message else 0
    st = _sess(chat_id)
    if not st or not st.get("basket") or not st.get("dates"):
        await _edit_or_send(cb, "Обери страви і дати 🍴📅", _kb(
            [[InlineKeyboardButton(text="⬅️ Меню", callback_data="fs:ord")]]))
        return
    db = SessionLocal()
    try:
        user = _user_of_chat(db, chat_id)
        if user is None:
            await _edit_or_send(cb, "Спершу прив'яжи акаунт: /start",
                                _kb([]))
            return
        cfg = _cfg_of(db, user.id)
        if not cfg.password_enc:
            await _edit_or_send(
                cb, "🔐 Пароль FoodStep не задано. Задай його на сайті: "
                    f"{site_url()} → вкладка «Харчування».", _kb([]))
            return
        items = _basket_items(st)
        pwd = fs.foodstep_password(cfg)
        results = []
        for d in sorted(st["dates"]):
            if fs.has_order(db, user.id, d):
                results.append({"date": d, "status": "already"})
                continue
            try:
                res = await fs.place_order(pwd, st["supplier"], d, items)
            except Exception:
                results.append({"date": d, "status": "Error"})
                continue
            status = "ok" if res["ok"] else "failed"
            _, created = fs.record_order(
                db, user.id, d, st["supplier"], items, res["total"],
                "manual", status)
            results.append({"date": d, "status": status,
                            "total": res["total"],
                            "message": res["message"],
                            "created": created})
    finally:
        db.close()
    lines = ["🍴 <b>Результат:</b>"]
    for r in results:
        d = _fmt_d(_date.fromisoformat(r["date"]))
        if r["status"] == "ok":
            lines.append(f"✅ {d} — замовлено ({r.get('total', 0)} грн)")
        elif r["status"] == "already":
            lines.append(f"ℹ️ {d} — уже замовлено раніше")
        elif r["status"] == "Failure":
            lines.append(f"❌ {d} — невірний пароль")
        else:
            lines.append(f"❌ {d} — {_esc(r.get('message') or 'помилка')}")
    risky = [r["date"] for r in results
             if _date.fromisoformat(r["date"]) == naive_kyiv_now().date()
             and naive_kyiv_now().hour >= 9 and r["status"] == "ok"]
    if risky:
        lines.append("⚠️ Після 9:00 замовлення на сьогодні може не "
                     "виконатися (дедлайн пройшов).")
    _sessions.pop(chat_id, None)
    await _edit_or_send(cb, "\n".join(lines), _kb([
        [InlineKeyboardButton(text="📅 Нове замовлення", callback_data="fs:ord")],
        [InlineKeyboardButton(text="📋 Мої замовлення", callback_data="fs:hist")],
    ]))


@router.callback_query(F.data == "fs:hist")
async def cb_history(cb: CallbackQuery) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id if cb.message else cb.from_user.id
    db = SessionLocal()
    try:
        user = _user_of_chat(db, chat_id)
        rows = fs.orders_view(db, user.id, 20) if user else []
    finally:
        db.close()
    if not rows:
        await _edit_or_send(cb, "Поки замовлень немає 🍴", _kb(
            [[InlineKeyboardButton(text="📅 Замовити", callback_data="fs:ord")]]))
        return
    lines = ["📋 <b>Мої замовлення</b>\n"]
    for r in rows:
        icon = "✅" if r["status"] == "ok" else "❌"
        src = "авто" if r["source"] == "auto" else "рука́ми"
        items = ", ".join(f"{_esc(i['title'])} ×{i['count']}"
                          for i in r["items"]) or "—"
        lines.append(f"{icon} {_fmt_d(_date.fromisoformat(r['date']))} "
                     f"({src}) — {items} — {r['total']} грн")
    await _edit_or_send(cb, "\n".join(lines), _kb([
        [InlineKeyboardButton(text="📅 Замовити", callback_data="fs:ord")]]))


# ---------------------------------------------------------------- автозамовлення


@router.callback_query(F.data == "fs:auto")
async def cb_auto(cb: CallbackQuery) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id if cb.message else cb.from_user.id
    db = SessionLocal()
    try:
        user = _user_of_chat(db, chat_id)
        if user is None:
            await _edit_or_send(cb, "Спершу прив'яжи акаунт: /start", _kb([]))
            return
        cfg = _cfg_of(db, user.id)
        variants = fs.variations_view(db, user.id)
    finally:
        db.close()
    on = "🔴 вимкнений" if not cfg.auto_enabled else "🟢 увімкнений"
    mode = "рандомна з варіацій" if cfg.auto_mode == "random" else "фіксована"
    text = (f"⚙️ <b>Автозамовлення</b>: {on}\n"
            f"Час: {cfg.order_time}   Попередження за {cfg.notify_minutes} хв\n"
            f"Режим: {mode}   Постачальник: "
            f"{_esc(fs._SUPPLIER_TITLES.get(cfg.supplier, cfg.supplier))}\n"
            f"Варіацій: {len(variants)}")
    kb = _kb([
        [InlineKeyboardButton(
            text="🔘 Увімкнути" if not cfg.auto_enabled else "⛔️ Вимкнути",
            callback_data="fs:auto:toggle")],
        [InlineKeyboardButton(text="➖ 30 хв", callback_data="fs:auto:t-30"),
         InlineKeyboardButton(text=f"⏰ {cfg.order_time}",
                              callback_data="noop"),
         InlineKeyboardButton(text="➕ 30 хв", callback_data="fs:auto:t+30")],
        [InlineKeyboardButton(
            text=f"🎯 Режим: {'фіксована' if cfg.auto_mode == 'random' else 'рандом'}",
            callback_data="fs:auto:mode")],
        [InlineKeyboardButton(text="📜 Варіації", callback_data="fs:vars")],
    ])
    await _edit_or_send(cb, text, kb)


def _apply_cfg(chat_id: int, mutate) -> None:
    db = SessionLocal()
    try:
        user = _user_of_chat(db, chat_id)
        if user is None:
            return
        cfg = _cfg_of(db, user.id)
        mutate(cfg)
        db.commit()
    finally:
        db.close()


@router.callback_query(F.data.startswith("fs:auto:"))
async def cb_auto_action(cb: CallbackQuery) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id if cb.message else 0
    action = (cb.data or "").split(":", 2)[2]

    def mutate(cfg: FoodstepConfig) -> None:
        if action == "toggle":
            cfg.auto_enabled = not cfg.auto_enabled
        elif action == "t+30":
            h, m = (int(x) for x in cfg.order_time.split(":"))
            m += 30
            h, m = (h + m // 60) % 24, m % 60
            cfg.order_time = f"{h:02d}:{m:02d}"
        elif action == "t-30":
            h, m = (int(x) for x in cfg.order_time.split(":"))
            m -= 30
            if m < 0:
                m += 60
                h = (h - 1) % 24
            cfg.order_time = f"{h:02d}:{m:02d}"
        elif action == "mode":
            cfg.auto_mode = "fixed" if cfg.auto_mode == "random" else "random"
        # дедлайн: не пізніше 8:00 (як і на сайті)
        h, m = (int(x) for x in cfg.order_time.split(":"))
        if h > 8 or (h == 8 and m > 0):
            cfg.order_time = "08:00"

    _apply_cfg(chat_id, mutate)
    await cb_auto(cb)  # перемалювати


@router.callback_query(F.data == "fs:vars")
async def cb_vars(cb: CallbackQuery) -> None:
    await cb.answer()
    chat_id = cb.message.chat.id if cb.message else cb.from_user.id
    db = SessionLocal()
    try:
        user = _user_of_chat(db, chat_id)
        variants = fs.variations_view(db, user.id) if user else []
    finally:
        db.close()
    lines = ["📜 <b>Варіації автозамовлення</b>\n"]
    if not variants:
        lines.append("Поки немає. Створи на сайті: оформи набір страв у "
                     "вкладці «Харчування» → «💾 Зберегти як варіацію».")
    for v in variants:
        items = ", ".join(f"{_esc(i['title'])}×{i['count']}" for i in v["items"])
        lines.append(f"• <b>{_esc(v['name'])}</b>: {items}")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Автозамовлення", callback_data="fs:auto")],
        _home_row()])
    await _edit_or_send(cb, "\n".join(lines), kb)


# ---------------------------------------------------------------- попередження автозамовлення


async def send_autoorder_warning(chat_id: int, user_id: int,
                                 variation: dict | None,
                                 order_at: datetime, supplier: str) -> None:
    """Викликає foodstep_scheduler за N хвилин до спрацювання:
    показує, ЯКА варіація буде замовлена, і дає відмінити."""
    left = max(0, int((order_at - naive_kyiv_now()).total_seconds() // 60))
    left_h = f"{left // 60} год {left % 60} хв" if left >= 60 else f"{left} хв"
    mode = "рандомна з варіацій"
    items = fs.items_human(variation["items"]) if variation else "—"
    name = _esc(variation["name"]) if variation else "варіацій немає ⚠️"
    text = (f"⏰ <b>Автозамовлення скоро спрацює</b> (за {left_h}, "
            f"о {order_at.strftime('%H:%M')})\n"
            f"Постачальник: {_esc(fs._SUPPLIER_TITLES.get(supplier, supplier))}\n"
            f"Варіація ({mode}): <b>{name}</b>\n{items}\n\n"
            "Все так, чи відмінити сьогодні?")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Відмінити",
                              callback_data="fs:aw:skip")],
        _home_row()])
    await send_text(chat_id, text, kb)


@router.callback_query(F.data == "fs:aw:skip")
async def cb_auto_warn(cb: CallbackQuery) -> None:
    """«❌ Відмінити» у попередженні автозамовлення (єдина кнопка)."""
    await cb.answer()
    chat_id = cb.message.chat.id if cb.message else 0
    _sessions.pop(chat_id, None)
    from app.telegram.foodstep_sched import _skips
    # цільова дата автозамовлення: до 9:00 — сьогодні, після — завтра
    # (та сама, що рахує планувальник; інакше «Відмінити» ввечері
    # не відміняє завтрашнє замовлення)
    iso = fs.default_target_date().isoformat()
    uid = _uid_of_chat(chat_id)
    if uid:
        _skips.add(f"{uid}:{iso}")
    # зберігаємо і в БД: переживає рестарт процесу
    db = SessionLocal()
    try:
        user = _user_of_chat(db, chat_id)
        if user:
            cfg = fs.get_config(db, user.id)
            sk = set(json.loads(cfg.skip_dates or "[]"))
            sk.add(iso)
            # чистимо минуле, щоб поле не росло без межі
            today = naive_kyiv_now().date().isoformat()
            sk = {d for d in sk if d >= today}
            cfg.skip_dates = json.dumps(sorted(sk))
            db.commit()
    finally:
        db.close()
    await _edit_or_send(cb, "⛔️ Автозамовлення відмінено.", _kb([]))


@router.callback_query(F.data.startswith("fs:cancel:"))
async def cb_cancel_order(cb: CallbackQuery) -> None:
    """«❌ Відмінити замовлення» під повідомленням про виконання
    автозамовлення: /ajax/delorder + журнал → cancelled."""
    await cb.answer()
    iso = (cb.data or "").split(":", 2)[2]
    chat_id = cb.message.chat.id if cb.message else 0
    db = SessionLocal()
    try:
        user = _user_of_chat(db, chat_id)
        if user is None:
            await _edit_or_send(cb, "Спершу прив'яжи акаунт: /start", _kb([]))
            return
        cfg = _cfg_of(db, user.id)
        if not cfg.password_enc:
            await _edit_or_send(cb, "🔐 Пароль FoodStep не задано.", _kb([]))
            return
        row = (db.query(FoodstepOrder)
               .filter_by(user_id=user.id, order_date=iso, status="ok")
               .first())
        if row is None:
            await _edit_or_send(cb, "Замовлення на цю дату не знайдено.",
                                _kb([]))
            return
        pwd = fs.foodstep_password(cfg)
        try:
            res = await fs.cancel_order(pwd, row.supplier, iso)
        except Exception:
            res = {"ok": False, "status": "Unknown", "password_failure": False}
        if res.get("password_failure"):
            await _edit_or_send(cb, "❌ FoodStep відмовив: невірний пароль.",
                                _kb([]))
            return
        row.status = "cancelled"
        db.commit()
        confirmed = " підтверджено FoodStep" if res.get("ok") else \
            ", але FoodStep не підтвердив — перевір на сайті"
        await _edit_or_send(
            cb, f"🗑 Замовлення на {_fmt_d(_date.fromisoformat(iso))} "
                f"скасовано{confirmed}.", _kb([]))
    finally:
        db.close()


def _uid_of_chat(chat_id: int) -> int | None:
    db = SessionLocal()
    try:
        user = _user_of_chat(db, chat_id)
        return user.id if user else None
    finally:
        db.close()


# Реєструється ОСТАННІМ і не чіпає команди (/...) — вони йдуть у свої хендлери.
@router.message(F.text, ~F.text.startswith("/"))
async def msg_basket(message: Message) -> None:
    """Текст без слеша: якщо є активна сесія замовлення — це набір страв."""
    chat_id = message.chat.id
    st = _sess(chat_id)
    if not st or st.get("step") != "basket":
        # не наша сесія — пропускаємо далі (хендлери bot.py, плагіни)
        from aiogram.dispatcher.event.bases import SkipHandler
        raise SkipHandler
    basket = parse_basket(message.text or "", st.get("max_no") or 0)
    if basket is None:
        await message.answer(
            "Не зрозумів 😅 Формат: <code>1, 2 2, 15 3</code> — "
            "номери через коми, кількість через пробіл після номера.")
        return
    st["basket"] = basket
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Далі → вибір дат",
                              callback_data="fs:dts")],
        [InlineKeyboardButton(text="🗑 Очистити", callback_data="fs:clr")],
    ])
    await message.answer(f"🧺 {_basket_text(st)}", reply_markup=kb)
