"""Відкат тестових здач: DELETE /homework/delete/{id}."""
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

    for hw_id in IDS:
        r = c.delete(f"{BASE}/v1/mystat/{alias}/homework/delete/{hw_id}",
                     headers=H)
        print(f"delete {hw_id}:", r.status_code, r.text[:120])
        if r.status_code not in (200, 201):
            # можливо delete чекає id здачі — спробуємо знайти за списком
            r = c.get(f"{BASE}/v1/mystat/{alias}/homework/list",
                      params={"limit": 100}, headers=H)
            done = next((g for g in r.json() if g.get("status") == 2), None)
            if done:
                for x in done["data"]:
                    if x["id"] == hw_id:
                        sub = (x.get("homework_stud") or {}).get("id")
                        print("  submission id:", sub)
                        if sub:
                            r2 = c.delete(
                                f"{BASE}/v1/mystat/{alias}/homework/delete/{sub}",
                                headers=H)
                            print(f"  delete sub {sub}:", r2.status_code,
                                  r2.text[:120])

    r = c.get(f"{BASE}/v1/mystat/{alias}/homework/list",
              params={"limit": 100}, headers=H)
    pend = next(g for g in r.json() if g.get("status") == 3)
    ids = [x["id"] for x in pend["data"]]
    print("pending count:", len(ids))
    for hw_id in IDS:
        print(f"  {hw_id} знову pending:", hw_id in ids)
