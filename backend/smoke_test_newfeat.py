"""Smoke-test нових фіч: Нагороди (awards), Прогрес (stat_progress),
Нагадування про дедлайни ДЗ (_detect_deadlines).

Весь справжній mapi підмінюється httpx.MockTransport — тест офлайновий.
Запуск:  python smoke_test_newfeat.py   (з папки backend, venv активний)
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import uuid
from datetime import datetime, timedelta

_tmp = tempfile.mkdtemp(prefix="m1id_nf_")
os.environ["M1ID_DB_URL"] = f"sqlite:///{_tmp}/test.db".replace("\\", "/")
os.environ["M1ID_SECRET_KEY"] = "newfeat-secret-key-0123456789abcdef-012345"
os.environ["M1ID_TELEGRAM_BOT_TOKEN"] = ''
os.environ["M1ID_EMAIL_MX_CHECK"] = "false"
os.environ["M1ID_DEBUG"] = "1"

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.services import mystat_client as ms  # noqa: E402

ME_PAYLOAD = {
    "id": 111213,
    "id_user_storage": 998877,
    "name": "Тестов Тест",
    "username": "nf_user",
    "lang": "uk",
    "profile": "student",
    "branch_alias": "pl",
    "branch_id": 4,
    "project_id": 50,
    "user_profiles": {
        "50": {"4": [{"user_id": 998877, "photo": "x.png",
                      "logbook_id": 111213}]}
    },
}

AWARDS_ITEMS = {
    "body": [
        {"id": 11, "img": "https://fs3/b1.png", "prices": [],
         "purchased": True, "equipped": True, "default": True, "params": []},
        {"id": 12, "img": "https://fs3/b2.png",
         "prices": [{"value": 60, "currency": "BEV"}],
         "purchased": False, "equipped": False, "default": False, "params": []},
    ],
    "eyes": [
        {"id": 21, "img": "https://fs3/e1.png",
         "prices": [{"value": 40, "currency": "BEV"}],
         "purchased": True, "equipped": False, "default": False, "params": []},
    ],
}

PROGRESS_PAYLOAD = {
    "data": [
        {"chart_type": 3,
         "chart_models": [
             {"date": "2025-09-01", "points": 11, "previous_points": None,
              "has_rasp": False},
             {"date": "2025-10-01", "points": 12, "previous_points": 11,
              "has_rasp": False},
             # живий mapi іноді віддає один місяць ДВІЧІ:
             # раніше фронт падав each_key_duplicate (2026-09)
             {"date": "2025-10-15", "points": None, "previous_points": 12,
              "has_rasp": False},
             {"date": "2026-08-01", "points": None, "previous_points": None,
              "has_rasp": False},
         ],
         "average_point": 11.7, "prev_average_point": 9}],
    "total_average_point": 11.85,
    "prev_total_average_point": 11,
}

hits = {"items": 0, "balance": 0, "buy": 0, "equip": 0}


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    auth = request.headers.get("authorization", "")
    token = auth.replace("Bearer ", "")

    if url.endswith("/mystat/auth/me"):
        if token == "TOK_OK_aaaaaaaaaaaaaaaaaaaaaaaaaaaa":
            return httpx.Response(200, json=ME_PAYLOAD)
        return httpx.Response(401, json=[])

    if "/v1/mystat/pl/" in url:
        if token != "TOK_OK_aaaaaaaaaaaaaaaaaaaaaaaaaaaa":
            return httpx.Response(401, json=[])
        if "custom-awards/items/buy" in url:
            hits["buy"] += 1
            return httpx.Response(200, json={"status": "ok"})
        if "custom-awards/items/equip" in url:
            hits["equip"] += 1
            return httpx.Response(200, json={"status": "ok"})
        if "custom-awards/items" in url:
            hits["items"] += 1
            return httpx.Response(200, json=AWARDS_ITEMS)
        if "custom-awards/balance" in url:
            hits["balance"] += 1
            return httpx.Response(200, json={"beavers": 120})
        if "statistic/progress" in url:
            return httpx.Response(200, json=PROGRESS_PAYLOAD)
        if "homework/list" in url:
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"echo": request.url.path})

    return httpx.Response(404, json={"error": "no_route"})


ms.set_transport(sync=httpx.MockTransport(handler),
                 async_=httpx.MockTransport(handler))

from app.main import app  # noqa: E402

passed = failed = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" — {extra}" if extra and not cond else ""))


from app.db.base import SessionLocal  # noqa: E402
from app.db.models import (  # noqa: E402
    MystatAccount,
    TelegramAccountConfig,
    TelegramLink,
)
from app.telegram import poller as pl  # noqa: E402
from app.telegram import bot as tg_bot  # noqa: E402

UNIQ = uuid.uuid4().hex[:10]

# ---------- детект дедлайнів: підмінюємо доставку ----------
sent: list[str] = []


async def _fake_notify(chat_id, text, kb=None):
    sent.append(text)
    return True


pl._notify = _fake_notify

with TestClient(app) as c:
    r = c.post("/api/auth/register", json={
        "username": f"nf_{UNIQ}", "password": "SuperSecret1!",
        "email": f"{UNIQ}@example.com"})
    check("реєстрація", r.status_code == 200)
    pair = r.json()["data"]
    H = {"Authorization": f"Bearer {pair['access_token']}"}
    user_id = pair["user"]["id"]

    r = c.post("/api/accounts/link-token", json={
        "access_token": "TOK_OK_aaaaaaaaaaaaaaaaaaaaaaaaaaaa"}, headers=H)
    check("link-token", r.status_code == 200 and r.json()["ok"], str(r.json()))

    # ---------- Нагороди ----------
    r = c.get("/api/app/awards", headers=H)
    aw = r.json()["data"]
    check("awards → ok", r.status_code == 200 and r.json()["ok"], str(r.json())[:300])
    check("awards: баланс бобрів = 120", aw.get("beavers") == 120, str(aw)[:200])
    check("awards: категорії нормалізовані (2)",
          len(aw.get("categories") or []) == 2, str(aw)[:300])
    body_cat = next((x for x in aw["categories"] if x["key"] == "body"), None)
    check("awards: item без prices → free", body_cat is not None
          and body_cat["items"][0]["free"] is True
          and body_cat["items"][0]["price"] == 0, str(body_cat))
    check("awards: item з ціною → price/currency",
          body_cat["items"][1]["price"] == 60
          and body_cat["items"][1]["currency"] == "BEV")

    r = c.post("/api/app/awards/equip", headers=H,
               json={"item_id": 21})
    check("awards/equip → ok", r.status_code == 200 and r.json()["ok"],
          str(r.json())[:200])
    check("awards/equip: mapi викликано", hits["equip"] == 1)
    n_before = hits["items"]
    r = c.get("/api/app/awards", headers=H)
    check("awards/equip: кеш каталогу інвалідовано (live-дозапит)",
          hits["items"] == n_before + 1,
          f"hits={hits['items']} before={n_before}")

    r = c.post("/api/app/awards/buy", headers=H, json={"items": [12]})
    check("awards/buy → ok", r.status_code == 200 and r.json()["ok"],
          str(r.json())[:200])

    r = c.post("/api/app/awards/buy", headers=H, json={"items": []})
    check("awards/buy: порожній items → 422", r.status_code == 422)

    # ---------- Прогрес ----------
    r = c.get("/api/app/progress", headers=H)
    pr = r.json()["data"]
    check("progress → ok", r.status_code == 200 and r.json()["ok"],
          str(r.json())[:300])
    check("progress: total_average", pr.get("total_average") == 11.85,
          str(pr)[:300])
    ch = (pr.get("charts") or [{}])[0]
    check("progress: chart нормалізований",
          ch.get("average") == 11.7 and len(ch.get("points") or []) == 3
          and ch["points"][1]["points"] == 12, str(ch))
    check("progress: дублікат місяця склеєний (кожен місяць один раз)",
          len(ch["points"]) == 3
          and ch["points"][1]["prev"] == 12, str(ch["points"]))
    check("progress: null-місяць лишається null",
          ch["points"][2]["points"] is None, str(ch["points"]))

    # ---------- Нагадування про дедлайни ----------
    db = SessionLocal()
    acc = (db.query(MystatAccount)
           .filter(MystatAccount.user_id == user_id).first())
    cfg = (db.query(TelegramAccountConfig)
           .filter(TelegramAccountConfig.account_id == acc.id).first())
    if cfg is None:
        cfg = TelegramAccountConfig(account_id=acc.id, user_id=acc.user_id,
                                    chat_id=777000111)
        db.add(cfg)
        db.commit()
    cfg.notify_deadlines = True
    cfg.notify_homework = False
    db.commit()

    now = datetime.now()

    def hw_payload(due_iso: str, hw_id: int = 901) -> dict:
        return {"homework": [{"status": 3, "data": [
            {"id": hw_id, "name_spec": "Математика", "theme": "Інтеграли",
             "overdue_time": due_iso}]}]}

    # секції: deadlines без homework_new → домашка все одно тягнеться
    secs = pl._sections_for(cfg, now.date())
    check("секції: deadlines вмикає homework",
          "homework" in secs and secs["homework"] == ["homework"], str(secs))
    cfg.notify_deadlines = False
    check("секції: обидва вимкнені → без homework",
          "homework" not in pl._sections_for(cfg, now.date()))
    cfg.notify_deadlines = True
    db.commit()

    # 1. дедлайн далеко (>24 год) → тихо
    sent.clear()
    asyncio.run(pl._detect_deadlines(
        db, cfg, acc, hw_payload((now + timedelta(days=3)).isoformat()), ""))
    check("дедлайн за 3 дні → тихо", sent == [], str(sent))

    # 2. дедлайн за 23 год → поріг 24 спрацьовує
    sent.clear()
    asyncio.run(pl._detect_deadlines(
        db, cfg, acc,
        hw_payload((now + timedelta(hours=23)).isoformat()), ""))
    check("дедлайн за 23 год → сповіщення",
          len(sent) == 1 and "Наближається дедлайн" in sent[0]
          and ("за 23 год" in sent[0] or "за 22 год" in sent[0])
          and "Інтеграли" in sent[0], str(sent))

    # 3. повторний прогін без змін → тихо (стан зафіксовано)
    sent.clear()
    asyncio.run(pl._detect_deadlines(
        db, cfg, acc,
        hw_payload((now + timedelta(hours=23)).isoformat()), ""))
    check("повторний прогін → тихо (без дубля)", sent == [], str(sent))

    # 4. дедлайн за 2 год → поріг 3 спрацьовує
    sent.clear()
    asyncio.run(pl._detect_deadlines(
        db, cfg, acc,
        hw_payload((now + timedelta(hours=2)).isoformat()), ""))
    check("дедлайн за 2 год → друге нагадування",
          len(sent) == 1 and ("за 2 год" in sent[0]
                              or "за 1 год" in sent[0]), str(sent))

    # 5. минулий дедлайн → мовчки закритий
    sent.clear()
    asyncio.run(pl._detect_deadlines(
        db, cfg, acc,
        hw_payload((now - timedelta(days=1)).isoformat()), ""))
    check("дедлайн минув → тихо", sent == [], str(sent))

    # 6. кілька робіт → одне повідомлення з двома рядками
    sent.clear()
    two = {"homework": [{"status": 3, "data": [
        {"id": 902, "name_spec": "Фізика", "theme": "Оптика",
         "overdue_time": (now + timedelta(hours=2)).isoformat()},
        {"id": 903, "name_spec": "Хімія", "theme": "Органіка",
         "overdue_time": (now + timedelta(hours=1)).isoformat()},
    ]}]}
    asyncio.run(pl._detect_deadlines(db, cfg, acc, two, ""))
    check("дві роботи → одне повідомлення, 2 рядки",
          len(sent) == 1 and "Дедлайни" in sent[0]
          and "Оптика" in sent[0] and "Органіка" in sent[0], str(sent))

    # 7. тихі години: не шлемо І не фіксуємо → після вікна надійде
    orig_quiet = pl._is_quiet_now
    try:
        pl._is_quiet_now = lambda c: True
        sent.clear()
        fresh = {"homework": [{"status": 3, "data": [
            {"id": 904, "name_spec": "Історія", "theme": "Козацька доба",
             "overdue_time": (now + timedelta(hours=1, minutes=50))
             .isoformat()}]}]}
        asyncio.run(pl._detect_deadlines(db, cfg, acc, fresh, ""))
        check("тихі години → без сповіщення", sent == [], str(sent))
        pl._is_quiet_now = lambda c: False
        sent.clear()
        asyncio.run(pl._detect_deadlines(db, cfg, acc, fresh, ""))
        check("після тихих годин → нагадування прийшло",
              len(sent) == 1 and "Козацька доба" in sent[0], str(sent))
    finally:
        pl._is_quiet_now = orig_quiet

    # 8. вимкнений тумблер через API
    link = TelegramLink(user_id=user_id, chat_id=777000111,
                        bot_username="")
    db.add(link)
    db.commit()
    r = c.post("/api/telegram/settings", headers=H,
               json={"account_seq": 1, "deadlines": False})
    check("settings: deadlines=false зберігається",
          r.status_code == 200 and r.json()["data"]["deadlines"] is False,
          str(r.json())[:300])
    r = c.get("/api/telegram/status", headers=H)
    st = r.json()["data"]["accounts"][0]["settings"]
    check("status: deadlines=False у налаштуваннях",
          st is not None and st["deadlines"] is False, str(st))
    db.close()

print(f"\nПідсумок newfeat: {passed} PASS / {failed} FAIL")
raise SystemExit(0 if failed == 0 else 1)
