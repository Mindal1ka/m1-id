"""Прогон користувацького сценарію через РЕАЛЬНИЙ uvicorn (не TestClient):
register → link (живий mapi) → синк → dashboard → повторний dashboard.

Шукаємо зависання/помилки, які не видно в TestClient.
Запуск:  python scripts/real_server_check.py <login> <password>
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx

LOGIN, PASSWORD = sys.argv[1], sys.argv[2]
PORT = 8081
_tmp = tempfile.mkdtemp(prefix="m1id_real_")

env = os.environ.copy()
env.update({
    "M1ID_DB_URL": f"sqlite:///{_tmp}/real.db".replace("\\", "/"),
    "M1ID_SECRET_KEY": "real-server-check-0123456789abcdef0123456789",
    "M1ID_EMAIL_MX_CHECK": "false",
})

proc = subprocess.Popen(
    [str(Path(".venv/Scripts/python.exe").resolve()), "-m", "uvicorn",
     "app.main:app", "--port", str(PORT)],
    cwd=Path(__file__).resolve().parents[1],
    env=env,
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
)

BASE = f"http://127.0.0.1:{PORT}"
failures = 0


def step(name: str, timeout: float, fn):
    global failures
    t0 = time.time()
    try:
        result = fn()
        print(f"[OK {time.time()-t0:5.2f}s] {name}")
        return result
    except Exception as exc:  # noqa: BLE001
        failures += 1
        print(f"[FAIL {time.time()-t0:5.2f}s] {name}: {exc!r}")
        return None


def wait_sync(H, aid, timeout_s=90):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        st = httpx.get(f"{BASE}/api/accounts/{aid}/sync/status",
                       headers=H, timeout=5).json()["data"]
        if st.get("status") in ("done", "error"):
            return st
        time.sleep(0.5)
    raise TimeoutError("sync did not finish")


try:
    up = None
    for _ in range(40):
        try:
            if httpx.get(f"{BASE}/api/health", timeout=2).status_code == 200:
                up = True
                print("[OK      ] server up")
                break
        except Exception:
            time.sleep(0.5)
    if not up:
        print("[FAIL    ] server did not start")
        sys.exit(1)

    UNIQ = uuid.uuid4().hex[:8]
    r = step("register", 15, lambda: httpx.post(
        f"{BASE}/api/auth/register",
        json={"username": f"real_{UNIQ}", "password": "SuperSecret1!",
              "email": f"{UNIQ}@gmail.com"}))
    if r is None:
        sys.exit(1)
    pair = r.json()["data"]
    H = {"Authorization": f"Bearer {pair['access_token']}"}

    r = step("link (живий mapi)", 30, lambda: httpx.post(
        f"{BASE}/api/accounts/link",
        json={"login": LOGIN, "password": PASSWORD}, headers=H))
    if r is None:
        sys.exit(1)
    aid = r.json()["data"]["account"]["id"]
    print(f"       account id={aid}")

    step("wait sync", 90, lambda: wait_sync(H, aid))

    step("dashboard #1", 30, lambda: httpx.get(
        f"{BASE}/api/app/dashboard?__account={aid}", headers=H))
    step("dashboard #2 (кеш)", 10, lambda: httpx.get(
        f"{BASE}/api/app/dashboard?__account={aid}", headers=H))
    step("homework", 20, lambda: httpx.get(
        f"{BASE}/api/app/homework?__account={aid}", headers=H))
    step("schedule week", 20, lambda: httpx.get(
        f"{BASE}/api/app/schedule?kind=week&__account={aid}", headers=H))
    step("marks year", 20, lambda: httpx.get(
        f"{BASE}/api/app/marks?period=year&__account={aid}", headers=H))

    print("\nПідсумок:", "УСІ кроки пройшли без зависань" if failures == 0
          else f"{failures} провалів")
finally:
    proc.terminate()
