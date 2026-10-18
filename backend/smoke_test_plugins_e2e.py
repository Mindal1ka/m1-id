"""Smoke-test E2E: реєстрація плагіна в plugins.db + виконання через
service (_run_and_apply) з фейковим юзером. Без мережі/Telegram.

Запуск: python smoke_test_plugins_e2e.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

# ОКРЕМА тимчасова БД: тест не має чіпати реальну plugins.db
_tmp = tempfile.mkdtemp(prefix="m1id_plg_e2e_")
os.environ.update({
    "M1ID_DB_URL": f"sqlite:///{_tmp}/t.db".replace("\\", "/"),
    "M1ID_SECRET_KEY": "plg-e2e-0123456789abcdef0123456789abcdef",
})

sys.path.insert(0, str(Path(__file__).parent))

from app.plugins.store import (PluginFile, PluginInstall, PluginMeta,
                               init_plugin_db, new_session)
from app.plugins import service

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} — {detail}")


init_plugin_db()

MANIFEST = json.loads(
    (Path(__file__).parent.parent / "plugins" / "streak-note" /
     "manifest.json").read_text(encoding="utf-8-sig"))
CODE = (Path(__file__).parent.parent / "plugins" / "streak-note" /
        "plugin.py").read_text(encoding="utf-8-sig")

# 1) реєстрація плагіна в БД (як робить роутер аплоаду)
db = new_session()
try:
    db.query(PluginMeta).filter_by(id="streak-note").delete()
    db.query(PluginFile).filter_by(plugin_id="streak-note").delete()
    db.query(PluginInstall).filter_by(plugin_id="streak-note").delete()
    db.add(PluginMeta(id="streak-note", name=MANIFEST["name"],
                      version=MANIFEST["version"], author="M1 ID",
                      description=MANIFEST["description"], verified=True,
                      manifest=MANIFEST, code_hash="test",
                      uploaded_by=0))
    db.flush()
    db.add(PluginFile(plugin_id="streak-note", path="plugin.py", content=CODE))
    db.add(PluginInstall(user_id=101, plugin_id="streak-note", enabled=True,
                         accepted_permissions=MANIFEST["permissions"],
                         settings={}, storage="{}"))
    db.commit()
finally:
    db.close()
print("== Інсталяція ==")
check("плагін зареєстровано", True)

# 2) TG-команда: /notes з текстом → збереження в storage
print("== TG-команда ==")
reply = asyncio.run(service_run()) if False else None
from app.plugins.service import run_tg_command
reply = asyncio.run(run_tg_command("streak-note", 101, "notes", "купити хліб"))
check("команда відповіла", "Збережено" in reply, reply)
reply2 = asyncio.run(run_tg_command("streak-note", 101, "notes", ""))
check("нотатку видно", "купити хліб" in reply2, reply2)

# 3) storage персист
db = new_session()
try:
    inst = (db.query(PluginInstall)
            .filter_by(user_id=101, plugin_id="streak-note").first())
    stored = json.loads(inst.storage or "{}")
    check("storage збережено",
          "купити хліб" in json.dumps(stored, ensure_ascii=False),
          repr(stored))
finally:
    db.close()

# 4) on_ui
print("== Вкладка (on_ui) ==")
from app.plugins.service import run_ui_request
out = asyncio.run(run_ui_request("streak-note", 101, {}))
check("on_ui ok", out.get("ok"), str(out))
check("дані вкладки", (out.get("data") or {}).get("items"), str(out.get("data")))

# 5) невстановлений юзер → відмова
reply3 = asyncio.run(run_tg_command("streak-note", 999, "notes", ""))
check("чужий юзер без інсталяції", "недоступний" in reply3, reply3)

print(f"\n{PASS} PASS / {FAIL} FAIL")
raise SystemExit(1 if FAIL else 0)