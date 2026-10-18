"""Відтворення смерті бекенда: акаунт з НЕЧИТАБЕЛЬНИМ токеном (стан
користувача після зміни ключа) + реальний uvicorn + dashboard.

Запуск:  python scripts/repro_crash.py
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

PORT = 8082
_tmp = tempfile.mkdtemp(prefix="m1id_crash_")
env = os.environ.copy()
env.update({
    "M1ID_DB_URL": f"sqlite:///{_tmp}/crash.db".replace("\\", "/"),
    "M1ID_SECRET_KEY": "crash-repro-0123456789abcdef0123456789abcdef",
    "M1ID_EMAIL_MX_CHECK": "false",
})
os.environ.update(env)  # репро-процес має бачити ту саму БД

BASE = f"http://127.0.0.1:{PORT}"
out_path = Path(_tmp) / "uvicorn.log"
proc = subprocess.Popen(
    [str(Path(".venv/Scripts/python.exe").resolve()), "-m", "uvicorn",
     "app.main:app", "--port", str(PORT)],
    cwd=Path(__file__).resolve().parents[1],
    env=env,
    stdout=open(out_path, "w", encoding="utf-8"),
    stderr=subprocess.STDOUT,
)

sys.path.insert(0, ".")

try:
    for _ in range(40):
        try:
            if httpx.get(f"{BASE}/api/health", timeout=2).status_code == 200:
                print("[OK] server up")
                break
        except Exception:
            time.sleep(0.5)
    else:
        print("[FAIL] no server")
        sys.exit(1)

    # --- юзер через справжній API, акаунт зі сміттєвим токеном просто в БД ---
    from app.db.base import SessionLocal
    from app.db.models import MystatAccount, User

    UNIQ = uuid.uuid4().hex[:8]
    r = httpx.post(f"{BASE}/api/auth/register",
                   json={"username": f"crash_{UNIQ}",
                         "password": "SuperSecret1!",
                         "email": f"{UNIQ}@gmail.com"}, timeout=10)
    pair = r.json()["data"]
    H = {"Authorization": f"Bearer {pair['access_token']}"}
    uname = f"crash_{UNIQ}"

    db = SessionLocal()
    user = db.query(User).filter(User.username == uname).first()
    acc = MystatAccount(user_id=user.id, branch_alias="pl", logbook_id="1",
                        id_user_storage="1", fio="Креш Тест",
                        access_token_enc="garbage-from-old-ephemeral-key")
    db.add(acc)
    db.commit()
    acc_id = acc.id
    db.close()
    print(f"[OK] user={user.id} account={acc_id} з НЕЧИТАБЕЛЬНИМ токеном")

    try:
        r = httpx.get(f"{BASE}/api/app/dashboard?__account={acc_id}",
                      headers=H, timeout=15)
        print(f"[dashboard] → {r.status_code} {r.text[:200]}")
    except Exception as exc:
        print(f"[dashboard] EXCEPTION: {exc!r}")

    time.sleep(1)
    print(f"[process] alive={proc.poll() is None}")
    try:
        r2 = httpx.get(f"{BASE}/api/accounts", headers=H, timeout=5)
        print(f"[after] /api/accounts → {r2.status_code}")
    except Exception as exc:
        print(f"[after] /api/accounts EXCEPTION: {exc!r}")
finally:
    proc.terminate()
    time.sleep(0.5)
    if out_path.exists():
        print("\n===== uvicorn.log (хвіст) =====")
        print(out_path.read_text(encoding="utf-8")[-3500:])
