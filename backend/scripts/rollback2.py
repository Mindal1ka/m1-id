"""Розбір: як видалити здачу. Шукаємо id здачі в homework_stud."""
import json

import httpx

BASE = "https://mapi.itstep.org"

# Облікові дані беремо ЛИШЕ зі змінних середовища (не зберігаємо у коді).
import os
import sys

LOGIN = os.environ.get("MYSTAT_LOGIN", "")
PASSWORD = os.environ.get("MYSTAT_PASSWORD", "")
if not LOGIN or not PASSWORD:
    sys.exit("Задайте MYSTAT_LOGIN і MYSTAT_PASSWORD у середовищі "
             "(напр. $env:MYSTAT_LOGIN='...'; $env:MYSTAT_PASSWORD='...').")
IDS = [150015, 150012, 148437]

with httpx.Client(timeout=30) as c:
    tok = c.post(f"{BASE}/v1/mystat/auth/login",
                 headers={"X-Language": "uk"},
                 json={"login": LOGIN, "password": PASSWORD}).text.strip()
    H = {"Authorization": f"Bearer {tok}", "X-Language": "uk"}
    me = c.post(f"{BASE}/v1/mystat/auth/me", headers=H).json()
    H["X-UserId"] = str(me["id_user_storage"])
    alias = me["branch_alias"]

    r = c.get(f"{BASE}/v1/mystat/{alias}/homework/list",
              params={"limit": 100}, headers=H)
    checking = next((g for g in r.json() if g.get("status") == 2), None)
    items = {x["id"]: x for x in (checking or {}).get("data", [])}
    for hw_id in IDS:
        x = items.get(hw_id)
        if not x:
            print(hw_id, "— не в «на перевірці»")
            continue
        stud = x.get("homework_stud") or {}
        print(f"== {hw_id} homework_stud keys:", sorted(stud.keys()))
        cand = {k: v for k, v in stud.items()
                if k in ("id", "id_homework", "id_stud", "stud_id",
                         "homework_stud_id") or (k.endswith("id") and isinstance(v, int))}
        print("   id-кандидати:", cand)
        # пробуємо видалити за кожним int-id
        for k, v in cand.items():
            rr = c.delete(f"{BASE}/v1/mystat/{alias}/homework/delete/{v}",
                          headers=H)
            print(f"   delete by {k}={v}:", rr.status_code, rr.text[:80])
            if rr.status_code == 200 and rr.text.strip().lower() == "true":
                break
