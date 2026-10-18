"""Фоновий опитувальник MyStat для Telegram-сповіщень.

Як працює:
  • кожні M1ID_TELEGRAM_POLL_SECONDS (дефолт 1800 = 30 хв) рахуємо, скільки
    запитів до mapi потрібно: лише секції, увімкнені в налаштуваннях
    КОЖНОГО акаунта окремо (telegram_account_configs);
  • розмазуємо ці запити РІВНОМІРНО по вікну циклу: акаунт i стартує на
    i-му слоті (window / кількість акаунтів), усі запити одного акаунта
    йдуть поспіль, без рандому - плавне навантаження;
  • ТИХІ ГОДИНИ 23:00-05:00 (галочка в конфігі_x акаунта): у цей час ми
    ПОВНІСТЮ не смикаємо mapi для цього акаунта - ні запитів, ні записів.
    Вранці цикл порівнює дані з вечірнім станом (telegram_poll_state) і
    надсилає все, що накопичилось за ніч, однією пачкою;
  • перший прогін після прив'язки - калібрувальний, без сповіщень;
  • конфіги акаунтів розділені: увімкнено на одному - не значить на
    другому; повідомлення різних акаунтів ідуть окремими повідомленнями
    з ЛОГІНОМ акаунта в заголовку (ПІБ у всіх однакові, логін - ні);
  • окремий луп щодня о 06:00 надсилає «Розклад на сьогодні».

Типи сповіщень (кожне з кнопками «Головна» + «M1 ID»):
  📚 нова домашка · 🏅 зміна рейтингу · 📅 зміна розкладу тижня (лише
  поточний тиждень) · 📆 зміна розкладу на сьогодні · 🌅 розклад о 6:00 ·
  🧮 нові оцінки · 🏆 зміна порядку в лідерборді (лише моя позиція або
  будь-яка) · 🛍️ зміни товарів магазину.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import time
from datetime import date, datetime, time as dtime, timedelta

from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.clock import naive_kyiv_now
from app.db.base import SessionLocal
from app.db.models import (
    MystatAccount,
    TelegramAccountConfig,
    TelegramPollState,
    utcnow,
)
from app.services import app_data
from app.services import mystat_client as ms
from app.telegram import bot as tg
from app.telegram.logmask import install_masking

_log = logging.getLogger("m1id.tg")
install_masking(_log)  # H5: маскуємо токен у логах

# ---------------------------------------------------------------- дрібниці

def _monday(d: date | None = None) -> date:
    d = d or naive_kyiv_now().date()
    return d - timedelta(days=d.weekday())


def _sha(obj) -> str:
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _acc_prefix(acc: MystatAccount) -> str:
    """Логін акаунта в заголовку (ПІБ в людей однакові, логін - ні)."""
    return f"<b>{tg._esc(tg._acc_name(acc))}</b>\n"


def _is_quiet_now(cfg: TelegramAccountConfig) -> bool:
    """Тихі години 23:00-05:00. N-M9 fix: межі доби рахуємо за КИЄВОМ
    (naive_kyiv_now), а не за локальним часом сервера — на не-UTC сервері
    оцінки більше не прилетять вночі. Див. app.core.clock."""
    if not cfg.quiet_hours:
        return False
    t = naive_kyiv_now().time()
    return t >= dtime(23, 0) or t < dtime(5, 0)


def _state_rows(db, account_id: int) -> dict[str, dict]:
    rows = (db.query(TelegramPollState)
            .filter(TelegramPollState.account_id == account_id).all())
    out: dict[str, dict] = {}
    for r in rows:
        try:
            out[r.section] = json.loads(r.payload or "{}")
        except Exception:
            out[r.section] = {}
    return out


def _save_state(db, account_id: int, section: str, data: dict) -> None:
    row = (db.query(TelegramPollState)
           .filter(TelegramPollState.account_id == account_id,
                   TelegramPollState.section == section).first())
    raw = json.dumps(data, ensure_ascii=False)
    if row is None:
        db.add(TelegramPollState(account_id=account_id, section=section,
                                 payload=raw))
    else:
        row.payload = raw
        row.updated_at = utcnow()
    for _attempt in range(2):
        try:
            db.commit()
            return
        except IntegrityError:  # паралельний перший запис - той самий upsert
            db.rollback()
            row = (db.query(TelegramPollState)
                   .filter(TelegramPollState.account_id == account_id,
                           TelegramPollState.section == section).first())
            if row is None:
                db.add(TelegramPollState(account_id=account_id,
                                         section=section, payload=raw))
            else:
                row.payload = raw
                row.updated_at = utcnow()


async def _notify(chat_id: int, text: str, kb=None) -> bool:
    """→ True, якщо Telegram реально прийняв повідомлення. False означає
    «не доставлено» — викликачі НЕ оновлюють стан змін у цьому випадку,
    тож подія буде повторена наступним циклом (раніше стан зберігався ДО
    відправки: одна мережева осічка = подія втрачалась назавжди —
    саме тому «бот іноді пропускає події»)."""
    try:
        await tg.send_text(chat_id, text, kb or tg.notify_kb())
        return True
    except Exception as exc:
        _log.warning("tg send failed chat=%s: %r", chat_id, exc)
        return False


# ----------------------------------------------------------- секції циклу

def _sections_for(cfg: TelegramAccountConfig, monday: date) -> dict[str, list[str]]:
    """Конфіз акаунта → секції mapi, які треба оновити."""
    s: dict[str, list[str]] = {}
    if cfg.notify_homework or cfg.notify_deadlines:
        # домашка потрібна і для нагадувань про дедлайни (окремий тумблер)
        s["homework"] = ["homework"]
    if cfg.notify_rating:
        s["rating"] = ["balances"]
    if cfg.notify_schedule_week or cfg.notify_schedule_day:
        # один запит покриває і тиждень, і «сьогодні»
        s["schedule"] = [f"schedule_week@{monday.isoformat()}"]
    if cfg.notify_marks:
        s["marks"] = ["stat_marks_year"]
    if cfg.notify_leaderboard:
        s["leaderboard"] = ["leader_points", "leader_table"]
    if cfg.notify_shop:
        s["shop"] = ["shop_products", "shop_orders"]
    return s


# ------------------------------------------------------------- детекти змін

_LESSON_KEY = lambda l: (str(l.get("start") or ""), str(l.get("end") or ""),
                         str(l.get("subject") or ""), str(l.get("room") or ""),
                         l.get("lesson_no"))


async def _detect_homework(db, cfg: TelegramAccountConfig, acc: MystatAccount,
                           payloads: dict, prefix: str) -> None:
    view = app_data.homework_view(payloads)
    items = [i for i in view.get("items") or []
             if isinstance(i, dict) and i.get("id") is not None]
    # Вікно «побачених» id. 200 недостатньо: у mapi приходить ВЕСЬ список
    # (включно з архівом), а homework_view сортує pending ПЕРШИМИ — при
    # >200 елементів «хвіст» витісняв голову, і ті самі pending-завдання
    # оголошувались новими КОЖЕН цикл. Об'єднуємо зі старим набором, щоб
    # зникнення з поточного списку (видалення ДЗ) не «оживляло» id.
    ids = sorted({int(i["id"]) for i in items})[-2000:]
    states = _state_rows(db, acc.id)
    st = states.get("homework")
    if st is None:  # калібрувальний прогін
        _save_state(db, acc.id, "homework", {"ids": ids})
        return
    old = set(st.get("ids") or [])
    fresh = [i for i in items if int(i["id"]) not in old][:8]
    if not fresh:
        return
    n = len(fresh)
    lines = []
    for i in fresh:
        due = str(i.get("due") or "")
        due_s = f" (до {tg._fmt_dt(due)})" if due else ""
        lines.append(f"• {tg._esc(i.get('subject'))} - "
                     f"{tg._esc(i.get('title') or '-')}{due_s}")
    head = ("📚 Нове домашнє завдання" if n == 1
            else f"📚 Нових домашніх завдань: {n}")
    # кнопка «Відкрити завдання» → deep-link на модалку першого нового ДЗ
    kb = None
    try:
        kb = tg.notify_hw_kb(int(fresh[0]["id"]), acc.user_seq,
                             acc.logbook_id)
    except (TypeError, ValueError, KeyError):
        kb = None
    sent = await _notify(cfg.chat_id,
                         prefix + head + ":\n" + "\n".join(lines), kb)
    if sent:
        # стан фіксуємо ЛИШЕ після реальної доставки: осічка Telegram
        # не ховає подію — наступний цикл спробує ще раз
        _save_state(db, acc.id, "homework",
                    {"ids": sorted(set(old) | {int(i["id"]) for i in items})
                     [-2000:]})


# Пороги нагадувань про дедлайн ДЗ: за 24 год і за 3 год
_DEADLINE_THRESHOLDS_H = (24, 3)


def _deadline_left_label(remaining: timedelta) -> str:
    """timedelta → '5 год 20 хв' / '2 дн 3 год' / '40 хв'."""
    total_min = int(remaining.total_seconds() // 60)
    if total_min < 60:
        return f"{max(total_min, 1)} хв"
    hours = total_min // 60
    if hours < 48:
        minutes = total_min % 60
        return f"{hours} год" + (f" {minutes} хв" if minutes else "")
    days = hours // 24
    hrs = hours % 24
    return f"{days} дн" + (f" {hrs} год" if hrs else "")


def _parse_due(due) -> datetime | None:
    """due з homework_view → datetime (наївний локальний). None — не парситься."""
    s = str(due or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


async def _detect_deadlines(db, cfg: TelegramAccountConfig, acc: MystatAccount,
                            payloads: dict, prefix: str) -> None:
    """Нагадування про дедлайн нездалої домашки (status=3 + відома дата).

    Пороги: за 24 год і за 3 год; кожне (id, поріг) спрацьовує ОДИН раз
    (стан 'hw_deadline'). Кілька робіт у одному циклі → ОДНЕ повідомлення.
    Тихі години: не шлемо І не фіксуємо — нагадування прийде наступним
    циклом після вікна, якщо дедлайн ще не минув. Минулий дедлайн
    (remaining<=0) закриваємо мовчки — «час вийшов» не спамимо."""
    view = app_data.homework_view(payloads)
    now = naive_kyiv_now()  # дедлайни mapi — у київському часі
    states = _state_rows(db, acc.id)
    st = states.get("hw_deadline") or {}
    raw_sent = st.get("sent") or {}
    sent: dict[str, list] = {}
    if isinstance(raw_sent, dict):
        sent = {str(k): [x for x in v if isinstance(x, int)]
                for k, v in raw_sent.items() if isinstance(v, list)}

    items = [i for i in view.get("items") or []
             if isinstance(i, dict) and i.get("id") is not None
             and i.get("status") == 3 and i.get("due")]

    alive: dict[str, list] = {}
    lines: dict[str, str] = {}
    for i in items:
        due_dt = _parse_due(i.get("due"))
        if due_dt is None:
            continue
        key = str(int(i["id"]))
        remaining = due_dt - now
        done = sent.get(key, [])
        if remaining.total_seconds() <= 0:
            # минув — мовчки закриваємо всі пороги (не пам'ятаємо «протухлі»)
            alive[key] = sorted(set(done) | set(_DEADLINE_THRESHOLDS_H))
            continue
        alive[key] = done
        if _is_quiet_now(cfg):
            continue  # не шлемо і не фіксуємо — прийде після вікна
        hit = [t for t in _DEADLINE_THRESHOLDS_H
               if remaining <= timedelta(hours=t) and t not in done]
        if not hit:
            continue
        lines[key] = (
            f"⏰ <b>за {_deadline_left_label(remaining)}</b> - "
            f"{tg._esc(i.get('subject'))} - {tg._esc(i.get('title') or '-')} "
            f"(до {tg._fmt_dt(i.get('due'))})")
        alive[key] = sorted(set(done) | set(hit))

        # подія для плагінів (сліпі дані, планіфікація у bus)
        from app.plugins import events as plugin_events
        plugin_events.emit_deadlines(
            cfg.user_id, [{**i, "remaining_h":
                            round(remaining.total_seconds() / 3600, 1)}],
            getattr(acc, "user_seq", None))

    if lines:
        head = ("⏰ <b>Наближається дедлайн</b>"
                if len(lines) == 1 else
                f"⏰ <b>Дедлайни домашки: {len(lines)}</b>")
        if not await _notify(cfg.chat_id,
                             prefix + head + "\n" + "\n".join(lines.values())):
            # доставка не вдалась: знімаємо СВІЖІ помітки (prune лишається) —
            # наступний цикл спробує ще раз
            for key in lines:
                alive[key] = sent.get(key, [])
    _save_state(db, acc.id, "hw_deadline", {"sent": alive})


async def _detect_rating(db, cfg: TelegramAccountConfig, acc: MystatAccount,
                         payloads: dict, prefix: str) -> None:
    view = app_data.balances_view(payloads)
    items = view.get("items") or []
    target = next((i for i in items if i.get("key") == "achivements"), None)
    if target is None:
        return
    val = target.get("value")
    place = target.get("rating")
    states = _state_rows(db, acc.id)
    st = states.get("rating")
    if st is None or (st.get("value") == val and st.get("place") == place):
        # без змін; стан оновлюємо лише коли він відрізняється — інакше
        # кожен прохід переписував би updated_at без потреби
        if st is None:
            _save_state(db, acc.id, "rating", {"value": val, "place": place})
        return
    msg = (f"{prefix}🏅 <b>Рейтинг змінився</b>: "
           f"{st.get('value') if st.get('value') is not None else '-'} → "
           f"<b>{val if val is not None else '-'}</b>")
    if st.get("place") != place and place is not None:
        msg += f" (місце {st.get('place') or '-'} → {place})"
    if await _notify(cfg.chat_id, msg):
        _save_state(db, acc.id, "rating", {"value": val, "place": place})


async def _detect_schedule(db, cfg: TelegramAccountConfig, acc: MystatAccount,
                           payloads: dict, prefix: str,
                           section_key: str) -> bool:
    """Тиждень + «сьогодні». True - якщо сповістили про зміну тижня
    (тоді окреме сповіщення про «сьогодні» не дублюємо)."""
    if section_key not in payloads:
        return False
    view = app_data.schedule_view(payloads, section_key)
    days = [d for d in view.get("days") or [] if isinstance(d, dict)]
    monday = _monday().isoformat()

    week_key = [[_LESSON_KEY(l) for l in (d.get("lessons") or [])
                 if isinstance(l, dict)] for d in days]
    week_hash = _sha(week_key)

    states = _state_rows(db, acc.id)
    st = states.get("sched_week")
    notified_week = False
    new_week_state = {"week": monday, "hash": week_hash}
    if st is None:
        _save_state(db, acc.id, "sched_week", new_week_state)
    elif st.get("week") != monday:
        # новий тиждень: перший погляд — стан оновлюємо БЕЗ повідомлення.
        # Раніше цієї гілки не було: st["week"] назавжди лишався старим,
        # умова st.get("week") == monday більше ніколи не спрацьовувала,
        # і сповіщення про зміни тижня вмирало після першого понеділка.
        _save_state(db, acc.id, "sched_week", new_week_state)
    elif st.get("week") == monday and st.get("hash") != week_hash:
        suffix = f" - {tg._esc(tg._acc_name(acc))}" if prefix else ""
        sent = await _notify(
            cfg.chat_id,
            prefix + tg.fmt_week(days, suffix=suffix)
            .replace("📅 <b>Розклад на тиждень</b>",
                     "🔄 <b>Розклад на цей тиждень змінився!</b> "
                     "Оновлений розклад:", 1))
        if sent:
            _save_state(db, acc.id, "sched_week", new_week_state)
            notified_week = True

    # «сьогодні» - з того самого тижневого payload (зайвих запитів немає)
    today = naive_kyiv_now().date().isoformat()
    day = next((d for d in days
                if str(d.get("date") or "")[:10] == today), None)
    day_hash = _sha([_LESSON_KEY(l) for l in (day or {}).get("lessons") or []
                     if isinstance(l, dict)])
    std = states.get("sched_day")
    new_day_state = {"date": today, "hash": day_hash}
    if std is None:
        _save_state(db, acc.id, "sched_day", new_day_state)
    elif std.get("date") != today:
        # новий день: стан оновлюємо без повідомлення (перший погляд)
        _save_state(db, acc.id, "sched_day", new_day_state)
    elif std.get("hash") != day_hash:
        if notified_week:
            # зміну тижня (у т.ч. «сьогодні») вже повідомили вище —
            # не дублюємо, АЛЕ фіксуємо стан дня: інакше наступний цикл
            # надішле «Розклад на сьогодні змінився» про те саме ще раз
            _save_state(db, acc.id, "sched_day", new_day_state)
        else:
            suffix = f" - {tg._esc(tg._acc_name(acc))}" if prefix else ""
            sent = await _notify(
                cfg.chat_id,
                prefix + tg.fmt_today(day, suffix=suffix)
                .replace("📅 <b>Розклад на сьогодні</b>",
                         "🔄 <b>Розклад на сьогодні змінився!</b> "
                         "Актуальний розклад:", 1))
            if sent:
                _save_state(db, acc.id, "sched_day", new_day_state)
    return notified_week


def _mark_key(m: dict) -> list:
    return [str(m.get("date") or ""), m.get("mark"),
            str(m.get("subject") or ""), str(m.get("theme") or "")]


async def _detect_marks(db, cfg: TelegramAccountConfig, acc: MystatAccount,
                        payloads: dict, prefix: str) -> None:
    view = app_data.marks_view(payloads)
    items = [m for m in view.get("items") or [] if isinstance(m, dict)]
    top = items[:50]
    stored = [_mark_key(m) for m in top]
    states = _state_rows(db, acc.id)
    st = states.get("marks")
    if st is None:
        _save_state(db, acc.id, "marks", {"items": stored})
        return
    old = {json.dumps(x, ensure_ascii=False) for x in st.get("items") or []}
    fresh = [m for m in top
             if json.dumps(_mark_key(m), ensure_ascii=False) not in old][:10]
    if not fresh:
        return
    n = len(fresh)
    lines = []
    for m in fresh:
        theme = f" ({tg._esc(m['theme'])})" if m.get("theme") else ""
        lines.append(f"{tg._fmt_d(m.get('date'))} - <b>{m.get('mark')}</b> - "
                     f"{tg._esc(m.get('subject') or '-')}{theme}")
    head = ("🧮 Нова оцінка" if n == 1 else f"🧮 Нових оцінок: {n}")
    if await _notify(cfg.chat_id, prefix + head + ":\n" + "\n".join(lines)):
        _save_state(db, acc.id, "marks", {"items": stored})


_SCOPE_UK = {"group": "група", "stream": "потік"}
_PERIOD_UK = {"month": "місяць", "semester": "семестр", "year": "рік",
              "all_time": "за весь час"}
_SCOPE_EN = {"group": "group", "stream": "stream"}
_PERIOD_EN = {"month": "month", "semester": "semester", "year": "year",
              "all_time": "all time"}


def _lb_orders(view: dict) -> tuple[dict[str, list[str]], dict[str, object]]:
    """Порядок учасників по всіх зрізах (динамічні scope:period - гілки
    mapi різні: школа month/semester/year, академія month/all_time)
    + моя позиція з leader-points.

    Порожні зрізи НЕ записуємо: mapi іноді моргає порожньою відповіддю -
    без цієї перевірки «всі зникли» виглядає як зміна порядку і дає
    фальшиве сповіщення. Дублікати id (top ∩ other) прибираємо,
    зберігаючи перший порядок."""
    orders: dict[str, list[str]] = {}
    sections = view.get("sections") if isinstance(view.get("sections"), dict) \
        else {}
    for scope, periods in sections.items():
        if not isinstance(periods, dict):
            continue
        for period, sec in periods.items():
            if not isinstance(sec, dict):
                continue
            ids: list[str] = []
            for r in (sec.get("top") or []) + (sec.get("nearby") or []):
                if isinstance(r, dict) and r.get("id") is not None:
                    sid = str(r["id"])
                    if sid not in ids:
                        ids.append(sid)
            if ids:
                orders[f"{scope}:{period}"] = ids
    pts = view.get("points") if isinstance(view.get("points"), dict) else {}
    my_pts = {s: ((pts.get(s) or {}).get("position")
                  if isinstance(pts.get(s), dict) else None)
              for s in pts}
    return orders, my_pts


async def _detect_leaderboard(db, cfg: TelegramAccountConfig,
                              acc: MystatAccount, payloads: dict,
                              prefix: str) -> None:
    view = app_data.leaderboard_view(payloads)
    orders, my_pts = _lb_orders(view)
    # УВАГА: рядки лідерборда в id_stud-просторі (logbook_id, напр.
    # «14546»), а не id_user_storage («8220572») - це РІЗНІ id mapi.
    # Матчимо за logbook_id, fallback - id_user_storage (сумісність).
    my_id = str(acc.logbook_id or acc.id_user_storage or "")
    states = _state_rows(db, acc.id)
    st = states.get("leaderboard")
    if not orders:
        # mapi відповів порожніми зрізами (мориг/невідома гілка):
        # лишаємо попередній стан недоторканим - інакше наступний цикл
        # виглядав би «першим побаченням» і реальну зміну можна
        # пропустити. Нічого не повідомляємо.
        if st is not None:
            return
        _save_state(db, acc.id, "leaderboard",
                    {"scopes": {}, "points": my_pts, "my_id": my_id})
        return
    if st is None:
        # калібрувальний прогін: запам'ятали стан — наступні зміни повідомляємо
        _save_state(db, acc.id, "leaderboard",
                    {"scopes": orders, "points": my_pts, "my_id": my_id})
        return
    old = st.get("scopes") or {}
    old_pts = st.get("points") or {}

    # Який зріз моніторити (Telegram → вибір користувача): lb_scope+lb_period.
    # Якщо вибраний зріз раптом зник із відповіді (гілка mapi змінилась,
    # моргнула відповідь) - не мовчимо назавжди, а повертаємось до всіх.
    chosen = ""
    if (cfg.lb_scope or "").strip() and (cfg.lb_period or "").strip():
        chosen = f"{cfg.lb_scope.strip()}:{cfg.lb_period.strip()}"
    if chosen and chosen not in orders and chosen not in old:
        chosen = ""

    # «Зміна» = зріз був і раніше, і порядок у ньому відрізняється.
    # Зріз, що з'явився ВПЕРШЕ (нова гілка/перший цикл з увімкненим
    # лідербордом) - не зміна: запам'ятали й промовчали.
    changed = [k for k, v in orders.items() if k in old and old.get(k) != v]
    if not changed:
        return
    if chosen:
        if chosen not in changed:
            return  # зміни лише в зрізах, які не моніторимо
        changed = [chosen]
    if not changed:
        return

    mine_only = bool(cfg.leaderboard_mine_only)
    if mine_only:
        my_changed = False
        for k in changed:
            ids = orders.get(k) or []
            old_ids = old.get(k) if isinstance(old.get(k), list) else []
            new_pos = (ids.index(my_id) + 1) if my_id in ids else None
            old_pos = (old_ids.index(my_id) + 1) \
                if my_id in (old_ids or []) else None
            if new_pos != old_pos:
                my_changed = True
                break
        if not my_changed and old_pts != my_pts:
            # позиція могла змінитись через leader-points (поза таблицею)
            my_changed = any(my_pts.get(s) is not None
                             and old_pts.get(s) != my_pts.get(s)
                             for s in my_pts)
        if not my_changed:
            return

    # основний зріз для показу: вибраний користувачем, інакше
    # group:month, інакше перший змінений
    primary = chosen or ("group:month" if "group:month" in changed
                         else changed[0])
    scope, period = primary.split(":")
    sections = view.get("sections") if isinstance(view.get("sections"), dict) \
        else {}
    sec = (sections.get(scope) or {}).get(period) \
        if isinstance(sections.get(scope), dict) else {}
    sec = sec if isinstance(sec, dict) else {}
    rows = [r for r in (sec.get("top") or []) + (sec.get("nearby") or [])
            if isinstance(r, dict)]

    # невідома гілка mapi → англійські підписи (як домовлялись)
    en = view.get("branch") == "unknown"

    def _lbl(s: str, p: str) -> str:
        if en:
            return (f"{_SCOPE_EN.get(s, s)} - {_PERIOD_EN.get(p, p)}")
        return f"{_SCOPE_UK.get(s, s)} - {_PERIOD_UK.get(p, p)}"

    lines = [prefix + "🏆 <b>Лідерборд змінився</b>"]
    if mine_only:
        ids = orders.get(primary) or []
        old_ids = old.get(primary) if isinstance(old.get(primary), list) else []
        new_pos = (ids.index(my_id) + 1) if my_id in ids else None
        old_pos = (old_ids.index(my_id) + 1) \
            if my_id in (old_ids or []) else None
        lines.append(f"Ваша позиція: <b>{new_pos or '-'}</b>"
                     + (f" (була {old_pos})" if old_pos else ""))
    else:
        names = ", ".join(_lbl(s, p)
                          for s, p in (k.split(":") for k in changed[:3]))
        lines.append(f"Порядок учасників оновився: {names}")
    if rows:
        lines.append("")
        for i, r in enumerate(rows[:5]):
            pos = r.get("position") or (i + 1)
            lines.append(f"{pos}. {tg._esc(r.get('fio') or '-')} - "
                         f"{r.get('amount') if r.get('amount') is not None else '-'}")
    me = next((r for r in rows if str(r.get("id") or "") == my_id), None)
    if me is not None:
        lines.append(f"\n👤 Ви: <b>{me.get('position') or '-'} місце</b> - "
                     f"{me.get('amount') if me.get('amount') is not None else '-'} балів")
    if await _notify(cfg.chat_id, "\n".join(lines)):
        _save_state(db, acc.id, "leaderboard",
                    {"scopes": orders, "points": my_pts, "my_id": my_id})


async def _detect_shop(db, cfg: TelegramAccountConfig, acc: MystatAccount,
                       payloads: dict, prefix: str) -> None:
    view = app_data.shop_view(payloads)
    products = [p for p in view.get("products") or [] if isinstance(p, dict)]
    CUR_UK = {"coins": "монет", "cristals": "кристалів", "beavers": "бобрів"}

    def _price_str(p: dict) -> str:
        # товар коштує УСІ валюти одночасно — показуємо всі
        prs = p.get("prices") if isinstance(p.get("prices"), list) else []
        if not prs:
            return str(p.get("price") or "")
        return " + ".join(
            f"{x.get('price')} {CUR_UK.get(x.get('currency'), x.get('currency'))}"
            for x in prs if isinstance(x, dict))

    fp = {str(p.get("id")): [str(p.get("title") or ""),
                             _price_str(p),
                             str(p.get("quantity"))]
          for p in products if p.get("id") is not None}
    states = _state_rows(db, acc.id)
    st = states.get("shop")
    if st is None:
        _save_state(db, acc.id, "shop", {"products": fp})
        return
    old = st.get("products") or {}
    added = [k for k in fp if k not in old]
    removed = [k for k in old if k not in fp]
    changed = [k for k in fp if k in old and fp[k] != old[k]]
    if not (added or removed or changed):
        return
    lines = [prefix + "🛍️ <b>Магазин оновився</b>"]
    for k in added[:4]:
        lines.append(f"➕ {tg._esc(fp[k][0])} ({fp[k][1]})")
    for k in changed[:4]:
        lines.append(f"✏️ {tg._esc(fp[k][0])}: {old[k][1]} → {fp[k][1]}")
    for k in removed[:3]:
        lines.append(f"➖ {tg._esc(old[k][0])}")
    extra = (len(added) - 4 if len(added) > 4 else 0) \
        + (len(changed) - 4 if len(changed) > 4 else 0)
    if extra > 0:
        lines.append(f"… і ще {extra} змін - дивіться на сайті")
    if await _notify(cfg.chat_id, "\n".join(lines)):
        _save_state(db, acc.id, "shop", {"products": fp})


# --------------------------------------------------------------- цикл

def _arrived_sections(cfg: TelegramAccountConfig, payloads: dict,
                      monday_iso: str) -> dict[str, list[str]]:
    """Які детекти можна ганяти по ЩОЙНО ПРИБУЛИХ payload'ах: перетин
    увімкнених у конфізі секцій з тими, що реально прийшли. Викликається
    і з циклу (після force-оновлення), і з on_fresh_data (сайт/сокет
    щойно витягнули дані — бот реагує без власних запитів до mapi)."""
    wanted = _sections_for(cfg, date.fromisoformat(monday_iso))
    arrived: dict[str, list[str]] = {}
    for name, secs in wanted.items():
        if any(payloads.get(s) is not None for s in secs):
            arrived[name] = secs
    return arrived


async def _run_detections(db, cfg: TelegramAccountConfig, acc: MystatAccount,
                          secs: dict[str, list[str]], prefix: str,
                          payloads: dict, monday_iso: str) -> None:
    """Прогін детектів по готових payload'ах. КОЖЕН детект у власному
    try/except: помилка одного (крива відповідь mapi тощо) більше не
    вбиває решту — раніше впав homework → мовчки пропускались marks/
    leaderboard/shop у тому ж циклі (звідси «бот іноді пропускає»)."""
    if "homework" in secs and payloads.get("homework") is not None:
        try:
            await _detect_homework(db, cfg, acc, payloads, prefix)
        except Exception as exc:
            _log.warning("tg detect homework acc=%s failed: %r",
                         acc.id, exc)
        try:
            await _detect_deadlines(db, cfg, acc, payloads, prefix)
        except Exception as exc:
            _log.warning("tg detect deadlines acc=%s failed: %r",
                         acc.id, exc)
    if "rating" in secs and payloads.get("balances") is not None:
        try:
            await _detect_rating(db, cfg, acc, payloads, prefix)
        except Exception as exc:
            _log.warning("tg detect rating acc=%s failed: %r", acc.id, exc)
    if "schedule" in secs:
        key = f"schedule_week@{monday_iso}"
        if payloads.get(key) is not None:
            try:
                await _detect_schedule(db, cfg, acc, payloads, prefix, key)
            except Exception as exc:
                _log.warning("tg detect schedule acc=%s failed: %r",
                             acc.id, exc)
    if "marks" in secs and (payloads.get("stat_marks_year") is not None
                            or payloads.get("stat_marks") is not None):
        try:
            await _detect_marks(db, cfg, acc, payloads, prefix)
        except Exception as exc:
            _log.warning("tg detect marks acc=%s failed: %r", acc.id, exc)
    if "leaderboard" in secs and (payloads.get("leader_table") is not None
                                  or payloads.get("leader_points") is not None):
        try:
            await _detect_leaderboard(db, cfg, acc, payloads, prefix)
        except Exception as exc:
            _log.warning("tg detect leaderboard acc=%s failed: %r",
                         acc.id, exc)
    if "shop" in secs and payloads.get("shop_products") is not None:
        try:
            await _detect_shop(db, cfg, acc, payloads, prefix)
        except Exception as exc:
            _log.warning("tg detect shop acc=%s failed: %r", acc.id, exc)


# локи детектів: по одному на (event loop, акаунт). asyncio.Lock
# прив'язана до loop'а — globальний лок із чужого loop'у падає з
# RuntimeError «bound to a different event loop» (та сама історія, що
# з refresh-локом у mystat_client). Серієзніть: два одночасні проходи
# детектів одного акаунта (сокет + сайт + цикл) без лока = подвійні
# сповіщення про одну зміну.
_det_locks: dict[tuple[int, int], asyncio.Lock] = {}
_det_locks_guard = threading.Lock()


def _detection_lock(account_id: int) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    key = (id(loop), account_id)
    with _det_locks_guard:
        lock = _det_locks.get(key)
        if lock is None:
            if len(_det_locks) > 512:  # страховка від росту
                # витісняємо ЛИШЕ вільні локи: clear() міг викинути лок,
                # який прямо зараз тримає/чекає інша корутина — тоді дві
                # паралельні проходки = саме ті подвійні сповіщення, від
                # яких лок існує
                for k in [k for k, v in _det_locks.items() if not v.locked()]:
                    _det_locks.pop(k, None)
            lock = _det_locks[key] = asyncio.Lock()
        return lock


async def _process_account(cfg: TelegramAccountConfig | None,
                           acc: MystatAccount,
                           secs: dict[str, list[str]], prefix: str,
                           plugin_secs: list[str] | tuple = (),
                           pacer: "object | None" = None) -> None:
    """ОДИН набір запитів (ТГ ∪ плагіни) → детекти ТГ + події плагінів."""
    monday_iso = _monday().isoformat()
    async with _detection_lock(acc.id):
        db = SessionLocal()
        payloads: dict = {}
        try:
            uniq = sorted({sec for lst in secs.values() for sec in lst}
                          | set(plugin_secs))
            if not uniq:
                return
            payloads = await app_data.get_payloads(db, acc, uniq, force=True,
                                                   pacer=pacer)
            if cfg is not None and secs:
                await _run_detections(db, cfg, acc, secs, prefix, payloads,
                                      monday_iso)
        finally:
            db.close()
    # події плагінів — за межами lock і сесії (cooldown 60с у dispatch
    # захищає від дублів із сайту/сокета)
    if plugin_secs:
        arrived = [s for s in plugin_secs if payloads.get(s) is not None]
        if arrived:
            from app.plugins import events as plugin_events
            plugin_events.emit_account_event(
                acc.id, acc.user_id, arrived, payloads,
                getattr(acc, "user_seq", None))


async def on_fresh_data(account_id: int, payloads: dict) -> None:
    """Сайт/сокет/хтось ще щойно витягнув свіжі дані з mapi (хук
    app_data.on_fresh_data). Бот одразу проганяє детекти по ЦИХ даних —
    без власних запитів до mapi. Так сайт і бот живуть разом: побачив
    нове на сайті → секунду по тому бот теж це «побачив» і повідомив.

    Тихі години: НЕ чіпаємо стан (як і цикл) — зміна залишиться в
    стані вечірнім і вранці прийде пачкою. Помилка / нема конфіга —
    мовчки виходимо (сайт від цього не залежить)."""
    db = SessionLocal()
    try:
        acc = db.get(MystatAccount, account_id)
        if acc is None or acc.status == "disabled":
            return
        # Плагіни: свіжі секції від сайту/сокета годують і плагіни —
        # незалежно від наявності TG-конфіга (cooldown 60с у dispatch
        # захищає від дублів; власних запитів до mapi тут немає).
        from app.plugins import poller as plugin_poller
        p_secs = plugin_poller.sections_by_account().get(account_id) or []
        if p_secs:
            arrived = [s for s in p_secs if payloads.get(s) is not None]
            if arrived:
                from app.plugins import events as plugin_events
                plugin_events.emit_account_event(
                    account_id, acc.user_id, arrived, payloads,
                    getattr(acc, "user_seq", None))
        cfg = (db.query(TelegramAccountConfig)
               .filter(TelegramAccountConfig.account_id == account_id)
               .first())
        if cfg is None or not cfg.chat_id:
            return  # TG не підключений — робота тільки для снапшотів сайту
        if _is_quiet_now(cfg):
            return
        monday_iso = _monday().isoformat()
        secs = _arrived_sections(cfg, payloads, monday_iso)
        if not secs:
            return
        n_accs = (db.query(MystatAccount)
                  .filter(MystatAccount.user_id == acc.user_id,
                          MystatAccount.status != "disabled").count())
        prefix = _acc_prefix(acc) if n_accs > 1 else ""
        async with _detection_lock(acc.id):
            await _run_detections(db, cfg, acc, secs, prefix, payloads,
                                  monday_iso)
    finally:
        db.close()


# секції «просто свіжих даних» для fast-path від сокета, коли TG-конфіга
# немає (снапшоти сайту оновлюються, сповіщень немає)
def _socket_sections(monday) -> dict[str, list[str]]:
    return {
        "payloads": [
            "homework", "stat_marks_year", "stat_marks", "balances",
            f"schedule_week@{monday.isoformat()}",
            "leader_points", "leader_table", "shop_products",
        ]
    }


async def refresh_account_now(account_id: int) -> None:
    """Миттєвий точковий цикл для акаунта (fast-path від notify-сокета).
    Є TG-конфіг → повний прохід детектів (сповіщення «як із циклу»);
    немає конфіга → лише оновлення снапшотів для сайту. Тихі години
    перевіряє викликач (notify_socket._on_event)."""
    db = SessionLocal()
    try:
        acc = db.get(MystatAccount, account_id)
        if acc is None or acc.status == "disabled":
            return
        cfg = (db.query(TelegramAccountConfig)
               .filter(TelegramAccountConfig.account_id == account_id)
               .first())
        monday = _monday()
        from app.plugins import poller as plugin_poller
        p_secs = plugin_poller.sections_by_account().get(account_id) or []
        if cfg is not None and cfg.chat_id:
            secs = _sections_for(cfg, monday)
            if not secs and not p_secs:
                return
            n_accs = (db.query(MystatAccount)
                      .filter(MystatAccount.user_id == acc.user_id,
                              MystatAccount.status != "disabled").count())
            await _process_account(cfg, acc, secs,
                                   _acc_prefix(acc) if n_accs > 1 else "",
                                   plugin_secs=p_secs)
        elif p_secs:
            # немає ТГ-конфіга, але є плагіни — той самий прохід без детектів
            await _process_account(None, acc, {}, "", plugin_secs=p_secs)
        else:
            await _process_payloads_only(acc, _socket_sections(monday))
    finally:
        db.close()


async def _process_payloads_only(acc: MystatAccount,
                                 secs: dict[str, list[str]]) -> None:
    """Тільки оновити снапшоти (без сповіщень)."""
    db = SessionLocal()
    try:
        uniq = sorted({sec for lst in secs.values() for sec in lst})
        await app_data.get_payloads(db, acc, uniq, force=True)
    finally:
        db.close()


def _acc_prefix_for(db, acc: MystatAccount) -> str:
    """Префікс логіном, якщо в користувача кілька акаунтів."""
    n_accs = (db.query(MystatAccount)
              .filter(MystatAccount.user_id == acc.user_id,
                      MystatAccount.status != "disabled")
              .count())
    return _acc_prefix(acc) if n_accs > 1 else ""


def _units_for_cycle(db) -> list[tuple]:
    """Юніти циклу: TG-конфіги + плагіни з ОБ'ЄДНАНИМИ секціями.
    → [(cfg | None, acc, tg_secs, prefix, plugin_secs)].

    Акаунт тягнеться ОДИН раз: отримані payload'и живлять і детекти ТГ,
    і події плагінів (раніше плагін-полер мав власний цикл з дубльованими
    запитами). Тихі години (конфіг ТГ): акаунт ПРОПУСКАЄТЬСЯ ПОВНІСТЮ -
    уночі ми не смикаємо mapi взагалі (ні запитів, ні станів)."""
    from app.plugins import poller as plugin_poller

    monday = _monday()
    plugin_secs = plugin_poller.sections_by_account()
    units: list[tuple[TelegramAccountConfig | None, MystatAccount,
                      dict[str, list[str]], str, list[str]]] = []
    quiet_skipped = 0
    seen_accs: set[int] = set()

    # 1) акаунти з TG-конфігами (секції ТГ ∪ секції плагінів)
    for cfg in db.query(TelegramAccountConfig).all():
        acc = db.get(MystatAccount, cfg.account_id)
        if acc is None or acc.status == "disabled":
            continue
        seen_accs.add(acc.id)
        secs = _sections_for(cfg, monday)
        p_secs = plugin_secs.get(acc.id) or []
        if not secs and not p_secs:
            continue
        if _is_quiet_now(cfg):
            quiet_skipped += 1
            continue
        units.append((cfg, acc, secs, _acc_prefix_for(db, acc), p_secs))

    # 2) плагін-акаунти БЕЗ TG-конфіга: без ТГ і без тихих годин, але
    #    теж у спільному циклі (раніше жив у власному 120с циклі)
    for acc_id, p_secs in plugin_secs.items():
        if acc_id in seen_accs:
            continue
        acc = db.get(MystatAccount, acc_id)
        if acc is None or acc.status == "disabled":
            continue
        units.append((None, acc, {}, "", p_secs))

    if quiet_skipped:
        _log.info("tg cycle: тихі години - %d акаунтів пропущено "
                  "(mapi не смикаємо)", quiet_skipped)
    return units


async def _run_cycle() -> None:
    db = SessionLocal()
    try:
        units = _units_for_cycle(db)
    finally:
        db.close()
    if not units:
        return

    total_requests = sum(
        len({s for lst in u[2].values() for s in lst} | set(u[4]))
        for u in units)
    window = max(60, int(get_settings().telegram_poll_seconds))
    # Два режими розмазування (env M1ID_POLL_PACE):
    #   account — вікно ділиться на акаунти, запити юзера всередині слота
    #             летять пачкою (стара поведінка, добре для кількох юзерів);
    #   request — вікно ділиться на ЗАПИТИ: pacer роздає кожному mapi-виклику
    #             власний момент (window/total_requests) — рівний потік без
    #             пачок незалежно від кількості акаунтів. Деталі: services/mapi_pacer.py
    pace_mode = (get_settings().poll_pace or "account").strip().lower()
    pacer = None
    slot = window / len(units)
    if pace_mode == "request" and total_requests > 0:
        from app.services.mapi_pacer import RequestPacer
        pacer = RequestPacer(window / total_requests)
        _log.info("tg cycle: %d акаунтів, %d mapi-запитів, режим «по запитах»: "
                  "1 запит / %.1fс (вікно %dс)",
                  len(units), total_requests, pacer.interval, window)
    else:
        _log.info("tg cycle: %d акаунтів, %d mapi-запитів, слот %.0fс",
                  len(units), total_requests, slot)
    for i, (cfg, acc, secs, prefix, p_secs) in enumerate(units):
        t0 = time.monotonic()
        try:
            await _process_account(cfg, acc, secs, prefix, plugin_secs=p_secs,
                                   pacer=pacer)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log.warning("tg poll account=%s failed: %r", acc.id, exc)
        if pacer is None and i < len(units) - 1:
            # account-режим: пауза між акаунтами; request-режим сам pacує
            # кожен запит — паузи по акаунтах не потрібні
            await asyncio.sleep(max(0.0, slot - (time.monotonic() - t0)))


async def run_poller() -> None:
    """Головний луп: цикл кожні TELEGRAM_POLL_SECONDS, запити розмазані."""
    window = max(60, int(get_settings().telegram_poll_seconds))
    _log.info("tg poller: цикл оновлення даних - %dс", window)
    while True:
        t0 = time.monotonic()
        try:
            await _run_cycle()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log.warning("tg poll cycle failed: %r", exc)
        elapsed = time.monotonic() - t0
        await asyncio.sleep(max(5.0, window - elapsed))


# ---------------------------------------------------------- розклад о 6:00

def _seconds_until_6am() -> float:
    """Секунди до 06:00 за КИЄВОМ (розклад на сьогодні)."""
    now = naive_kyiv_now()
    target = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return max(1.0, (target - now).total_seconds())


async def _daily_run() -> None:
    db = SessionLocal()
    try:
        configs = (db.query(TelegramAccountConfig)
                   .filter(TelegramAccountConfig.notify_schedule_daily
                           .is_(True))
                   .all())
        units = []
        for cfg in configs:
            if _is_quiet_now(cfg):  # 06:00 поза вікном, але всяк випадок
                continue
            acc = db.get(MystatAccount, cfg.account_id)
            if acc is None or acc.status == "disabled":
                continue
            n_accs = (db.query(MystatAccount)
                      .filter(MystatAccount.user_id == acc.user_id,
                              MystatAccount.status != "disabled")
                      .count())
            units.append((cfg, acc, _acc_prefix(acc) if n_accs > 1 else ""))
    finally:
        db.close()
    if not units:
        return
    monday = _monday().isoformat()
    key = f"schedule_week@{monday}"
    for cfg, acc, prefix in units:
        db = SessionLocal()
        try:
            payloads = await app_data.get_payloads(db, acc, [key], force=True)
            view = app_data.schedule_view(payloads, key)
            days = [d for d in view.get("days") or [] if isinstance(d, dict)]
            today = naive_kyiv_now().date().isoformat()
            day = next((d for d in days
                        if str(d.get("date") or "")[:10] == today), None)
            # суфікс «- логін» у стилі повідомлень про зміни: prefix
            # (жирний + \n) клеївся впритул до заголовка ранкових
            # («…на сьогодні<b>login</b>») - тепер інлайн, як всюди
            suffix = f" - {tg._esc(tg._acc_name(acc))}" if prefix else ""
            text = tg.fmt_today(
                day, suffix=suffix, header="🌅 <b>Розклад на сьогодні</b>")
            await _notify(cfg.chat_id, text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log.warning("tg daily account=%s failed: %r", acc.id, exc)
        finally:
            db.close()
        await asyncio.sleep(0.4)


async def run_daily() -> None:
    """Щодня о 06:00 (час сервера) - «Розклад на сьогодні»."""
    while True:
        await asyncio.sleep(_seconds_until_6am())
        try:
            await _daily_run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log.warning("tg daily run failed: %r", exc)
        # on_daily плагінів — той самий ранковий прохід (власний цикл
        # плагін-полера прибрано, живлення даних — у tg циклі)
        try:
            from app.plugins.poller import _daily_pass as plugin_daily
            await plugin_daily()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _log.warning("plugin daily pass failed: %r", exc)
        await asyncio.sleep(61)  # не стріляємо двічі на межі доби
