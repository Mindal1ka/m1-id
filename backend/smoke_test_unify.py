# Smoke: єдине життя сайту і бота (app_data.on_fresh_data → poller.on_fresh_data)
# + детекти зберігають стан ЛИШЕ після успішного send (події не губляться)
# + кожен детект ізольований try/except.
import asyncio
import json
from datetime import datetime, timedelta
import os
import tempfile

tmp = tempfile.mkdtemp(prefix="m1id_unify_")
os.environ.update({
    "M1ID_DB_URL": f"sqlite:///{tmp}/t.db".replace("\\", "/"),
    "M1ID_SECRET_KEY": "unify-0123456789abcdef0123456789abcdef",
    "M1ID_EMAIL_MX_CHECK": "false",
})

from app.core.security import encrypt_secret, hash_password  # noqa: E402
from app.db.base import SessionLocal, init_db  # noqa: E402
from app.db.models import (  # noqa: E402
    MystatAccount,
    TelegramAccountConfig,
    TelegramPollState,
    User,
)
from app.services import app_data  # noqa: E402
from app.telegram import poller  # noqa: E402

ok = failed = 0


def check(name, cond, extra=""):
    global ok, failed
    cond = bool(cond)
    ok += 1 if cond else 0
    failed += 0 if cond else 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" - {extra}" if extra and not cond else ""))


init_db()
db = SessionLocal()

u = User(username="unify", username_lower="unify",
         email="unify@example.com",
         password_hash=hash_password("SuperSecret1!"))
db.add(u)
db.commit()
acc = MystatAccount(
    user_id=u.id, user_seq=1, mystat_login="univac", fio="Тест Тестовий",
    status="active", language="uk", branch_alias="pl",
    access_token_enc=encrypt_secret("tok"), logbook_id="100",
    id_user_storage="200",
)
db.add(acc)
db.commit()
cfg = TelegramAccountConfig(account_id=acc.id, user_id=u.id, chat_id=111,
                            quiet_hours=False,
                            notify_homework=True, notify_rating=True,
                            notify_schedule_week=True,
                            notify_schedule_day=True, notify_marks=True,
                            notify_leaderboard=True, notify_shop=True)
db.add(cfg)
db.commit()
acc_id, user_id = acc.id, u.id
db.close()

SENT: list[str] = []

# ПІДМІНА відправки Telegram: "мережа" спочатку падає, потім працює
send_state = {"ok": False}


async def fake_send_text(chat_id, text, kb=None):
    if not send_state["ok"]:
        raise RuntimeError("tg network hiccup")
    SENT.append(text)


poller.tg.send_text = fake_send_text

# фейкові payload'и у форматі СИРНОГО mapi (як їх повертає get_payloads)
HW1 = [{"status": 3, "data": [
    {"id": 11, "name_spec": "Фізика", "theme": "КР №1",
     "overdue_time": (datetime.now() + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%S"), "status": 3}]}]
BAL5 = [{"alias": "achivements", "value": 5, "rating": 3}]


def payloads_v2(hw_id=11, ach=5, marks=None):
    monday = poller._monday().isoformat()
    p = {
        "homework": [{"status": 3, "data": [
            {"id": hw_id, "name_spec": "Фізика", "theme": "КР",
             "overdue_time": (datetime.now() + timedelta(hours=6))
             .strftime("%Y-%m-%dT%H:%M:%S"), "status": 3}]}],
        "balances": [{"alias": "achivements", "value": ach, "rating": 3}],
        f"schedule_week@{monday}": {"data": [], "start_day": monday,
                                    "end_date": "2026-09-06"},
    }
    if marks:
        p["stat_marks_year"] = marks
    return p


def state_sections():
    d = SessionLocal()
    try:
        return {r.section for r in
                (d.query(TelegramPollState)
                .filter(TelegramPollState.account_id == acc_id).all())}
    finally:
        d.close()


async def main():
    # 1) КАЛІБРУВАЛЬНИЙ прогін: без сповіщень, стан фіксується одразу
    await poller.on_fresh_data(acc_id, payloads_v2())
    check("калібровка: без сповіщень", len(SENT) == 0)
    check("калібровка: стан збережено",
          {"homework", "rating", "sched_week", "sched_day"}
          <= state_sections(), str(state_sections()))

    # 2) нова домашка + рейтинг змінився, але Telegram «лежить»:
    #    сповіщення не доставлене → стан НЕ переписується → подія жива
    send_state["ok"] = False
    await poller.on_fresh_data(acc_id, payloads_v2(hw_id=12, ach=7))
    check("send failed → без доставки", len(SENT) == 0)
    st_hw = json.loads(json.dumps(
        [r.payload for r in SessionLocal().query(TelegramPollState)
         .filter(TelegramPollState.account_id == acc_id,
                 TelegramPollState.section == "homework")][0]))
    check("send failed → hw-стан залишився СТАРИМ (id 11)",
          "11" in st_hw and "12" not in st_hw, st_hw[:80])

    # 3) мережа оживла: ТІ САМІ дані повторно → доставка спрацювала
    send_state["ok"] = True
    await poller.on_fresh_data(acc_id, payloads_v2(hw_id=12, ach=7))
    check("retry після збою → сповіщення доставлені", len(SENT) >= 2,
          f"sent={len(SENT)}")
    check("після доставки стан оновлено (id 12)",
          "12" in [r.payload for r in SessionLocal()
                   .query(TelegramPollState)
                   .filter(TelegramPollState.account_id == acc_id,
                           TelegramPollState.section == "homework")][0])

    # 4) повторний прогін тих самих даних → дедуп, нових сповіщень немає
    before = len(SENT)
    await poller.on_fresh_data(acc_id, payloads_v2(hw_id=12, ach=7))
    check("без змін → без сповіщень", len(SENT) == before)

    # 5) сайт щойно побачив нову оцінку → бот повідомляє миттєво
    #    (hw_id=12 — домашка без змін, ізольовано саме оцінку)
    await poller.on_fresh_data(acc_id, payloads_v2(
        hw_id=12,
        marks=[{"mark": "12", "mark_date": "2026-09-03",
                "name_spec": "Фізика", "theme": "Тест", "type_work": 1}]))
    check("сайт побачив оцінку → бот повідомив", len(SENT) == before + 1,
          f"sent={len(SENT)}")
    after5 = len(SENT)

    # 6) детект, що падає, не блокує решту
    async def boom(db_, cfg_, acc_, payloads_, prefix_):
        raise RuntimeError("boom")

    saved = poller._detect_rating
    poller._detect_rating = boom
    try:
        await poller.on_fresh_data(acc_id, payloads_v2(hw_id=13, ach=9))
        check("падіння одного детекта не зупиняє решту",
              len(SENT) == after5 + 2, f"sent={len(SENT)}")
    finally:
        poller._detect_rating = saved

    # 7) _arrived_sections: тільки детекти, чий payload реально прийшов
    d = SessionLocal()
    try:
        cfg2 = (d.query(TelegramAccountConfig)
                .filter(TelegramAccountConfig.account_id == acc_id).first())
        monday = poller._monday().isoformat()
        arrived = poller._arrived_sections(cfg2, {"homework": HW1}, monday)
        check("_arrived_sections: перетин конфіга і прибулих",
              set(arrived) == {"homework"}, str(arrived))
    finally:
        d.close()

    # 8) _emit_fresh живучий: sync-виняток у listener нічого не ламає
    app_data._emit_fresh(acc_id, {})
    app_data._fresh_listeners.append(
        lambda a, p: (_ for _ in ()).throw(RuntimeError("sync boom")))
    app_data._emit_fresh(acc_id, {"homework": HW1})
    app_data._fresh_listeners.clear()
    await asyncio.sleep(0.05)
    check("_emit_fresh живучий", True)


asyncio.run(main())
print(f"\nІтог: {ok} PASS / {failed} FAIL")
raise SystemExit(1 if failed else 0)
