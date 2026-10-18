"""M0 smoke-test: спека вантажиться, SpecRegistry працює, системні роути живі.

Запуск:  python smoke_test_m0.py   (з папки backend, venv активний)
Відповіді API — у конверті {ok, data, meta, error}.
"""
from __future__ import annotations

import os
import sys

# M0 вантажить .env (реальний токен бота) — у smoke-тесті бота НЕ піднімаємо
os.environ["M1ID_TELEGRAM_BOT_TOKEN"] = ""

from fastapi.testclient import TestClient

from app.main import app

passed = failed = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))


with TestClient(app) as client:
    # 1. health
    r = client.get("/api/health")
    body = r.json()
    check("GET /api/health → конверт ok", r.status_code == 200
          and body["ok"] is True and body["error"] is None)
    check("health.data.service = M1 ID",
          body.get("data", {}).get("service") == "M1 ID", str(body))

    # 2. статистика спеки (снапшот: 162 шляхи / 167 операцій / 51 схема / 17 тегів)
    st = client.get("/api/system/spec/stats").json()["data"]
    check("stats.operations > 150", st["operations"] > 150, str(st["operations"]))
    check("stats.paths > 150", st["paths"] > 150, str(st["paths"]))
    check("stats.schemas >= 50", st["schemas"] >= 50, str(st["schemas"]))
    check("stats.tags >= 15", st["tags"] >= 15, str(st["tags"]))
    check("специ — MyStat API", "MyStat" in (st.get("title") or ""))

    # 3. довідник операцій
    r = client.get("/api/system/spec/operations", params={"tag": "Homework"})
    j = r.json()
    ops = j["data"]
    check("операцій Homework >= 8 (meta.count)", len(ops) >= 8
          and j.get("meta", {}).get("count") == len(ops))
    ids = {o["operation_id"] for o in ops}
    check("є homework_list", any("homework_list" in i for i in ids))

    r = client.get("/api/system/spec/operations", params={"q": "leader"})
    check("пошук 'leader' знаходить leader-table",
          any("leader_table" in o["operation_id"] for o in r.json()["data"]))

    # 4. матчинг шляхів із параметрами — ядро майбутнього проксі
    reg = app.state.registry
    hit = reg.match("GET", "/v1/mystat/pl/homework/list")
    check("match homework/list",
          hit is not None and hit[0].params == ("branch_alias",))
    if hit:
        op, params = hit
        check("branch_alias витягнуто", params == {"branch_alias": "pl"}, str(params))
        check("concrete_path збирається",
              op.concrete_path(**params) == "/v1/mystat/pl/homework/list")

    hit2 = reg.match("GET", "/v1/mystat/pl/homework/12345")
    check("match homework/{id}",
          hit2 is not None and hit2[1].get("homework_id") == "12345")
    check("невідомий шлях → None", reg.match("GET", "/v1/nonexistent/xyz") is None)

    # 5. схема з components
    login_schema = reg.schema("LoginIn")
    check("schema LoginIn.login/password",
          {"login", "password"} <= set(login_schema.get("properties", {})))

print(f"\nПідсумок M0: {passed} PASS / {failed} FAIL")
sys.exit(1 if failed else 0)
