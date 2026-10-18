"""Telegram-бот M1 ID (aiogram 3): прив'язка, меню, перегляд даних.

Прив'язка: сайт генерує deep-link https://t.me/<bot>?start=<uid>-<hmac10>
(payload підписаний jwt-секретом - див. linking.py). Ім'я бота НЕ
хардкодиться: воно береться з getMe під час старту (runtime.py).

Дані бот бере з нашої БД/кешу через app_data (той самий шар, що й
/api/app/*) - бот «бачить» ті самі дані, що й сайт, без окремих паролів.

Акаунти: якщо їх кілька - БОТ ПИТАЄ, ЧИЙ ПОКАЗАТИ, при КОЖНОМУ відкритті
розділу (запам'ятовування немає свідомо). В кожному розділі є кнопка
«Інший акаунт». Акаунти підписані ЛОГІНОМ (як і на сайті): ПІБ у людей
на різних акаунтах часто однакове, логін - унікальний.

Усі тексти - українською. Під кожним сповіщенням і в меню - кнопки
«Головна» (меню бота) та «M1 ID» (посилання на сайт).
"""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import date, timedelta

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.core.clock import naive_kyiv_now
from app.core.config import get_settings
from app.core.responses import ApiError
from app.db.base import SessionLocal
from app.db.models import MystatAccount, TelegramLink
from app.services import app_data
from app.telegram.linking import parse_start_payload
from app.telegram.logmask import install_masking

_log = logging.getLogger("m1id.tg")
install_masking(_log)  # H5: маскуємо токен у логах

router = Router(name="m1id")

_bot: Bot | None = None
_bot_username: str | None = None

WD_UK = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд")

WELCOME_UNLINKED = (
    "👋 Привіт! Це бот <b>M1 ID</b>.\n\n"
    "Щоб отримувати сповіщення (нова домашка, оцінки, зміни розкладу, "
    "рейтинг, лідерборд, магазин) і дивитися дані тут, прив'яжіть акаунт:\n"
    "відкрийте сайт → вкладка <b>Telegram</b> - там QR-код або "
    "кнопка-посилання особисто для вас."
)
NO_ACC_TEXT = (
    "📎 Спочатку прив'яжіть акаунт MyStat на сайті (розділ «Акаунти»), "
    "потім повертайтеся."
)
PICK_TEXT = "Оберіть акаунт:"

ACTIONS = ("hw", "marks", "sch", "lb")


def bind(bot: Bot, username: str | None) -> None:
    """Викликається з runtime.py після успішного getMe."""
    global _bot, _bot_username
    _bot = bot
    _bot_username = username


def current_username() -> str | None:
    return _bot_username


def site_url() -> str:
    return get_settings().telegram_site_url


# ---------------------------------------------------------------- клавіатури

def _chat_has_pl(chat_id: int | None) -> bool:
    """Чи має власник прив'язки акаунт філії pl (потрібно для FoodStep)."""
    if chat_id is None:
        return False
    from app.services.foodstep import user_has_pl
    db = SessionLocal()
    try:
        link = _link_by_chat(db, chat_id)
        return link is not None and user_has_pl(db, link.user_id)
    finally:
        db.close()


def menu_kb(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """Головне меню. Кнопка «Харчування» — лише якщо в чату є pl-акаунт."""
    site = InlineKeyboardButton(text="🌐 Відкрити M1 ID", url=site_url())
    last = ([InlineKeyboardButton(text="🍴 Харчування", callback_data="fs:menu"),
             site] if _chat_has_pl(chat_id) else [site])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 Домашки", callback_data="hw"),
         InlineKeyboardButton(text="🧮 Оцінки", callback_data="marks")],
        [InlineKeyboardButton(text="📅 Розклад", callback_data="sch"),
         InlineKeyboardButton(text="🏆 Лідерборд", callback_data="lb")],
        last,
    ])


def notify_kb() -> InlineKeyboardMarkup:
    """Кнопки під КОЖНИМ сповіщенням."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Головна", callback_data="home"),
         InlineKeyboardButton(text="M1 ID", url=site_url())],
    ])


def notify_hw_kb(hw_id: int, account_seq: int,
                 logbook_id: str | int = "") -> InlineKeyboardMarkup:
    """Сповіщення про домашку: пряме посилання на завдання на сайті
    (deep-link /app?account=N&hw=ID відкриває модалку з деталями).
    lb=<logbook_id> — перевірка на фронті, що посилання відкриває
    саме той акаунт (інакше показується помилка, а не чужі дані)."""
    url = f"{site_url()}/app?account={account_seq}&hw={hw_id}"
    if logbook_id:
        url += f"&lb={logbook_id}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📖 Відкрити завдання",
            url=url)],
        [InlineKeyboardButton(text="🏠 Головна", callback_data="home"),
         InlineKeyboardButton(text="M1 ID", url=site_url())],
    ])


def url_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Відкрити M1 ID", url=site_url())]])


# --- клавіатури розділу «Харчування» (FoodStep) — для повідомлень
# поза флоу foodstep_bot (планувальник, broadcast меню) ---

def foodstep_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Замовити", callback_data="fs:ord"),
         InlineKeyboardButton(text="📋 Замовлення", callback_data="fs:hist")],
        [InlineKeyboardButton(text="🏠 Головна", callback_data="home"),
         InlineKeyboardButton(text="M1 ID", url=site_url())],
    ])


def foodstep_error_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Замовити вручну", callback_data="fs:ord")],
        [InlineKeyboardButton(text="🏠 Головна", callback_data="home"),
         InlineKeyboardButton(text="M1 ID", url=site_url())],
    ])


def foodstep_cancel_kb(iso: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Відмінити замовлення",
                              callback_data=f"fs:cancel:{iso}")],
        [InlineKeyboardButton(text="🏠 Головна", callback_data="home"),
         InlineKeyboardButton(text="M1 ID", url=site_url())],
    ])


def _with_common(rows: list[list[InlineKeyboardButton]], change_cb: str | None,
                 site_label: str | None = None) -> InlineKeyboardMarkup:
    """Додає «Інший акаунт» (якщо є) + «Головна»/сайт у кінець клавіатури."""
    if change_cb:
        rows.append([InlineKeyboardButton(text="👤 Інший акаунт",
                                          callback_data=change_cb)])
    if site_label:
        rows.append([InlineKeyboardButton(text=site_label, url=site_url())])
    rows.append([InlineKeyboardButton(text="🏠 Головна", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------- формати

def _esc(v) -> str:
    return html.escape(str(v if v is not None else ""))


def _fmt_d(iso) -> str:
    """'2026-09-01…' → '01.09'."""
    s = str(iso or "")
    try:
        return f"{int(s[8:10]):02d}.{int(s[5:7]):02d}"
    except (ValueError, IndexError):
        return s[:10]


def _fmt_dt(iso) -> str:
    """'2026-09-03T23:55…' → '03.09 23:55'."""
    s = str(iso or "")
    if "T" in s:
        return f"{_fmt_d(s[:10])} {s[11:16]}"
    return _fmt_d(s)


def _wd_label(day_iso) -> str:
    try:
        d = date.fromisoformat(str(day_iso)[:10])
        return f"{WD_UK[d.weekday()]}, {_fmt_d(day_iso)}"
    except ValueError:
        return _fmt_d(day_iso)


def _chunks(text: str, limit: int = 3800) -> list[str]:
    """Розбивка по рядках під ліміт Telegram (4096). Рядок без \\n,
    довший за ліміт, ріжеться жорстко (інакше send_message падає)."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    cur = ""
    for line in text.split("\n"):
        # LOW: довгий рядок без \n — жорстке ріження по limit
        while len(line) > limit:
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(line[:limit])
            line = line[limit:]
        if cur and len(cur) + len(line) + 1 > limit:
            parts.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        parts.append(cur)
    return parts or [""]


async def send_text(chat_id: int, text: str,
                    kb: InlineKeyboardMarkup | None = None) -> None:
    """Надіслати повідомлення (авторозбивка на частини, кнопки - на першій)."""
    if _bot is None:
        raise RuntimeError("telegram_bot_not_running")
    parts = _chunks(text)
    for i, part in enumerate(parts):
        await _bot.send_message(chat_id, part, reply_markup=kb if i == 0 else None)
        if i < len(parts) - 1:
            await asyncio.sleep(0.35)  # ліміти Telegram


def fmt_lessons(lessons) -> list[str]:
    # Сортуємо за часом старту: MyStat віддає пари в довільному порядку,
    # а «номер» пари (lesson_no) - це слот розкладу з дірами (2..11),
    # не позиція в списку. Тому нумеруємо самі: 1..N за хронологією.
    ls = sorted((l for l in lessons or [] if isinstance(l, dict)),
                key=lambda x: (str(x.get("start") or ""),
                               str(x.get("end") or ""),
                               str(x.get("subject") or "")))
    lines: list[str] = []
    for i, l in enumerate(ls, 1):
        s = str(l.get("start") or "")[:5]
        e = str(l.get("end") or "")[:5]
        time_s = f"{s}-{e}" if s and e else (s or "")
        subj = _esc(l.get("subject") or "-")
        room = f", каб. {_esc(l.get('room'))}" if l.get("room") else ""
        head = f"{i}. "
        body = f"{time_s} " if time_s else ""
        lines.append(f"{head}{body}{subj}{room}")
    return lines


def fmt_today(day: dict | None, suffix: str = "",
              header: str = "📅 <b>Розклад на сьогодні</b>") -> str:
    lessons = (day or {}).get("lessons") or []
    title = header + suffix
    d_iso = str((day or {}).get("date") or "")
    if d_iso:
        title += f" ({_wd_label(d_iso)})"
    lines = fmt_lessons(lessons)
    if not lines:
        return f"{title}\n😴 Пар немає - гарного відпочинку!"
    return f"{title}\n" + "\n".join(lines)


def fmt_week(days, suffix: str = "") -> str:
    out = ["📅 <b>Розклад на тиждень</b>" + suffix]
    shown = False
    ordered = sorted([d for d in days or [] if isinstance(d, dict)],
                     key=lambda x: str(x.get("date") or ""))
    for d in ordered:
        lines = fmt_lessons(d.get("lessons"))
        if not lines:
            continue
        shown = True
        out.append(f"\n<b>{_wd_label(str(d.get('date') or ''))}</b>")
        out.extend(lines)
    if not shown:
        out.append("😴 Цього тижня пар немає.")
    return "\n".join(out)


# ---------------------------------------------------------------- БД-хелпери

def _link_by_chat(db, chat_id: int) -> TelegramLink | None:
    return db.query(TelegramLink).filter(TelegramLink.chat_id == chat_id).first()


# T5: rate-limit /start (і з валідним, і з битим payload) — brute-force
# захист сигнатури: не більше 10 спроб на чат за 5 хв
_START_RL_LIMIT = 10
_START_RL_WINDOW = 300.0
_start_rl: dict[int, list[float]] = {}


_START_RL_MAX_KEYS = 5000


def _start_rate_ok(chat_id: int) -> bool:
    import time as _time
    now = _time.monotonic()
    # обмежуємо словник: чистимо протухлі записи, а за потреби — найстаріші
    if len(_start_rl) > _START_RL_MAX_KEYS:
        for k in [k for k, v in _start_rl.items()
                  if not v or now - v[-1] >= _START_RL_WINDOW]:
            _start_rl.pop(k, None)
        while len(_start_rl) > _START_RL_MAX_KEYS:
            _start_rl.pop(next(iter(_start_rl)), None)
    hits = [t for t in _start_rl.get(chat_id, [])
            if now - t < _START_RL_WINDOW]
    if len(hits) >= _START_RL_LIMIT:
        _start_rl[chat_id] = hits
        return False
    hits.append(now)
    _start_rl[chat_id] = hits
    return True


def _user_allowed(db, chat, from_id: int | None) -> bool:
    """T6: авторизація for приватних і групових чатів.
    Приватний чат: chat_id сам є from.id — за лінком.
    Група: дані бачить лише власник прив'язки (у нього є приватний
    лінк з chat_id == from.id); решта учасників групи — ні."""
    link = _link_by_chat(db, chat.id)
    if link is None:
        return False
    if getattr(chat, "type", "private") == "private":
        return True
    if from_id is None:
        return False
    own = (db.query(TelegramLink)
           .filter(TelegramLink.user_id == link.user_id).all())
    return any(int(l.chat_id) == int(from_id) for l in own)


def _allowed_chat(chat, from_id: int | None) -> bool:
    """T6-перевірка з власною сесією БД (для хендлерів, що не тримають db)."""
    db = SessionLocal()
    try:
        return _user_allowed(db, chat, from_id)
    finally:
        db.close()


def _accounts(db, link: TelegramLink | None) -> list[MystatAccount]:
    if link is None:  # чат не прив'язаний
        return []
    return (db.query(MystatAccount)
            .filter(MystatAccount.user_id == link.user_id,
                    MystatAccount.status != "disabled")
            .order_by(MystatAccount.user_seq)
            .all())


def _acc_name(acc: MystatAccount) -> str:
    """ЛОГІН (як у виборі на сайті): ПІБ у людей однакове, логін - ні."""
    return (acc.mystat_login or acc.label or acc.fio
            or f"Акаунт #{acc.user_seq}")


def _resolve(db, chat_id: int, seq: int | None):
    """→ ("ok"|"no_link"|"no_acc", link, account, multi)."""
    link = _link_by_chat(db, chat_id)
    if link is None:
        return "no_link", None, None, False
    accs = _accounts(db, link)
    if not accs:
        return "no_acc", link, None, False
    acc = None
    if seq is not None:
        acc = next((a for a in accs if a.user_seq == seq), None)
    if acc is None:
        acc = accs[0]
    return "ok", link, acc, len(accs) > 1


def _err_text(exc: Exception) -> str:
    code = getattr(exc, "code", "")
    if code == "account_needs_relogin":
        return ("🔐 Потрібно знову увійти в MyStat на сайті - акаунт "
                "відв'язався. Після входу сповіщення продовжать працювати.")
    return "⚠️ MyStat тимчасово недоступний. Спробуйте за хвилину."


# ---------------------------------------------------------------- показ

def _entry_kb(action: str, accs: list[MystatAccount],
              params: str = "") -> InlineKeyboardMarkup:
    """Пікер акаунтів: кнопки з ЛОГІНАМИ (порядок як на сайті)."""
    rows = [[InlineKeyboardButton(
        text=_acc_name(a)[:60],
        callback_data=f"pick:{action}:{a.user_seq}" + (
            f":{params}" if params else ""))]
        for a in accs[:8]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _edit_or_send(msg: Message, text: str,
                        kb: InlineKeyboardMarkup | None = None) -> None:
    parts = _chunks(text)
    try:
        await msg.edit_text(parts[0], reply_markup=kb)
        for part in parts[1:]:
            await msg.answer(part)
        return
    except TelegramBadRequest as exc:
        if "not modified" in str(exc).lower():
            return
    except Exception as exc:
        _log.warning("tg edit failed: %r", exc)
    for i, part in enumerate(parts):
        await msg.answer(part, reply_markup=kb if i == 0 else None)


async def _render(msg: Message, action: str, seq: int | None, *,
                  force: bool = False, variant: str | None = None,
                  scope: str | None = None, period: str | None = None,
                  edit: bool = False, from_id: int | None = None) -> None:
    """Зібрати розділ (дані з app_data) і показати в чаті."""
    db = SessionLocal()
    try:
        # T6: у групах дані бачить лише власник прив'язки
        if not _user_allowed(db, msg.chat, from_id):
            await msg.answer("🔒 Дані доступні лише власнику прив'язки.")
            return
        st, _link, acc, multi = _resolve(db, msg.chat.id, seq)
    finally:
        db.close()
    if st == "no_link":
        await msg.answer(WELCOME_UNLINKED, reply_markup=url_kb())
        return
    if st == "no_acc" or acc is None:
        await msg.answer(NO_ACC_TEXT, reply_markup=url_kb())
        return
    r_scope = scope or "group"
    r_period = period or "month"
    try:
        if action == "hw":
            text, rows = await _view_homework(acc, multi, force=force)
        elif action == "marks":
            text, rows = await _view_marks(acc, multi, force=force)
        elif action == "sch":
            text, rows = await _view_schedule(acc, multi, variant or "today",
                                              force=force)
        else:
            text, rows, r_scope, r_period = await _view_leaderboard(
                acc, multi, scope, period, force=force)
    except ApiError as exc:
        text, rows = _err_text(exc), []
    except Exception as exc:
        _log.warning("tg view %s failed: %r", action, exc)
        text, rows = "⚠️ Не вдалося отримати дані. Спробуйте пізніше.", []
    if multi:  # у всіх розділах можна змінити акаунт
        if action == "sch":
            change_cb = f"acc:sch:{variant or 'today'}"
        elif action == "lb":
            # контекст - РЕАЛЬНО показані scope/period (вони могли
            # підстрахуватись першими доступними у view)
            change_cb = f"acc:lb:{r_scope}:{r_period}"
        else:
            change_cb = f"acc:{action}"
    else:
        change_cb = None
    kb = _with_common(rows, change_cb)
    if edit:
        await _edit_or_send(msg, text, kb)
    else:
        parts = _chunks(text)
        for i, part in enumerate(parts):
            await msg.answer(part, reply_markup=kb if i == 0 else None)


# ---------------------------------------------------------------- view-запити

async def _view_homework(acc: MystatAccount, multi: bool,
                         force: bool = False):
    db = SessionLocal()
    try:
        payloads = await app_data.get_payloads(db, acc, ["homework"],
                                               force=force)
    finally:
        db.close()
    view = app_data.homework_view(payloads)
    counts = view.get("counts") or {}
    items = view.get("items") or []
    head = "📚 <b>Домашні завдання</b>"
    if multi:
        head += f" - {_esc(_acc_name(acc))}"
    lines = [head,
             f"⏳ Виконати: {counts.get('pending', 0)} · 🔎 Перевіряється: "
             f"{counts.get('checking', 0)} · ✅ Виконано: {counts.get('done', 0)}"]
    dl = view.get("nearest_deadlines") or []
    if dl:
        lines.append("\n⏰ <b>Найближчі дедлайни:</b>")
        for d in dl[:5]:
            due = _fmt_dt(d.get("due"))
            lines.append(f"• {_esc(d.get('subject') or '')} - "
                         f"{_esc(d.get('title') or '-')}"
                         + (f" <i>(до {due})</i>" if due else ""))
    if items:
        lines.append("\n📋 <b>Завдання</b> (спочатку найгарячіші):")
        for it in items[:10]:
            st = it.get("status")
            ico = "✅" if st == 1 else "🔎" if st == 2 else "🔁" if it.get("is_retake") else "🟡"
            due = _fmt_dt(it.get("due"))
            tail = f" · до {due}" if due else ""
            if it.get("overdue_days"):
                tail += f" · ⚠️ прострочено на {it['overdue_days']} дн."
            lines.append(f"{ico} {_esc(it.get('subject') or '')} - "
                         f"{_esc(it.get('title') or '-')}{tail}")
        if len(items) > 10:
            lines.append(f"… і ще {len(items) - 10} - дивіться на сайті")
    rows = [[InlineKeyboardButton(text="🔄 Оновити",
                                  callback_data=f"hwr:{acc.user_seq}")]]
    return "\n".join(lines), rows


async def _view_marks(acc: MystatAccount, multi: bool, force: bool = False):
    db = SessionLocal()
    try:
        payloads = await app_data.get_payloads(db, acc, ["stat_marks_year"],
                                               force=force)
    finally:
        db.close()
    view = app_data.marks_view(payloads)
    items = view.get("items") or []
    head = "🧮 <b>Останні оцінки</b>"
    if multi:
        head += f" - {_esc(_acc_name(acc))}"
    lines = [head]
    if view.get("overall_avg") is not None:
        lines.append(f"Середній бал: <b>{view['overall_avg']}</b> · "
                     f"усього оцінок: {view.get('total_marks', 0)}")
    if not items:
        lines.append("Оцінок ще немає.")
    for m in items[:50]:
        theme = f" ({_esc(m['theme'])})" if m.get("theme") else ""
        lines.append(f"{_fmt_d(m.get('date'))} - <b>{m.get('mark')}</b> - "
                     f"{_esc(m.get('subject') or '-')}{theme}")
    rows = [[InlineKeyboardButton(text="🔄 Оновити",
                                  callback_data=f"marksr:{acc.user_seq}")]]
    return "\n".join(lines), rows


async def _view_schedule(acc: MystatAccount, multi: bool, variant: str,
                         force: bool = False):
    today_d = naive_kyiv_now().date()
    monday = today_d - timedelta(days=today_d.weekday())
    section = f"schedule_week@{monday.isoformat()}"
    db = SessionLocal()
    try:
        payloads = await app_data.get_payloads(db, acc, [section],
                                               force=force)
    finally:
        db.close()
    view = app_data.schedule_view(payloads, section)
    days = [d for d in view.get("days") or [] if isinstance(d, dict)]
    suffix = f" - {_esc(_acc_name(acc))}" if multi else ""
    if variant == "week":
        text = fmt_week(days, suffix=suffix)
    else:
        today = today_d.isoformat()
        day = next((d for d in days if str(d.get("date") or "")[:10] == today),
                   None)
        text = fmt_today(day, suffix=suffix)
    seq = acc.user_seq
    rows = [
        [InlineKeyboardButton(
            text="• Сьогодні" if variant == "today" else "Сьогодні",
            callback_data=f"sch:{seq}:today"),
         InlineKeyboardButton(
             text="• Тиждень" if variant == "week" else "Тиждень",
             callback_data=f"sch:{seq}:week")],
        [InlineKeyboardButton(text="🔄 Оновити",
                              callback_data=f"schf:{seq}:{variant}")],
    ]
    return text, rows


def _find_me(rows: list[dict], acc: MystatAccount) -> dict | None:
    """Власний рядок у таблиці лідерборду.

    1) за id_stud-простором: logbook_id рядка таблиці (напр. «14546»);
    2) потім id_user_storage (сумісність);
    3) fallback - за ПІБ, якщо збіг ЄДИНИЙ (ідентифікатори в live-таблиці
       не завжди збігаються, а «Ви: 12 місце - 14 балів» замість реальних
       13 місця і 65 балів - це обман користувача).
    """
    for cand in (str(acc.logbook_id or ""),
                 str(acc.id_user_storage or "")):
        if cand:
            for r in rows:
                if str(r.get("id") or "") == cand:
                    return r
    fio = str(acc.fio or "").strip().lower()
    if fio:
        hits = [r for r in rows
                if str(r.get("fio") or "").strip().lower() == fio]
        if len(hits) == 1:
            return hits[0]
    return None


async def _view_leaderboard(acc: MystatAccount, multi: bool,
                            scope: str | None, period: str | None,
                            force: bool = False):
    """Лідерборд. Гілки mapi різні (школа: month/semester/year,
    академія: month/all_time) - періоди беремо з view['scopes'] (динамічно,
    з live-відповіді), а scope/period підстраховуємо першим доступним.
    → (text, keyboard_rows, resolved_scope, resolved_period)."""
    db = SessionLocal()
    try:
        payloads = await app_data.get_payloads(
            db, acc, ["leader_points", "leader_table"], force=force)
    finally:
        db.close()
    view = app_data.leaderboard_view(payloads)
    meta = [m for m in view.get("scopes") or [] if isinstance(m, dict)]
    sections = view.get("sections") or {}
    if meta:
        s_keys = [str(m.get("key")) for m in meta]
        scope_r = scope if scope in s_keys else s_keys[0]
        smeta = next(m for m in meta if str(m.get("key")) == scope_r)
        pmeta = [p for p in smeta.get("periods") or [] if isinstance(p, dict)]
        p_keys = [str(p.get("key")) for p in pmeta]
        period_r = period if period in p_keys else \
            (p_keys[0] if p_keys else "month")
    else:  # зовсім немає таблиці - показуємо як є
        scope_r = scope or "group"
        period_r = period or "month"
        smeta = {"key": scope_r, "label": scope_r.capitalize()}
        pmeta = [{"key": period_r, "label": period_r.capitalize()}]
    sec = (sections.get(scope_r) or {}).get(period_r) or {}
    rows_l = [r for r in (sec.get("top") or []) + (sec.get("nearby") or [])
              if isinstance(r, dict)]
    s_lbl = str(smeta.get("label") or scope_r)
    p_lbl = next((str(p.get("label")) for p in pmeta
                  if str(p.get("key")) == period_r), period_r)
    head = (f"🏆 <b>Лідерборд</b> - {s_lbl.lower()} · "
            f"{p_lbl.lower()}")
    if multi:
        head += f" - {_esc(_acc_name(acc))}"
    lines = [head]
    if rows_l:
        for i, r in enumerate(rows_l[:10]):
            pos = r.get("position") or (i + 1)
            amt = r.get("amount")
            lines.append(f"{pos}. {_esc(r.get('fio') or '-')} - "
                         f"{amt if amt is not None else '-'}")
    else:
        lines.append("Поки що немає даних рейтингу.")
    me = _find_me(rows_l, acc)
    pts = (view.get("points") or {}).get(scope_r) or {}
    if me is not None:
        amt = me.get("amount")
        amount_s = f" - {amt} балів" if amt is not None else ""
        lines.append(f"\n👤 Ви: <b>{me.get('position') or '-'} місце</b>"
                     f"{amount_s}")
    elif pts.get("position") is not None:
        # у leader-points totalCount - НЕ бали користувача (ліміт/лічильник
        # учасників), тому тут бали не показуємо взагалі
        lines.append(f"\n👤 Ви: <b>{pts.get('position')} місце</b> "
                     f"(за даними лідер-поїнтів)")
    seq = acc.user_seq

    def _btn(m: dict, active_key: str, other: str) -> InlineKeyboardButton:
        """Кнопка перемикача: поточний варіант з «•», повні ключі в callback
        (scope/period тепер динамічні - не влазять у g/mo-коди)."""
        lbl = str(m.get("label") or m.get("key") or "?")
        return InlineKeyboardButton(
            text=("• " + lbl) if str(m.get("key")) == active_key else lbl,
            callback_data=f"lb:{seq}:{m.get('key')}:{other}")

    rows: list[list[InlineKeyboardButton]] = []
    if len(meta) > 1:  # охоплення малюємо лише якщо їх > 1
        rows.append([_btn(m, scope_r, period_r) for m in meta])
    if len(pmeta) > 1:  # періоди - лише якщо їх > 1
        rows.append([_btn(p, period_r, scope_r) for p in pmeta])
    rows.append([InlineKeyboardButton(
        text="🔄 Оновити", callback_data=f"lbf:{seq}:{scope_r}:{period_r}")])
    return "\n".join(lines), rows, scope_r, period_r


# ---------------------------------------------------------------- команди

@router.message(CommandStart())
async def start_handler(message: Message, command: CommandObject) -> None:
    """Прив'язка за deep-link (?start=<uid>-<sig>) або головне меню."""
    if message.chat is None:
        return
    # T5: rate-limit на /start (захист від brute-force HMAC-сигнатури)
    if not _start_rate_ok(message.chat.id):
        await message.answer("⏳ Занадто часто. Спробуйте за кілька хвилин.")
        return
    db = SessionLocal()
    try:
        payload = (command.args or "").strip()
        if payload:
            user_id = parse_start_payload(payload)
            if user_id is None:
                await message.answer(
                    "⚠️ Посилання недійсне або застаріле. Згенеруйте нове на "
                    "сайті: вкладка <b>Telegram</b>.")
                return
            from app.db.models import TelegramAccountConfig, User

            user = db.get(User, user_id)
            if user is None:
                await message.answer(
                    "⚠️ Користувача M1 ID не знайдено. Спочатку "
                    "зареєструйтеся на сайті.")
                return
            # T5: не перезаписуємо чужий активний chat_id — цей чат
            # уже прив'язаний до ІНШОГО користувача → відмова
            steal = (db.query(TelegramLink)
                     .filter(TelegramLink.chat_id == message.chat.id,
                             TelegramLink.user_id != user.id).first())
            if steal is not None:
                await message.answer(
                    "⚠️ Цей чат уже прив'язаний до іншого акаунта M1 ID. "
                    "Спочатку відв'яжіть його в того користувача.")
                return
            link = (db.query(TelegramLink)
                    .filter(TelegramLink.user_id == user.id).first())
            if link is None:
                link = TelegramLink(user_id=user.id,
                                    chat_id=message.chat.id)
                db.add(link)
            link.chat_id = message.chat.id
            link.bot_username = _bot_username or ""
            db.flush()
            # конфіг на кожен існуючий акаунт юзера (дефолти), і синк chat_id
            accs = (db.query(MystatAccount)
                    .filter(MystatAccount.user_id == user.id,
                            MystatAccount.status != "disabled").all())
            for a in accs:
                cfg = (db.query(TelegramAccountConfig)
                       .filter(TelegramAccountConfig.account_id == a.id)
                       .first())
                if cfg is None:
                    db.add(TelegramAccountConfig(account_id=a.id,
                                                 user_id=user.id,
                                                 chat_id=message.chat.id))
                else:
                    cfg.chat_id = message.chat.id
            db.commit()
            await message.answer(
                f"✅ Акаунт <b>{_esc(user.username)}</b> прив'язано!\n\n"
                "Сповіщення налаштовуються на сайті: вкладка <b>Telegram</b> "
                "(для кожного акаунта окремо). Перший цикл оновлення "
                "(до 30 хв) - калібрувальний, сповіщення прийдуть після "
                "нього.\n\nОберіть розділ:",
                reply_markup=menu_kb(message.chat.id))
            return
        if _link_by_chat(db, message.chat.id) is None:
            await message.answer(WELCOME_UNLINKED, reply_markup=url_kb())
            return
        await message.answer("👋 <b>M1 ID</b> - оберіть розділ:",
                             reply_markup=menu_kb(message.chat.id))
    finally:
        db.close()


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    await message.answer(
        "🤖 <b>M1 ID - довідка</b>\n\n"
        "/homework - 📚 домашні завдання\n"
        "/marks - 🧮 останні 50 оцінок\n"
        "/schedule - 📅 розклад на сьогодні й тиждень\n"
        "/leaderboard - 🏆 лідерборд\n"
        "/settings - ⚙️ сповіщення (вкладка Telegram на сайті)\n\n"
        "Якщо акаунтів кілька - бот питатиме, чий показати, при кожному "
        "відкритті розділу (і в кожному розділі є кнопка «Інший акаунт»).",
        reply_markup=menu_kb(message.chat.id))


@router.message(Command("settings"))
async def settings_handler(message: Message) -> None:
    await message.answer(
        "⚙️ <b>Сповіщення</b> - на сайті, вкладка «Telegram».\n"
        "Для кожного акаунта свій конфіг: домашка, оцінки, розклад, "
        "рейтинг, лідерборд, магазин, тихі години. Там же можна "
        "відв'язати акаунт.",
        reply_markup=url_kb())


async def _entry_message(message: Message, action: str) -> None:
    """Спільна точка входу команд: прив'язка → вибір акаунта → розділ."""
    if message.chat is None:
        return
    from_id = message.from_user.id if message.from_user else None
    db = SessionLocal()
    try:
        link = _link_by_chat(db, message.chat.id)
        if link is None:
            await message.answer(WELCOME_UNLINKED, reply_markup=url_kb())
            return
        # T6: у групах дані (і навіть список акаунтів) — лише власнику
        if not _user_allowed(db, message.chat, from_id):
            await message.answer("🔒 Дані доступні лише власнику прив'язки.")
            return
        accs = _accounts(db, link)
    finally:
        db.close()
    if not accs:
        await message.answer(NO_ACC_TEXT, reply_markup=url_kb())
        return
    if len(accs) > 1:  # ПИТАЄМО при кожному відкритті
        await message.answer(PICK_TEXT,
                             reply_markup=_entry_kb(action, accs))
        return
    try:
        if _bot is not None:
            await _bot.send_chat_action(message.chat.id, "typing")
    except Exception:
        pass
    await _render(message, action, accs[0].user_seq, from_id=from_id)


@router.message(Command("homework"))
async def cmd_homework(message: Message) -> None:
    await _entry_message(message, "hw")


@router.message(Command("marks"))
async def cmd_marks(message: Message) -> None:
    await _entry_message(message, "marks")


@router.message(Command("schedule"))
async def cmd_schedule(message: Message) -> None:
    await _entry_message(message, "sch")


@router.message(Command("leaderboard"))
async def cmd_leaderboard(message: Message) -> None:
    await _entry_message(message, "lb")


# ---------------------------------------------------------------- плагіни

def register_plugin_commands() -> None:
    """Динамічні TG-команди плагінів (plugins.db).

    Реєстр читається з БД на КОЖНЕ повідомлення — нові /команди,
    завантажені після старту бота, працюють без перезапуску.
    Хендлер зареєстровано останнім (після всіх статичних Command-хендлерів),
    тож системні команди (/start, /homework, ...) пріоритетніші; якщо команда
    не належить жодному плагіну — мовчки ігноруємо (як і раніше).
    """
    from aiogram import F

    @router.message(F.text.regexp(r"^/([A-Za-z0-9_]+)(@\S+)?"))
    async def _plugin_cmd(message: Message) -> None:
        if message.chat is None or not message.text:
            return
        cmd_name = (message.text.split()[0].lstrip("/")
                    .split("@")[0].lower())
        from app.plugins.store import TgCommand, new_session

        db = new_session()
        try:
            row = (db.query(TgCommand)
                   .filter(TgCommand.command == cmd_name).first())
        finally:
            db.close()
        if row is None:
            return
        user_id = _user_by_chat(message.chat.id)
        if user_id is None:
            await message.answer(
                "🔌 Ця команда належить плагіну M1 ID. Спочатку прив'яжіть "
                "акаунт: /start")
            return
        # T6: у групах команди плагінів — лише для власника прив'язки
        db2 = SessionLocal()
        try:
            allowed = _user_allowed(db2, message.chat,
                                    message.from_user.id if message.from_user
                                    else None)
        finally:
            db2.close()
        if not allowed:
            await message.answer("🔒 Команди плагінів — лише для "
                                 "власника прив'язки.")
            return
        args_text = (message.text.split(None, 1)[1]
                     if len(message.text.split(None, 1)) > 1 else "")
        from app.plugins.service import run_tg_command

        text = await run_tg_command(row.plugin_id, user_id, cmd_name,
                                    args_text)
        await message.answer(text, reply_markup=url_kb())


def _user_by_chat(chat_id: int) -> int | None:
    from app.db.models import TelegramLink

    db = SessionLocal()
    try:
        link = _link_by_chat(db, chat_id)
        return link.user_id if link else None
    finally:
        db.close()


def _fid(cb: CallbackQuery) -> int | None:
    """T6: id користувача, який натиснув кнопку (для авторизації)."""
    return cb.from_user.id if cb.from_user else None


@router.callback_query(F.data.startswith("plg:"))
async def cb_plugin_button(cb: CallbackQuery) -> None:
    """Кнопка плагіна: plg:<plugin_id>:<button_id> → хук on_button_<id>."""
    await cb.answer()
    parts = (cb.data or "").split(":")
    if len(parts) != 3 or cb.message is None or cb.message.chat is None:
        return
    plugin_id, button_id = parts[1], parts[2]
    user_id = _user_by_chat(cb.message.chat.id)
    if user_id is None:
        await cb.message.answer(
            "🔌 Плагіни M1 ID: спочатку прив'яжіть акаунт (/start).")
        return
    # T6: група — лише власник прив'язки
    db_chk = SessionLocal()
    try:
        allowed = _user_allowed(db_chk, cb.message.chat, _fid(cb))
    finally:
        db_chk.close()
    if not allowed:
        await cb.message.answer("🔒 Кнопки плагінів — лише для "
                                "власника прив'язки.")
        return
    from app.plugins.service import _run_and_apply

    resp = await _run_and_apply(
        plugin_id, user_id, hook=f"on_button_{button_id}",
        trigger="button", trigger_detail=f"{plugin_id}:{button_id}",
        args={"event": "tg_button", "button": button_id})
    if not resp.get("ok"):
        await cb.message.answer(f"⚠️ Помилка плагіна: "
                                f"{str(resp.get('error'))[:200]}")
        return
    text = str((resp.get("result") or {}).get("text") or "✅ Готово.")
    await cb.message.answer(text, reply_markup=url_kb())


# ---------------------------------------------------------------- callbacks

@router.callback_query(F.data == "home")
async def cb_home(cb: CallbackQuery) -> None:
    await cb.answer()
    msg = cb.message
    if msg is None:
        return
    try:
        await msg.edit_text("👋 <b>M1 ID</b> - оберіть розділ:",
                            reply_markup=menu_kb(msg.chat.id))
    except TelegramBadRequest as exc:
        if "not modified" not in str(exc).lower():
            await msg.answer("👋 <b>M1 ID</b> - оберіть розділ:",
                             reply_markup=menu_kb(msg.chat.id))


@router.callback_query(F.data.in_(ACTIONS))
async def cb_menu_section(cb: CallbackQuery) -> None:
    await cb.answer()
    msg = cb.message
    if msg is None or cb.data not in ACTIONS:
        return
    action: str = cb.data
    db = SessionLocal()
    try:
        link = _link_by_chat(db, msg.chat.id)
        # T6: у групах — лише власник прив'язки
        allowed = _user_allowed(db, msg.chat, _fid(cb))
        accs = _accounts(db, link)
    finally:
        db.close()
    if link is None:
        await msg.answer(WELCOME_UNLINKED, reply_markup=url_kb())
        return
    if not allowed:
        await msg.answer("🔒 Дані доступні лише власнику прив'язки.")
        return
    if not accs:
        await msg.answer(NO_ACC_TEXT, reply_markup=url_kb())
        return
    if len(accs) == 1:
        await _render(msg, action, accs[0].user_seq, edit=True,
                      from_id=_fid(cb))
        return
    # меню завжди редагує ТОЙ САМИЙ пост, нові повідомлення не шлемо
    await _edit_or_send(msg, PICK_TEXT, _entry_kb(action, accs))


@router.callback_query(F.data.startswith("acc:"))
async def cb_change_account(cb: CallbackQuery) -> None:
    """«Інший акаунт» у розділі → пікер з тим самим контекстом розділу.
    Теж редагуємо існуюче повідомлення, а не шлемо нове."""
    await cb.answer()
    msg = cb.message
    if msg is None:
        return
    parts = (cb.data or "").split(":")  # acc | action [: param...]
    action = parts[1] if len(parts) > 1 else ""
    # хвіст може містити ':' (lb: scope:period) - склеюємо назад
    params = ":".join(parts[2:]) if len(parts) > 2 else ""
    if action not in ACTIONS:
        return
    db = SessionLocal()
    try:
        link = _link_by_chat(db, msg.chat.id)
        allowed = _user_allowed(db, msg.chat, _fid(cb))  # T6
        accs = _accounts(db, link)
    finally:
        db.close()
    if link is None:
        await msg.answer(WELCOME_UNLINKED, reply_markup=url_kb())
        return
    if not allowed:
        await msg.answer("🔒 Дані доступні лише власнику прив'язки.")
        return
    if not accs:
        await msg.answer(NO_ACC_TEXT, reply_markup=url_kb())
        return
    await _edit_or_send(msg, PICK_TEXT,
                        _entry_kb(action, accs, params))


def _parse_lb_ctx(param: str) -> tuple[str, str]:
    """Контекст lb у callback-даних → (scope, period). Новий формат -
    повні ключі 'group:month' (періоди тепер динамічні), старий -
    'g:mo' або 'gmo' (кнопки зі старих повідомлень)."""
    pmap = {"mo": "month", "se": "semester", "ye": "year",
            "al": "all_time"}
    pp = param.split(":")
    if len(pp) == 2:
        scope = {"g": "group", "s": "stream"}.get(pp[0], pp[0])
        return scope[:24], pmap.get(pp[1], pp[1])[:24]
    if len(param) == 3 and param[0] in ("g", "s") \
            and param[1:] in ("mo", "se", "ye"):
        return ("group" if param[0] == "g" else "stream",
                pmap[param[1:]])
    return "group", "month"


@router.callback_query(F.data.startswith("pick:"))
async def cb_pick(cb: CallbackQuery) -> None:
    await cb.answer("Завантажую…")
    parts = (cb.data or "").split(":")
    # pick | action | seq [: param...] - param може містити ':' (lb),
    # тому склеюємо хвіст назад (раніше бралась лише 1 частина і
    # контекст lb губився → після зміни акаунта скидалось на group/month)
    if len(parts) < 3 or parts[1] not in ACTIONS or not (parts[2].isascii() and parts[2].isdigit()):
        return
    action, seq = parts[1], int(parts[2])
    param = ":".join(parts[3:]) if len(parts) > 3 else None
    if cb.message is None:
        return
    variant = None
    scope = None
    period = None
    if action == "sch" and param in ("today", "week"):
        variant = param
    elif action == "lb" and param:
        scope, period = _parse_lb_ctx(param)
    await _render(cb.message, action, seq, edit=True, variant=variant,
                  scope=scope, period=period, from_id=_fid(cb))


# LOW: чіткі префікси "sch:"/"schf:" — "sch" ловив і "schf:" (крихко)
@router.callback_query(F.data.startswith(("sch:", "schf:")))
async def cb_schedule(cb: CallbackQuery) -> None:
    await cb.answer()
    data = cb.data or ""
    if data == "sch":  # меню обробляє cb_menu_section
        return
    force = data.startswith("schf:")
    parts = data.split(":")
    if len(parts) != 3 or not (parts[1].isascii() and parts[1].isdigit()) or parts[2] not in ("today", "week"):
        return
    if cb.message is not None:
        await _render(cb.message, "sch", int(parts[1]), edit=True,
                      variant=parts[2], force=force, from_id=_fid(cb))


@router.callback_query(F.data.startswith("marksr:"))
async def cb_marks_refresh(cb: CallbackQuery) -> None:
    await cb.answer()
    parts = (cb.data or "").split(":")
    if len(parts) != 2 or not (parts[1].isascii() and parts[1].isdigit()):
        return
    if cb.message is not None:
        await _render(cb.message, "marks", int(parts[1]), edit=True,
                      force=True, from_id=_fid(cb))


@router.callback_query(F.data.startswith("hwr:"))
async def cb_hw_refresh(cb: CallbackQuery) -> None:
    await cb.answer()
    parts = (cb.data or "").split(":")
    if len(parts) != 2 or not (parts[1].isascii() and parts[1].isdigit()):
        return
    if cb.message is not None:
        await _render(cb.message, "hw", int(parts[1]), edit=True,
                      force=True, from_id=_fid(cb))


@router.callback_query(F.data.startswith("lb"))
async def cb_leaderboard(cb: CallbackQuery) -> None:
    await cb.answer()
    data = cb.data or ""
    if data == "lb":  # меню обробляє cb_menu_section
        return
    force = data.startswith("lbf:")
    parts = data.split(":")
    # lb[f] | seq | scope | period - повні ключі (динамічні гілки:
    # школа month/semester/year, академія month/all_time). Кнопки зі
    # старих повідомлень (g/s + mo/se/ye) теж приймаємо.
    if len(parts) != 4 or not (parts[1].isascii() and parts[1].isdigit()):
        return
    scope = {"g": "group", "s": "stream"}.get(parts[2], parts[2])[:24]
    period = {"mo": "month", "se": "semester", "ye": "year",
              "al": "all_time"}.get(parts[3], parts[3])[:24]
    if cb.message is not None:
        await _render(cb.message, "lb", int(parts[1]), edit=True, force=force,
                      scope=scope, period=period, from_id=_fid(cb))


# ------------------------------------------------------------ вхід за QR
# Користувач кидає боту посилання з QR (https://…/qr/<токен>) або ФОТО з QR —
# бот пропонує підтвердити вхід на іншому пристрої. Підтвердження: вибір
# коду збігу з 3 кнопок (захист від фішингу) або «Відхилити».

async def _offer_qr_login(message: Message, token: str) -> None:
    from app.services import qr_login as qr

    db = SessionLocal()
    try:
        link = _link_by_chat(db, message.chat.id)
        if link is None or getattr(message.chat, "type", "private") != "private":
            await message.answer(
                "⚠️ Підтвердити вхід можна лише з прив'язаного приватного чату. "
                "Прив'яжіть бота на сайті: вкладка <b>Telegram</b>.")
            return
        row = qr.get_live(db, token)
        if row is None or row.status != "pending":
            await message.answer("⌛ Цей QR недійсний або застарів. "
                                 "Оновіть його на сторінці входу.")
            return
        opts = qr.code_options(token, row.code)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=o, callback_data=f"qra:{token}:{o}")
             for o in opts],
            [InlineKeyboardButton(text="❌ Відхилити",
                                  callback_data=f"qrd:{token}")],
        ])
        await message.answer(
            "🔐 <b>Запит на вхід у M1 ID</b>\n\n"
            f"💻 {_esc(qr.describe_ua(row.req_ua))}\n"
            f"🌐 IP: <code>{_esc(row.req_ip)}</code>\n\n"
            "Якщо це ви, оберіть <b>код, що показано на екрані</b> "
            "біля QR. Якщо не ви - відхиліть.", reply_markup=kb)
    finally:
        db.close()


@router.message(F.text.regexp(r"/qr/[0-9a-f]{32}"))
async def qr_link_handler(message: Message) -> None:
    from app.services import qr_login as qr

    token = qr.extract_token(message.text or "")
    if token:
        await _offer_qr_login(message, token)


def _decode_qr_texts(data: bytes) -> list[str]:
    import io

    import zxingcpp
    from PIL import Image

    img = Image.open(io.BytesIO(data))
    img.load()
    return [r.text for r in zxingcpp.read_barcodes(img) if r.text]


async def _qr_from_image(message: Message, file_id: str) -> None:
    from app.services import qr_login as qr

    if getattr(message.chat, "type", "private") != "private":
        return
    db = SessionLocal()
    try:
        if _link_by_chat(db, message.chat.id) is None:
            return  # чужим чатам не відповідаємо
    finally:
        db.close()
    try:
        buf = await message.bot.download(file_id)
        texts = await asyncio.to_thread(_decode_qr_texts, buf.read())
    except ImportError as exc:
        _log.error("QR-фото: не вистачає залежності: %r", exc)
        await message.answer(
            "⚠️ Розпізнавання QR на сервері не встановлено. "
            "Надішліть посилання з QR текстом.")
        return
    except Exception as exc:
        _log.warning("QR-фото: не розпізнано: %r", exc)
        await message.answer("⚠️ Не вдалося прочитати фото.")
        return
    token = next((t for t in map(qr.extract_token, texts) if t), None)
    if token is None:
        await message.answer("🤷 QR входу M1 ID на фото не знайдено. "
                             "Сфотографуйте QR зі сторінки входу ближче.")
        return
    await _offer_qr_login(message, token)


@router.message(F.photo)
async def qr_photo_handler(message: Message) -> None:
    await _qr_from_image(message, message.photo[-1].file_id)


@router.message(F.document.mime_type.startswith("image/"))
async def qr_doc_handler(message: Message) -> None:
    await _qr_from_image(message, message.document.file_id)


@router.callback_query(F.data.startswith(("qra:", "qrd:")))
async def cb_qr(cb: CallbackQuery) -> None:
    from app.services import qr_login as qr

    msg = cb.message
    if msg is None or getattr(msg.chat, "type", "private") != "private":
        await cb.answer()
        return
    parts = (cb.data or "").split(":")
    token = parts[1] if len(parts) > 1 else ""
    db = SessionLocal()
    try:
        link = _link_by_chat(db, msg.chat.id)
        if link is None or not qr.extract_token(token):
            await cb.answer("Недоступно", show_alert=True)
            return
        if parts[0] == "qrd":
            qr.deny(db, token)
            text = "❌ Вхід відхилено."
        else:
            res = qr.approve(db, token, link.user_id,
                             parts[2] if len(parts) > 2 else "", "telegram")
            text = {"ok": "✅ Вхід підтверджено. Пристрій зараз увійде.",
                    "wrong_code": "🚫 Хибний код - запит відхилено.",
                    }.get(res, "⌛ Запит застарів або вже оброблений.")
        try:
            await msg.edit_text(text)
        except TelegramBadRequest:
            pass
        await cb.answer()
    finally:
        db.close()
