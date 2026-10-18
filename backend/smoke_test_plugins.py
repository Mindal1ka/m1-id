"""Smoke-тест системи плагінів M1 ID (без мережі і Telegram).

Перевіряє: AST-аналізатор, валідацію маніфеста, санітізер (сліпий API),
worker runner (успіх, помилка, таймаут), ліміти сповіщень.
Запуск: python smoke_test_plugins.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# ОКРЕМА тимчасова БД: тест не має чіпати реальну plugins.db
_tmp = tempfile.mkdtemp(prefix="m1id_plg_smoke_")
os.environ.update({
    "M1ID_DB_URL": f"sqlite:///{_tmp}/t.db".replace("\\", "/"),
    "M1ID_SECRET_KEY": "plg-smoke-0123456789abcdef0123456789abcdef",
})

sys.path.insert(0, str(Path(__file__).parent))

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} — {detail}")


# ---------------------------------------------------------------- аналізатор
print("== AST-аналізатор ==")
from app.plugins.analyzer import CodePolicyError, analyze, entry_functions

try:
    analyze("import os\nprint(1)")
    check("reject import os", False, "не відхилив")
except CodePolicyError as e:
    check("reject import os", "os" in str(e))

try:
    analyze("eval('1+1')")
    check("reject eval", False)
except CodePolicyError:
    check("reject eval", True)

try:
    analyze("x = (lambda: 0).__class__.__base__.__subclasses__()")
    check("reject dunder-escape", False)
except CodePolicyError:
    check("reject dunder-escape", True)

try:
    analyze("import getattr_lib\ngetattr(str, '__g'+'lobals__')")
except CodePolicyError:
    pass  # імпорт не в білому списку — теж ок
try:
    analyze("getattr(str, '__globals__')")
    check("reject dunder-рядок", False)
except CodePolicyError:
    check("reject dunder-рядок", True)

r = analyze("import json\nimport math\ndef on_ui(ctx):\n    return {'data': 1}")
check("accept валідного коду", bool(r.get("hash")))
check("entry_functions", "on_ui" in str(
    entry_functions("def on_ui(ctx):\n    pass")))

# ---------------------------------------------------------------- маніфест
print("== Маніфест ==")
from app.plugins.manifest import ManifestError, validate

base = {"id": "demo", "name": "Демо", "version": "1.0.0",
        "permissions": ["homework:read", "notify:telegram"]}
validate(base)
check("валідний маніфест", True)
try:
    validate({**base, "id": "Bad Slug"})
    check("reject поганий slug", False)
except ManifestError:
    check("reject поганий slug", True)
try:
    validate({**base, "permissions": ["root"]})
    check("reject невідомий дозвіл", False)
except ManifestError:
    check("reject невідомий дозвіл", True)
try:
    validate({**base, "tg_commands": [{"command": "start",
                                       "description": "конфлікт"}]})
    check("reject системна команда?", False, "start не в білому списку словника команд — перевіряється конфліктами")
except ManifestError:
    check("reject невалідної команди", True)

# ---------------------------------------------------------------- санітізер
print("== Сліпий API ==")
from app.plugins.sanitizer import blind_payloads

data = {"items": [{"fio": "Марія Коваленко", "email": "a@b.com",
                   "mark": 11},
                  {"teacher_fio": "Олена Гнатюк", "title": "Алгебра д/з"}]}
blind, red = blind_payloads(42, "demo", {"homework": data})
hw = blind["homework"]["items"]
check("fio → псевдонім", hw[0]["fio"].startswith("#T"))
check("email прибрано", "a@b.com" not in json.dumps(blind))
check("оцінка не зачеплена", hw[0]["mark"] == 11)
back = red.unredact(f"Домашка від {hw[1]['teacher_fio']}!")
check("реверс #T → ім'я", "Олена Гнатюк" in back)

lb, red2 = blind_payloads(42, "demo",
                          {"leader_table": {"rows": [{"fio": "Іван Публічний"}]}})
check("лідерборд: імена публічні",
      lb["leader_table"]["rows"][0]["fio"] == "Іван Публічний")

# ---------------------------------------------------------------- runner
print("== Runner ==")
from app.plugins.runner import run_hook

from app.plugins.store import init_plugin_db
init_plugin_db()

good_code = """
def on_ui(ctx):
    n = int(ctx.get('params', {}).get('n', 1)) * 2
    return {'data': {'result': n}, 'text': 'готово'}
"""
resp = run_hook("smoke", "on_ui", {"params": {"n": 21}}, 0, "test",
                code=good_code)
check("run ok", resp.get("ok"), str(resp.get("error")))
check("результат", (resp.get("result") or {}).get("data") == {"result": 42})

resp = run_hook("smoke", "on_ui", {}, 0, "test",
                code="def on_ui(ctx):\n    raise ValueError('бум')")
check("помилка плагіна ловиться", not resp.get("ok")
      and "ValueError" in str(resp.get("error")))

resp = run_hook("smoke", "on_ui", {}, 0, "test",
                code="def on_ui(ctx):\n    x = 0\n"
                     "    while True:\n        x += 1")
check("таймаут 2с → kill", not resp.get("ok")
      and "timeout" in str(resp.get("error")))

resp = run_hook("smoke", "on_event", {}, 0, "test",
                code="import socket\n")
check("повторна AST-перевірка перед запуском", not resp.get("ok"))

resp = run_hook("smoke", "on_missing", {}, 0, "test", code="x = 1")
check("відсутня функція хука", not resp.get("ok"))

# ---------------------------------------------------------------- пісочниця worker
print("== Worker пісочниця (runtime) ==")
resp = run_hook("smoke", "on_ui", {}, 0, "test", code=(
    "def on_ui(ctx):\n"
    "    import os\n"
    "    return {'data': os.getcwd()}\n"))
check("import os недоступний у worker", not resp.get("ok"))

resp = run_hook("smoke", "on_ui", {}, 0, "test", code=(
    "def on_ui(ctx):\n"
    "    return {'data': __builtins__ is not None}\n"))
check("dunder-доступ у worker заблокований", not resp.get("ok"))

resp = run_hook("smoke", "on_ui", {}, 0, "test", code=(
    "import json\nimport math\n"
    "def on_ui(ctx):\n"
    "    return {'data': math.floor(json.loads('[2.9]')[0])}\n"))
check("білі модулі працюють", resp.get("ok"))

# ---------------------------------------------------------------- ліміти
print("== Ліміти сповіщень ==")
from app.plugins.notify import RateLimitExceeded, check_and_reserve

sent = 0
try:
    for i in range(31):
        check_and_reserve("limplug", 777)
        sent += 1
except RateLimitExceeded:
    pass
check("плагін-ліміт 30/год", sent == 30, f"sent={sent}")

sent = 0
try:
    for i in range(60):
        check_and_reserve(f"p{i}", 888)
        sent += 1
except RateLimitExceeded:
    pass
check("юзер-ліміт 60/год", sent == 60, f"sent={sent}")

print(f"\n{PASS} PASS / {FAIL} FAIL")
raise SystemExit(1 if FAIL else 0)