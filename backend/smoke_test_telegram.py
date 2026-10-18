"""Telegram smoke-test: прив'язка (підпис deep-link), API статус/налаштування/
відв'язка, детекти змін poller'а (домашка/оцінки/лідерборд/розклад/магазин),
тихі години (mapi не смикаємо вночі), розділені конфіги по акаунтах -
БЕЗ реального Telegram (бот у тесті не стартує).

Payload-и детектів - у ТІЙ САМІЙ формі, що й живі відповіді mapi
(data/id_stud/prices), бо детекти працюють поверх app_data view-ів.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
import uuid

_tmp = tempfile.mkdtemp(prefix="m1id_tg_")
os.environ["M1ID_DB_URL"] = f"sqlite:///{_tmp}/test.db".replace("\\", "/")
os.environ["M1ID_SECRET_KEY"] = "test-secret-key-tg-0123456789abcdef-0123456789"
os.environ["M1ID_EMAIL_MX_CHECK"] = "false"
os.environ["M1ID_TELEGRAM_BOT_TOKEN"] = ""  # реальний бот у тесті не стартує
os.environ["M1ID_DEBUG"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.db.base import SessionLocal  # noqa: E402
from app.db.models import (  # noqa: E402
    MystatAccount,
    TelegramAccountConfig,
    TelegramLink,
    User,
)
from app.telegram import bot as tg_bot  # noqa: E402
from app.telegram import poller as pl  # noqa: E402
from app.telegram.linking import make_start_payload, parse_start_payload  # noqa: E402

from app.main import app  # noqa: E402

passed = failed = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" - {extra}" if extra and not cond else ""))


UNIQ = f"{int(time.time())}{uuid.uuid4().hex[:6]}"
USERNAME = f"tguser_{UNIQ}"
EMAIL = f"{UNIQ}@gmail.com"
PASSWORD = "SuperSecret1!"

# ── фіктивна доставка: усе, що «летить у Telegram», збираємо в sent ──
sent: list[str] = []
sent_kb: list[object] = []


async def _fake_notify(chat_id: int, text: str, kb=None) -> bool:
    """Заглушка віддає True (успішна доставка) — реальний контракт
    poller._notify: стан змін фіксується ЛИШЕ після доставки, тому
    заглушка МАЖЕ сигналізувати успіх, інакше події «повторювались» б."""
    sent.append(text)
    sent_kb.append(kb)
    return True


pl._notify = _fake_notify

with TestClient(app) as c:
    # ---------- deep-link payload ----------
    p = make_start_payload(123)
    check("start-payload roundtrip", parse_start_payload(p) == 123)
    check("підроблений payload відкидається",
          parse_start_payload("123-0000000000") is None)
    check("сміття відкидається", parse_start_payload("abc") is None
          and parse_start_payload("") is None
          and parse_start_payload("x-1-2") is None)

    # ---------- API до прив'язки ----------
    r = c.post("/api/auth/register", json={
        "username": USERNAME, "password": PASSWORD, "email": EMAIL})
    check("register → ok", r.status_code == 200 and r.json()["ok"] is True)
    access = r.json()["data"]["access_token"]
    H = {"Authorization": f"Bearer {access}"}

    r = c.get("/api/telegram/status", headers=H)
    j = r.json()
    check("status → ok конверт", r.status_code == 200 and j["ok"] is True)
    d = j["data"]
    check("не прив'язано, акаунтів без прив'язки теж немає в списку",
          d["linked"] is False and d["accounts"] == [])
    check("бот не налаштований у тесті (токен порожній)",
          d["bot_configured"] is False and d["deep_link"] is None)

    r = c.post("/api/telegram/settings", headers=H,
               json={"account_seq": 1, "marks_new": False})
    check("settings без прив'язки → 404 telegram_not_linked",
          r.status_code == 404
          and r.json()["error"][0]["code"] == "telegram_not_linked")

    # ---------- прив'язка в БД (те саме, що робить /start у боті) ----------
    db = SessionLocal()
    user = db.query(User).filter(User.username == USERNAME).first()
    acc1 = MystatAccount(user_id=user.id, user_seq=1, label="Тестовий",
                         status="active", id_user_storage="u2",
                         mystat_login="login_one")
    acc2 = MystatAccount(user_id=user.id, user_seq=2, label="Другий",
                         status="active", id_user_storage="u9",
                         mystat_login="login_two")
    db.add(acc1)
    db.flush()
    db.add(acc2)
    link = TelegramLink(user_id=user.id, chat_id=777000111,
                        bot_username="M1_IDBOT")
    db.add(link)
    db.commit()
    acc1_id, acc2_id, link_id = acc1.id, acc2.id, link.id
    db.close()

    r = c.get("/api/telegram/status", headers=H)
    d = r.json()["data"]
    check("status → linked, обидва акаунти в списку",
          d["linked"] is True and len(d["accounts"]) == 2)
    a1 = d["accounts"][0]
    check("акаунт у статусі підписаний ЛОГІНОМ",
          a1["login"] == "login_one" and a1["account_seq"] == 1)
    check("конфігів ще немає - settings null в обох",
          a1["settings"] is None and d["accounts"][1]["settings"] is None)

    # ---------- конфіг акаунта 1: розділені конфіги! ----------
    r = c.post("/api/telegram/settings", headers=H,
               json={"account_seq": 1, "marks_new": False,
                     "shop_change": True})
    check("settings акаунта 1 зберігаються",
          r.status_code == 200 and r.json()["data"]["marks_new"] is False
          and r.json()["data"]["shop_change"] is True)

    r = c.post("/api/telegram/settings", headers=H,
               json={"account_seq": 2, "marks_new": True})
    check("settings акаунта 2 - окремий конфіг",
          r.status_code == 200 and r.json()["data"]["marks_new"] is True)

    r = c.get("/api/telegram/status", headers=H)
    accs = r.json()["data"]["accounts"]
    s1, s2 = accs[0]["settings"], accs[1]["settings"]
    check("конфіги РОЗДІЛЕНІ: marks_new False на 1-му і True на 2-му",
          s1["marks_new"] is False and s2["marks_new"] is True)
    check("ввімкнено на одному - не ввімкнено на іншому (shop)",
          s1["shop_change"] is True and s2["shop_change"] is False)

    r = c.post("/api/telegram/test", headers=H, json={"account_seq": 1})
    check("test без запущеного бота → 503",
          r.status_code == 503
          and r.json()["error"][0]["code"] == "telegram_bot_not_running")

    # ---------- логін як ім'я акаунта ----------
    db = SessionLocal()
    acc = db.get(MystatAccount, acc1_id)
    check("бот підписує акаунт логіном, а не ПІБ",
          tg_bot._acc_name(acc) == "login_one")

    # ---------- «Ви» в лідерборді: матч за id, fallback за ПІБ ----------
    acc.fio = "Мендєлєєв Іван Олексійович"
    db.commit()
    rows_me = [
        {"id": "x1", "fio": "Яцун Іван", "position": 1, "amount": 174},
        {"id": "x2", "fio": "Мендєлєєв Іван Олексійович", "position": 13,
         "amount": 65},
    ]
    acc.id_user_storage = "x2"
    me = tg_bot._find_me(rows_me, acc)
    check("лідерборд: свій рядок за id (13 місце, 65 балів)",
          me is not None and me["position"] == 13 and me["amount"] == 65)
    acc.id_user_storage = "other_id"  # id не збігається
    me = tg_bot._find_me(rows_me, acc)
    check("лідерборд: fallback за ПІБ (єдиний збіг)",
          me is not None and me["amount"] == 65)
    acc.fio = "Такий Самий"
    rows_dup = [
        {"id": "a", "fio": "Такий Самий", "position": 1, "amount": 9},
        {"id": "b", "fio": "Такий Самий", "position": 2, "amount": 8},
    ]
    check("лідерборд: двозначний ПІБ (тезки) → не вгадуємо",
          tg_bot._find_me(rows_dup, acc) is None)

    # ---------- детект: домашка ----------
    lk = db.get(TelegramLink, link_id)
    cfg1 = (db.query(TelegramAccountConfig)
            .filter(TelegramAccountConfig.account_id == acc.id).first())
    if cfg1 is None:  # на випадок запуску тесту без API-кроку вище
        cfg1 = TelegramAccountConfig(account_id=acc.id, user_id=user.id,
                                     chat_id=777000111)
        db.add(cfg1)
        db.commit()
    sent.clear()
    hw = {"homework": [{"status": 3, "data": [
        {"id": 1, "name_spec": "Математика", "theme": "Інтеграли",
         "overdue_time": "2026-09-03T23:55"}]}]}
    asyncio.run(pl._detect_homework(db, cfg1, acc, hw, ""))
    check("домашка: перший прогін - калібровка, без сповіщення", sent == [])
    hw["homework"][0]["data"].append(
        {"id": 2, "name_spec": "Фізика", "theme": "Оптика",
         "overdue_time": "2026-09-05T23:55"})
    asyncio.run(pl._detect_homework(db, cfg1, acc, hw, ""))
    check("домашка: нове ДЗ виявлено", len(sent) == 1
          and "Фізика" in sent[0] and "Оптика" in sent[0])
    # deep-link кнопка «Відкрити завдання» → /app?account=N&hw=ID
    kb = sent_kb[-1]
    kb_url = None
    try:
        for row in kb.inline_keyboard:
            for btn in row:
                if btn.url and "hw=" in btn.url:
                    kb_url = btn.url
    except Exception:
        pass
    check("домашка: кнопка «Відкрити завдання» з deep-link",
          kb_url is not None and kb_url.endswith("/app?account=1&hw=2")
          and "Відкрити завдання" in repr(kb))
    sent.clear()
    asyncio.run(pl._detect_homework(db, cfg1, acc, hw, ""))
    check("домашка: повторний прогін без змін - тихо", sent == [])

    # ---------- детект: оцінки ----------
    sent.clear()
    mk = {"stat_marks_year": [
        {"mark_date": "2026-08-30", "mark": 11, "name_spec": "Алгоритми",
         "theme": "Сортування"}]}
    asyncio.run(pl._detect_marks(db, cfg1, acc, mk, ""))
    check("оцінки: калібровка без сповіщення", sent == [])
    mk["stat_marks_year"].insert(0, {"mark_date": "2026-08-31", "mark": 12,
                                     "name_spec": "Алгоритми",
                                     "theme": "Дерева"})
    asyncio.run(pl._detect_marks(db, cfg1, acc, mk, ""))
    check("оцінки: нова оцінка виявлена", len(sent) == 1
          and "Нова оцінка" in sent[0] and "Дерева" in sent[0])

    # ---------- детект: лідерборд (самe ПОРЯДОК учасників) ----------
    def lb_payload(order: list[str]) -> dict:
        rows = [{"id_stud": uid, "fio_stud": f"Студент {uid}",
                 "position": i + 1, "amount": 100 - i}
                for i, uid in enumerate(order)]
        return {"leader_table": {"group": {
                    "month": {"top": rows, "other": [], "new_students": []},
                    "semester": {}, "year": {}},
                    "stream": {"month": {}, "semester": {}, "year": {}}},
                "leader_points": {"group": {
                    "studentPosition": order.index("u2") + 1,
                    "totalCount": 90},
                    "stream": {"studentPosition": None, "totalCount": None}}}

    sent.clear()
    asyncio.run(pl._detect_leaderboard(db, cfg1, acc, lb_payload(
        ["u1", "u2", "u3", "u4"]), ""))
    check("лідерборд: калібровка без сповіщення", sent == [])

    cfg1.leaderboard_mine_only = True
    sent.clear()
    asyncio.run(pl._detect_leaderboard(db, cfg1, acc, lb_payload(
        ["u2", "u1", "u3", "u4"]), ""))
    check("лідерборд: моя позиція змінилась → сповіщення",
          len(sent) == 1 and "Ваша позиція" in sent[0], str(sent))

    sent.clear()
    asyncio.run(pl._detect_leaderboard(db, cfg1, acc, lb_payload(
        ["u2", "u3", "u1", "u4"]), ""))
    check("лідерборд: мій порядок не змінився → тихо (mine_only)",
          sent == [], str(sent))

    cfg1.leaderboard_mine_only = False
    sent.clear()
    asyncio.run(pl._detect_leaderboard(db, cfg1, acc, lb_payload(
        ["u2", "u3", "u4", "u1"]), ""))
    check("лідерборд: будь-яка зміна порядку → сповіщення (усі зміни)",
          len(sent) == 1 and "Порядок учасників" in sent[0], str(sent))

    # ---------- лідерборд: гілки (академія / школа / невідома) ----------
    from app.services import app_data as ad  # noqa: E402

    def acad_payload() -> dict:
        top = [{"id_stud": "u1", "fio_stud": "Яцун І.", "position": 1,
                "amount": 174}]
        return {"leader_table": {
                    "group": {"month": {"top": top, "other": [],
                                        "new_students": []},
                              "all_time": {"top": [], "other": [],
                                           "new_students": []}},
                    "stream": {"month": {"top": [], "other": [],
                                         "new_students": []},
                               "all_time": {"top": [], "other": [],
                                            "new_students": []}}},
                "leader_points": {"group": {"studentPosition": 5,
                                            "totalCount": 40},
                                  "stream": {"studentPosition": None,
                                             "totalCount": None}}}

    va = ad.leaderboard_view(acad_payload())
    check("лідерборд: академічна гілка - branch=academy",
          va["branch"] == "academy", str(va.get("branch")))
    check("лідерборд: академія - періоди month+all_time динамічно, укр",
          [p["key"] for p in va["scopes"][0]["periods"]]
          == ["month", "all_time"]
          and va["scopes"][0]["periods"][1]["label"] == "За весь час"
          and va["scopes"][0]["label"] == "Група",
          str(va["scopes"])[:220])
    check("лідерборд: академія - all_time у sections",
          "all_time" in va["sections"]["group"], str(va["sections"].keys()))

    vs = ad.leaderboard_view({"leader_table": {"group": {
        "month": {"top": [], "other": [], "new_students": []},
        "semester": {"top": [], "other": [], "new_students": []},
        "year": {"top": [], "other": [], "new_students": []}}}})
    check("лідерборд: шкільна гілка - month/semester/year, укр",
          vs["branch"] == "school"
          and [p["key"] for p in vs["scopes"][0]["periods"]]
          == ["month", "semester", "year"]
          and vs["scopes"][0]["periods"][2]["label"] == "Рік",
          str(vs["scopes"])[:220])

    vu = ad.leaderboard_view({"leader_table": {"clan": {
        "week": {"top": [], "other": [], "new_students": []}}}})
    check("лідерборд: невідома гілка - англійські підписи",
          vu["branch"] == "unknown"
          and vu["scopes"][0]["label"] == "Clan"
          and vu["scopes"][0]["periods"][0]["label"] == "Week",
          str(vu["scopes"])[:220])

    # порожні вузли ({}) не стають кнопками: у lb_payload вище
    # semester/year = {} → лишиться лише month
    v1 = ad.leaderboard_view(lb_payload(["u1", "u2"]))
    check("лідерборд: порожні періоди приховані (немає кнопок-пустушок)",
          [p["key"] for p in v1["scopes"][0]["periods"]] == ["month"]
          and list(v1["sections"].keys()) == ["group"],
          str(v1["scopes"])[:220])

    check("лідерборд: _parse_lb_ctx розуміє новий і легаси-формати",
          tg_bot._parse_lb_ctx("stream:all_time") == ("stream", "all_time")
          and tg_bot._parse_lb_ctx("group:month") == ("group", "month")
          and tg_bot._parse_lb_ctx("g:mo") == ("group", "month")
          and tg_bot._parse_lb_ctx("sye") == ("stream", "year"),
          "")

    # ---------- детект: розклад тиждень + сьогодні ----------
    today = time.strftime("%Y-%m-%d")
    monday = pl._monday().isoformat()
    key = f"schedule_week@{monday}"

    def lesson(no: int, subj: str, room: str = "12") -> dict:
        # СИРА форма mapi (schedule_view сам нормалізує через norm_lesson)
        return {"date": today, "lesson": no, "week_day": 1,
                "started_at": f"{8 + no:02d}:30", "finished_at": f"{8 + no:02d}:15",
                "subject_name": subj, "room_name": room}

    def sched_payload(raw_lessons: list[dict]) -> dict:
        return {key: {"data": raw_lessons}}

    sent.clear()
    asyncio.run(pl._detect_schedule(db, cfg1, acc,
                                    sched_payload([lesson(1, "Математика")]),
                                    "", key))
    check("розклад: калібровка без сповіщення", sent == [])

    sent.clear()
    asyncio.run(pl._detect_schedule(db, cfg1, acc, sched_payload(
        [lesson(1, "Математика"), lesson(2, "Фізика", room="7")]), "", key))
    check("розклад: зміна тижня → сповіщення з новим розкладом",
          len(sent) == 1 and "змінився" in sent[0] and "Фізика" in sent[0],
          str(sent))
    sent.clear()
    asyncio.run(pl._detect_schedule(db, cfg1, acc,
                                    sched_payload([lesson(1, "Математика")]),
                                    "", key))
    check("розклад: повернення до попереднього теж зміна (пам'ятає стан)",
          len(sent) == 1, str(sent))

    # ---------- детект: магазин ----------
    def shop_payload(items: list[dict]) -> dict:
        return {"shop_products": items, "shop_orders": []}

    def prod(pid: int, title: str, price: str, qty: int | None = 5) -> dict:
        return {"id": pid, "title": title, "quantity": qty,
                "prices": [{"price": price, "currency": "COI"}]}

    sent.clear()
    asyncio.run(pl._detect_shop(db, cfg1, acc, shop_payload(
        [prod(1, "Худі", "300")]), ""))
    check("магазин: калібровка без сповіщення", sent == [])
    sent.clear()
    asyncio.run(pl._detect_shop(db, cfg1, acc, shop_payload(
        [prod(1, "Худі", "250"), prod(2, "Кружка", "100", qty=None)]), ""))
    check("магазин: новий товар + зміна ціни виявлені",
          len(sent) == 1 and "Кружка" in sent[0] and "250" in sent[0],
          str(sent))

    # ---------- тихі години: НЕ смикаємо mapi (акаунт пропускається) ----------
    real_quiet = pl._is_quiet_now
    cfg2 = (db.query(TelegramAccountConfig)
            .filter(TelegramAccountConfig.account_id == acc2_id).first())
    if cfg2 is None:
        cfg2 = TelegramAccountConfig(account_id=acc2_id, user_id=user.id,
                                     chat_id=777000111, quiet_hours=False)
        db.add(cfg2)
        db.commit()
    cfg2.quiet_hours = False
    db.commit()

    pl._is_quiet_now = lambda _cfg: True
    units = pl._units_for_cycle(db)
    check("тихі години: акаунт з quiet пропущений (mapi не смикаємо)",
          all(c.account_id != acc1_id for c, _a, _s, _p in units))

    pl._is_quiet_now = lambda _cfg: False  # імітуємо «день»
    units = pl._units_for_cycle(db)
    check("поза вікном обидва акаунти в циклі",
          {c.account_id for c, _a, _s, _p in units} == {acc1_id, acc2_id})
    pl._is_quiet_now = real_quiet

    # секції беруться з конфігу КОЖНОГО акаунта окремо
    cfg1.notify_shop = False
    cfg1.notify_marks = True
    cfg2.notify_shop = True
    cfg2.notify_marks = False
    s1 = pl._sections_for(cfg1, pl._monday())
    s2 = pl._sections_for(cfg2, pl._monday())
    check("розділені конфіги → різні секції запитів",
          "marks" in s1 and "shop" not in s1
          and "shop" in s2 and "marks" not in s2)

    # ---------- розбивка довгих повідомлень ----------
    long_text = "\n".join(f"рядок {i} - довгий вміст для перевірки" * 4
                          for i in range(300))
    parts = tg_bot._chunks(long_text)
    check("довгі повідомлення розбиваються (< 4096 кожна)",
          len(parts) > 1 and all(len(p) <= 4096 for p in parts))
    db.close()

    # ---------- відв'язка (прив'язка + конфіги) ----------
    r = c.post("/api/telegram/unlink", headers=H)
    check("unlink → ok", r.status_code == 200
          and r.json()["data"]["unlinked"] is True)
    r = c.get("/api/telegram/status", headers=H)
    check("після unlink - не прив'язано",
          r.json()["data"]["linked"] is False)
    db = SessionLocal()
    n_cfg = db.query(TelegramAccountConfig).count()
    db.close()
    check("unlink прибрав і конфіги акаунтів", n_cfg == 0)

print()
print(f"Ітог Telegram: {passed} PASS / {failed} FAIL")
sys.exit(1 if failed else 0)
