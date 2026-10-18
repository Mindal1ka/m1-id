"""Зонд параметрів OpenAPI для вибору задач Sync Engine (M2)."""
import json, sys
from pathlib import Path

spec = json.loads((Path(__file__).resolve().parents[1] / "openapi_snapshot" / "openapi.json").read_text(encoding="utf-8"))
needles = sys.argv[1:] or ["config", "page-counters", "get-balances",
                           "get-month", "homework/list", "statistic/", "news",
                           "payment/get-hist", "nutrition/get-menu", "awards"]

for path, item in sorted(spec["paths"].items()):
    if not any(n in path for n in needles):
        continue
    for method, op in item.items():
        if method.lower() not in {"get", "post"}:
            continue
        params = []
        for p in op.get("parameters", []):
            req = "*" if p.get("required") else ""
            sch = p.get("schema", {})
            extra = ""
            if "enum" in sch:
                extra = " enum=" + "|".join(map(str, sch["enum"][:6]))
            elif "default" in sch:
                extra = f" default={sch['default']}"
            params.append(f"{p.get('name')}{req}:{sch.get('type','?')}{extra}")
        body = ""
        rb = (op.get("requestBody") or {}).get("content", {}).get("application/json", {})
        if "$ref" in rb.get("schema", {}):
            body = " body=" + rb["schema"]["$ref"].rsplit("/", 1)[-1]
        print(f"{method.upper():4} {path}")
        if params:
            print(f"      {' | '.join(params)}")
        if body:
            print(f"     {body}")
