"""Клієнт навантажувального тесту: сідує юзерів, жене фази, друкує E2E-метрики.

  python scripts/loadtest_client.py [vu] [port]

Фази: cold-burst (холодні dashboard) → warm-max (без think-time) →
realistic (запит раз на 5с).
"""
from __future__ import annotations

import asyncio
import sys
import time
import uuid

VU = int(sys.argv[1]) if len(sys.argv) > 1 else 60
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8126
BASE = f"http://127.0.0.1:{PORT}"

import httpx  # noqa: E402

ERRORS = {"n": 0}
RUN_DUR = 1.0


def lat_stats(samples: list[float]) -> str:
    if not samples:
        return "n=0"
    s = sorted(samples)
    n = len(s)
    return (f"n={n:5d} rps={n / RUN_DUR:6.0f} "
            f"p50={s[n // 2] * 1000:6.0f}ms p95={s[min(n - 1, int(n * .95))] * 1000:6.0f}ms "
            f"p99={s[min(n - 1, int(n * .99))] * 1000:6.0f}ms max={s[-1] * 1000:6.0f}ms "
            f"err={ERRORS['n']}")


async def seed_users(n: int) -> list[dict]:
    async with httpx.AsyncClient(base_url=BASE, timeout=60) as c:
        users = []
        for i in range(n):
            u = uuid.uuid4().hex[:10]
            r = await c.post("/api/auth/register", json={
                "username": f"load_{u}", "password": "SuperSecret1!",
                "email": f"{u}@example.com"})
            pair = r.json()["data"]
            r = await c.post("/api/accounts/link-token", json={
                "access_token": "LOADTOK_aaaaaaaaaaaaaaaaaaaaaaaaaa"},
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


async def vu_user(u: dict, deadline: float, lat: dict[str, list[float]]) -> None:
    headers = {"Authorization": f"Bearer {u['pair']['access_token']}"}
    acc = u["acc"]["id"]
    pool = ["/api/app/dashboard"] * 5 + ["/api/app/homework"] * 2 + \
           ["/api/app/schedule?__account=%d&kind=week" % acc] * 2 + \
           ["/api/app/marks"]
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        i = 0
        while time.perf_counter() < deadline:
            path = pool[i % len(pool)]
            i += 1
            if not path.startswith("/api/app/schedule"):
                path = f"{path}?__account={acc}"
            t0 = time.perf_counter()
            r = await c.get(path, headers=headers)
            lat.setdefault(path.split("?")[0], [])
            if r.status_code == 200:
                lat[path.split("?")[0]].append(time.perf_counter() - t0)
            else:
                ERRORS["n"] += 1


async def cold_burst(users: list[dict],
                     lat: dict[str, list[float]]) -> None:
    async def one(u: dict) -> None:
        headers = {"Authorization": f"Bearer {u['pair']['access_token']}"}
        async with httpx.AsyncClient(base_url=BASE, timeout=60) as c:
            t0 = time.perf_counter()
            r = await c.get(f"/api/app/dashboard?__account={u['acc']['id']}",
                            headers=headers)
            lat.setdefault("/api/app/dashboard", [])
            if r.status_code == 200:
                lat["/api/app/dashboard"].append(time.perf_counter() - t0)
            else:
                ERRORS["n"] += 1

    t0 = time.perf_counter()
    await asyncio.gather(*(one(u) for u in users))
    print(f"[cold-burst] {len(users)} dashboard із холодного кешу "
          f"за {time.perf_counter() - t0:.2f}s total")


async def main() -> None:
    global RUN_DUR
    n_users = max(VU, 20)
    print(f"[client] сідуємо {n_users} користувачів...")
    users = await seed_users(n_users)
    print("[client] чекаємо синк перших 10...")
    await wait_synced(users[:10])

    lat: dict[str, list[float]] = {}

    cold = users[10:10 + VU // 2] if len(users) > 10 else users
    RUN_DUR = 1.0
    ERRORS["n"] = 0
    lat.clear()
    await cold_burst(cold, lat)
    for p, s in sorted(lat.items()):
        print(f"  {p:28s} {lat_stats(s)}")

    RUN_DUR = 20.0
    ERRORS["n"] = 0
    lat.clear()
    deadline = time.perf_counter() + RUN_DUR
    print(f"[warm-max] {VU} VU без think-time, {RUN_DUR:.0f}s...")
    await asyncio.gather(*(vu_user(u, deadline, lat) for u in users[:VU]))
    for p, s in sorted(lat.items()):
        print(f"  {p:28s} {lat_stats(s)}")
    total = sum(len(s) for s in lat.values())
    print(f"  {'РАЗОМ warm':28s} n={total} rps={total / RUN_DUR:.0f} "
          f"err={ERRORS['n']}")

    RUN_DUR = 12.0
    ERRORS["n"] = 0
    lat.clear()
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

    await asyncio.gather(*(realistic(u) for u in users[:VU]))
    for p, s in sorted(lat.items()):
        print(f"  {p:28s} {lat_stats(s)} (think=5s)")
    print("[client] готово.")

if __name__ == "__main__":
    asyncio.run(main())
