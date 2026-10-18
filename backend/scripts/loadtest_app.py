"""Навантажувальний тест M1 ID: реальний uvicorn-стек + замоканий mapi.

Фази:
  1) cold-burst  — усі VU одночасно відкривають dashboard (холодні снапшоти,
                   fan-out у mapi + запис снапшотів);
  2) warm-max    — стеля читань із кешу (без think-time), змішаний трафік;
  3) realistic   — юзер відкриває екран раз на ~5с (профіль «дивиться застосунок»).

Запуск:  python scripts/loadtest_app.py [vu] [port]
Обмеження rate_limit знято (тестуємо стелю, а не ліміти).
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import statistics
import sys
import tempfile
import threading
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

VU = int(sys.argv[1]) if len(sys.argv) > 1 else 60
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8123
BASE = f"http://127.0.0.1:{PORT}"

# ── середовище тесту ДО імпорту app ──────────────────────────────
_tmp = tempfile.mkdtemp(prefix="m1id_load_")
os.environ["M1ID_DB_URL"] = f"sqlite:///{_tmp}/load.db".replace("\\", "/")
os.environ["M1ID_SECRET_KEY"] = "load-test-secret-key-0123456789abcdef-0123456789"
os.environ["M1ID_EMAIL_MX_CHECK"] = "false"
os.environ["M1ID_DEBUG"] = "1"

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import Depends  # noqa: E402

# знімаємо rate-limit (міряємо стелю, не ліміти)
import app.services.ratelimit as _rl  # noqa: E402


async def _noop() -> None:
    return None


_rl.rate_limit = lambda *a, **k: Depends(_noop)
_rl.rate_limit_user = _rl.rate_limit

logging.getLogger("m1id").setLevel(logging.WARNING)  # не спамимо access-логом
logging.getLogger("asyncio").setLevel(logging.CRITICAL)  # шум proactor на Win

# ── мок mapi: правдоподібні розміри відповідей ──────────────────
TOKEN_OK = "LOADTOK_aaaaaaaaaaaaaaaaaaaaaaaaaa"


def _marks(n: int) -> list[dict]:
    subjects = ["Алгебра", "Геометрія", "Фізика", "Хімія", "Історія",
                "Укр.мова", "Інформатика", "Англійська"]
    out = []
    for i in range(n):
        s = subjects[i % len(subjects)]
        out.append({
            "y": str(2026), "m": str(1 + i % 12), "d": str(1 + i % 28),
            "mark": str(3 + i % 10), "name_spec": s,
            "theme": f"Тема №{i}", "fio_teach": "Вчитель В. В.",
            "photo_pas": "", "comment": "",
        })
    return out


def _lessons(n: int, day: int) -> list[dict]:
    return [{
        "date": f"2026-08-{24 + day:02d}", "week_day": str(1 + day % 7),
        "lesson": (i % 8) + 1,
        "started_at": f"0{i % 8}:30:00", "finished_at": f"0{i % 8}:15:00",
        "subject_name": f"Предмет-{i % 9}", "lesson_theme": "Тема",
        "teacher_name": "Вчитель", "room_name": "201", "mark": 11,
        "attendance": "100", "was": 1, "was_type": None,
        "mark_type": 1, "homeworks": [], "video_link": None,
    } for i in range(n)]


def _hw(n: int) -> list[dict]:
    return [{"status": g, "data": [{
        "id": 100000 + i, "name_spec": f"Предмет-{i % 8}",
        "theme": f"ДЗ №{i}", "fio_teach": "Вчитель",
        "creation_time": "2026-08-20 10:00:00",
        "overdue_time": "2026-08-30 23:59:00",
        "status": g, "coins_to_close_deadline": 20,
        "is_autotest": False, "is_retake": False,
        "file_path": "", "homework_stud": {"mark": None},
    } for i in range(n)]} for g in (3, 2, 1)]


_ME = {"id": 0, "id_user_storage": 0, "name": "Навантаж Тест",
       "lang": "uk", "branch_alias": "pl",
       "user_profiles": {"50": {"4": [{"photo": "x.png"}]}}}

_SECTIONS: dict[str, object] = {
    "profile": _ME, "config": {"data": {"ok": 1}},
    "counters": [{"counter_type": f"c{i}", "counter": i} for i in range(20)],
    "balances": [{"alias": a, "value": 100} for a in ("coins", "cristals", "achivements")],
    "schedule_week": {"data": _lessons(40, 0), "start_day": "2026-08-24"},
    "schedule_month": {"data": _lessons(160, 0), "start_day": "2026-08-01"},
    "homework": _hw(20),
    "stat_marks": _marks(40),
    "stat_marks_year": _marks(600),      # ~94 КБ як у живому API
    "stat_attendance": [{"d": 1}],
    "news": [{"id": i, "title": "Новина", "preview_text": "..." * 20,
              "image": "http://x/y.jpg", "is_viewed": i % 3 == 0,
              "published_at": "2026-08-20 10:00:00",
              "created_by_fullname": "Дирекція"} for i in range(15)],
    "shop_products": [{"id": i, "title": "Товар", "text": "..." * 10,
                       "image": ["http://x/y.jpg"], "quantity": 5,
                       "prices": [{"price": "231.00", "min_price": "100",
                                   "currency": "COI"}],
                       "properties": []} for i in range(20)],
    "shop_orders": [{"id": i, "uuid": str(uuid.uuid4()), "status": 4,
                     "created_at": "2026-08-20 10:00:00", "can_discard": False,
                     "products": [{"product_id": 1, "title": "Товар",
                                   "quantity": 1, "image": ["u"],
                                   "order_product_price": [{"price": 196,
                                                            "currency": "COI"}]}]}
                    for i in range(10)],
    "qr": "data:image/png;base64," + "A" * 1500,
    "leader_points": {"group": {"totalCount": 500, "studentPosition": 42},
                      "stream": {"totalCount": 2000, "studentPosition": 150}},
    "leader_table": {"group": {"month": {"top": [], "other": [], "new_students": []},
                               "all_time": {"top": [], "other": [],
                                            "new_students": []}},
                     "stream": {"month": {"top": [], "other": [],
                                          "new_students": []},
                                "all_time": {"top": [], "other": [],
                                             "new_students": []}}},
    "stat_progress": {"ok": 1},
    "payment": {"full_name": "Навантаж Тест", "student_cost": 3000},
    "payment_next": {"debtor_status": 0, "amount": 0},
    "payment_history": [],
    "payment_schedule": [],
    "clubs": [], "club_abonements": [], "club_balance": {"amount": 0},
    "club_transactions": [], "contacts": {"address": "Київ"},
    "custom_awards_items": [], "custom_awards_balance": {"amount": 0},
}


async def mapi_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    await asyncio.sleep(0.003)  # імітація RTT mapi ~3мс
    if url.endswith("/v1/mystat/auth/me"):
        return httpx.Response(200, json=_ME)
    if url.endswith("/v1/mystat/auth/refresh"):
        return httpx.Response(200, text=TOKEN_OK)
    if "/schedule/get-month" in url:
        return httpx.Response(200, json=_SECTIONS["schedule_month"]
                              if "type=month" in url else _SECTIONS["schedule_week"])
    for key in ("profile", "config", "counters", "balances", "homework",
                "stat_marks", "stat_attendance", "news", "shop_products",
                "shop_orders", "qr", "leader_points", "leader_table",
                "stat_progress", "payment", "clubs", "club_abonements",
                "club_balance", "club_transactions", "contacts",
                "custom-awards/items", "custom-awards/balance"):
        slug = key.replace("custom-awards/items", "custom-awards/items")
        if f"/{key}" in url or url.endswith(f"/{key}"):
            return httpx.Response(200, json=_SECTIONS.get(key, {"ok": 1}))
    if "/statistic/marks" in url:
        period = "month" if "period=month" in url else "year"
        return httpx.Response(200, json=_SECTIONS[f"stat_marks_{period}"
                                                 if period == "year"
                                                 else "stat_marks"])
    if "/students/get-qr-code" in url:
        return httpx.Response(200, json=_SECTIONS["qr"])
    return httpx.Response(200, json={"ok": 1})


import app.services.mystat_client as ms  # noqa: E402

ms.set_transport(sync=httpx.MockTransport(mapi_handler),
                 async_=httpx.MockTransport(mapi_handler))

from app.main import app  # noqa: E402

# ── серверний час обробки (не залежить від CPU VU-клієнтів) ────
SERVER_TIMES: list[tuple[str, float]] = []


@app.middleware("http")
async def _server_timing(request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    SERVER_TIMES.append((request.url.path.split("?")[0],
                         time.perf_counter() - t0))
    return response

# ── uvicorn у фоновому потоці ────────────────────────────────────
config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning",
                        access_log=False)
server = uvicorn.Server(config)
threading.Thread(target=server.run, daemon=True).start()
for _ in range(100):
    if server.started:
        break
    time.sleep(0.1)
print(f"[load] uvicorn on {BASE}, DB={os.environ['M1ID_DB_URL']}")


def lat_stats(samples: list[float]) -> str:
    if not samples:
        return "n=0"
    s = sorted(samples)
    n = len(s)

    def pct(p: float) -> float:
        return s[min(n - 1, int(n * p))]

    return (f"n={n:5d} rps={n / RUN_DUR:6.0f} "
            f"p50={pct(0.50) * 1000:6.0f}ms p95={pct(0.95) * 1000:6.0f}ms "
            f"p99={pct(0.99) * 1000:6.0f}ms max={s[-1] * 1000:6.0f}ms "
            f"err={ERRORS['n']}")


def server_stats(paths: tuple[str, ...]) -> str:
    rows = [d for p, d in SERVER_TIMES if p in paths]
    if not rows:
        return "сервер: немає даних"
    rows.sort()
    n = len(rows)
    p50 = rows[n // 2] * 1000
    p95 = rows[min(n - 1, int(n * 0.95))] * 1000
    avg = sum(rows) / n * 1000
    return (f"сервер: n={n} p50={p50:.0f}ms p95={p95:.0f}ms "
            f"avg={avg:.0f}ms → ~{1000 / max(avg, 0.001):.0f} rps/ядро еквів.")


RUN_DUR = 1.0
ERRORS = {"n": 0}


async def seed_users(n: int) -> list[dict]:
    """Реєструємо n користувачів і прив'язуємо акаунти (снапшоти НЕ
    прогріваємо — dashboard буде холодним)."""
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        users = []
        for i in range(n):
            u = uuid.uuid4().hex[:10]
            r = await c.post("/api/auth/register", json={
                "username": f"load_{u}", "password": "SuperSecret1!",
                "email": f"{u}@example.com"})
            pair = r.json()["data"]
            r = await c.post("/api/accounts/link-token", json={
                "access_token": TOKEN_OK},
                headers={"Authorization": f"Bearer {pair['access_token']}"})
            acc = r.json()["data"]["account"]
            users.append({"pair": pair, "acc": acc})
        return users


async def wait_synced(users: list[dict]) -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        for u in users:
            h = {"Authorization": f"Bearer {u['pair']['access_token']}"}
            for _ in range(150):
                st = (await c.get(
                    f"/api/accounts/{u['acc']['id']}/sync/status",
                    headers=h)).json()["data"]
                if st.get("status") in ("done", "error"):
                    break
                await asyncio.sleep(0.2)


async def vu_user(u: dict, deadline: float, think: float,
                  lat: dict[str, list[float]]) -> None:
    """Один віртуальний юзер: цикл запитів за вагами екранів."""
    headers = {"Authorization": f"Bearer {u['pair']['access_token']}"}
    acc = u["acc"]["id"]
    mix = [("/api/app/dashboard", 5), ("/api/app/homework", 2),
           ("/api/app/schedule", 2), ("/api/app/marks", 1)]
    pool = [p for p, w in mix for _ in range(w)]
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        while time.perf_counter() < deadline:
            path = pool[int(time.perf_counter() * 1000) % len(pool)]
            if path == "/api/app/schedule":
                path += "?__account=%d&kind=week" % acc
            else:
                path += f"?__account={acc}"
            t0 = time.perf_counter()
            r = await c.get(path, headers=headers)
            dt = time.perf_counter() - t0
            lat.setdefault(path.split("?")[0], [])
            if r.status_code == 200:
                lat[path.split("?")[0]].append(dt)
            else:
                ERRORS["n"] += 1


async def cold_burst(users: list[dict],
                     lat: dict[str, list[float]]) -> None:
    """Усі юзери одночасно відкривають dashboard за холодним кешем."""
    async def one(u: dict) -> None:
        headers = {"Authorization": f"Bearer {u['pair']['access_token']}"}
        async with httpx.AsyncClient(base_url=BASE, timeout=60) as c:
            t0 = time.perf_counter()
            r = await c.get(f"/api/app/dashboard?__account={u['acc']['id']}",
                            headers=headers)
            dt = time.perf_counter() - t0
            lat.setdefault("/api/app/dashboard", [])
            if r.status_code == 200:
                lat["/api/app/dashboard"].append(dt)
            else:
                ERRORS["n"] += 1

    t0 = time.perf_counter()
    await asyncio.gather(*(one(u) for u in users))
    print(f"[cold-burst] всі {len(users)} dashboard із холодного кешу "
          f"за {time.perf_counter() - t0:.2f}s total")


async def main() -> None:
    global RUN_DUR
    n_users = max(VU, 20)
    print(f"[load] сідуємо {n_users} користувачів...")
    users = await seed_users(n_users)
    print("[load] чекаємо синк снапшотів...")
    await wait_synced(users[:10])  # перші 10 прогріті; решті холодно

    lat: dict[str, list[float]] = {}

    # 1) cold burst: VU/2 юзерів із холодними снапшотами
    cold_users = users[10:10 + VU // 2] if len(users) > 10 else users
    RUN_DUR = 1.0
    ERRORS["n"] = 0
    lat.clear()
    await cold_burst(cold_users, lat)
    for p, s in sorted(lat.items()):
        print(f"  {p:28s} {lat_stats(s)}")

    # 2) warm стеля: всі VU, без think-time
    warm_users = users[:VU]
    RUN_DUR = 20.0
    ERRORS["n"] = 0
    lat.clear()
    SERVER_TIMES.clear()
    deadline = time.perf_counter() + RUN_DUR
    print(f"[warm-max] {VU} VU без think-time, {RUN_DUR:.0f}s...")
    await asyncio.gather(*(vu_user(u, deadline, 0.0, lat) for u in warm_users))
    for p, s in sorted(lat.items()):
        print(f"  {p:28s} {lat_stats(s)}")
    total = sum(len(s) for s in lat.values())
    print(f"  {'РАЗОМ warm':28s} n={total} rps={total / RUN_DUR:.0f} "
          f"err={ERRORS['n']}")
    print(f"  {'':28s} {server_stats(('/api/app/dashboard', '/api/app/homework', '/api/app/schedule', '/api/app/marks'))}")

    # 3) реалістичний профіль: запит раз на 5с на юзера
    RUN_DUR = 12.0
    ERRORS["n"] = 0
    lat.clear()
    SERVER_TIMES.clear()
    deadline = time.perf_counter() + RUN_DUR

    async def realistic(u: dict) -> None:
        headers = {"Authorization": f"Bearer {u['pair']['access_token']}"}
        async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
            while time.perf_counter() < deadline:
                t0 = time.perf_counter()
                r = await c.get(
                    f"/api/app/dashboard?__account={u['acc']['id']}",
                    headers=headers)
                lat.setdefault("/api/app/dashboard", [])
                if r.status_code == 200:
                    lat["/api/app/dashboard"].append(time.perf_counter() - t0)
                else:
                    ERRORS["n"] += 1
                await asyncio.sleep(5.0)

    await asyncio.gather(*(realistic(u) for u in warm_users))
    for p, s in sorted(lat.items()):
        print(f"  {p:28s} {lat_stats(s)} (think=5s)")
    print(f"  {'':28s} {server_stats(('/api/app/dashboard',))}")

    server.should_exit = True
    print("[load] готово.")
if __name__ == "__main__":
    asyncio.run(main())
