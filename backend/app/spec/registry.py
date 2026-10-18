"""SpecRegistry — серце spec-driven бекенда M1 ID.

Читає OpenAPI 3.1 специ і будує індекс операцій:
  • перевірка існування маршруту (шаблони шляхів із {param});
  • витяг параметрів шляху ({branch_alias}, {homework_id}, ...);
  • доступ до components.schemas для валідації тіл запитів;
  • статистика/довідник для фронту.

Жоден шлях до MyStat не хардкодиться в коді — лише імена зі специ.
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote

import httpx

from app.core.responses import ApiError

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

# Теги, які в оригіналі не потребують Bearer (див. MYSTAT_API.md §2/§13)
PUBLIC_TAGS = {"Public", "Docs & Info"}


def _safe_segment(key: str, value: object) -> str:
    """Безпечний сегмент шляху: відхиляємо `..`, `/`, бекслеш, `?`, `#`, керуючі
    символи (також у відсотково-закодованому вигляді), решту URL-кодуємо."""
    raw = str(value)
    # декодуємо кілька разів, щоб піймати подвійне кодування (%252e%252e)
    decoded = raw
    for _ in range(3):
        nxt = unquote(decoded)
        if nxt == decoded:
            break
        decoded = nxt
    bad = (not raw or decoded.strip(".") == "" or ".." in decoded
           or any(ch in decoded for ch in "/\\?#")
           or any(ord(ch) < 32 or ord(ch) == 127 for ch in decoded))
    if bad:
        # ApiError (400), а не ValueError: проксі інакше віддав би 500
        raise ApiError(400, "bad_path_param", key, "unsafe_path_parameter")
    return quote(raw, safe="")


@dataclass(frozen=True)
class Operation:
    """Одна операція зі специ."""

    method: str                 # GET / POST / ...
    path_template: str          # /v1/mystat/{branch_alias}/homework/{homework_id}
    operation_id: str           # homework_info_v1_mystat__branch_alias__...
    tag: str                    # Homework
    summary: str
    params: tuple[str, ...]     # ("branch_alias", "homework_id")
    body_schema_ref: str | None # ім'я схеми requestBody, якщо є
    secured: bool               # чи вимагає Authorization

    def concrete_path(self, **params: str) -> str:
        """Підставити значення в шаблон: branch_alias='pl', id=5 → готовий шлях."""
        out = self.path_template
        for key, value in params.items():
            out = out.replace("{" + key + "}", _safe_segment(key, value))
        return out


class SpecRegistry:
    """Індекс операцій OpenAPI-специ."""

    _param_re = re.compile(r"\{([^{}]+)\}")

    def __init__(self) -> None:
        self.raw: dict = {}
        self._ops: dict[tuple[str, str], Operation] = {}
        self._matchers: list[tuple[re.Pattern[str], Operation]] = []
        self.loaded_from: str | None = None
        self.loaded_at: float | None = None

    # ------------------------------------------------------------ завантаження
    def load_url(self, url: str, cache_dir: Path | None = None,
                 timeout: float = 6.0) -> bool:
        """Завантажити специ за URL (майбутній прод-режим SPEC_URL). False — недоступна."""
        try:
            resp = httpx.get(url, timeout=timeout, follow_redirects=True)
            resp.raise_for_status()
            spec = resp.json()
            # валідація (paths тощо) ДО запису кешу: інакше бита відповідь
            # апстріма перезаписав би останню хорошу специ в кеші
            self._install(spec, f"url:{url}")
        except Exception:
            return False
        if cache_dir is not None:
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
                (cache_dir / "openapi.json").write_text(
                    json.dumps(spec, ensure_ascii=False), encoding="utf-8"
                )
            except OSError:
                pass  # кеш — best effort
        return True

    def load_file(self, path: Path) -> None:
        spec = json.loads(Path(path).read_text(encoding="utf-8"))
        self._install(spec, f"file:{path}")

    def load_chain(self, *, spec_url: str | None, cache_dir: Path,
                   primary_file: Path, fallback_files: list[Path]) -> str:
        """Ланцюг надійності з README: URL → свіжий кеш → локальні файли.

        Повертає рядок-джерело, наприклад 'file:C:/.../openapi.json'.
        """
        if spec_url and self.load_url(spec_url, cache_dir):
            return f"url:{spec_url}"

        cached = cache_dir / "openapi.json"
        if cached.exists():
            try:
                self.load_file(cached)
                return f"cache:{cached}"
            except Exception:
                pass  # битий кеш — ідемо далі

        for candidate in [primary_file, *fallback_files]:
            if Path(candidate).exists():
                try:
                    self.load_file(Path(candidate))
                    return f"file:{candidate}"
                except Exception:
                    # битий/некоректний файл не має валити старт застосунку,
                    # якщо поруч є валідний fallback — ідемо по ланцюгу далі
                    continue

        raise RuntimeError(
            "OpenAPI-специ не знайдено: немає SPEC_URL, кешу та локальних файлів"
        )

    # ----------------------------------------------------------- індексація
    def _install(self, spec: dict, source: str) -> None:
        if not isinstance(spec, dict) or "paths" not in spec:
            raise ValueError("Це не OpenAPI-специ (немає paths)")

        # будуємо НОВІ індекси й підмінюємо атомарно: раніше ops/matchers
        # чистилися й перебудовувалися наживо — паралельний match() в
        # цей миг бачив порожній реєстр (транзитні 404 проксі при reload)
        ops: dict[tuple[str, str], Operation] = {}
        matchers: list[tuple[re.Pattern[str], Operation]] = []
        global_security = spec.get("security")

        for path, item in spec["paths"].items():
            for method, op in item.items():
                if method.lower() not in HTTP_METHODS or not isinstance(op, dict):
                    continue
                tags = op.get("tags") or ["-"]
                tag = tags[0]

                explicit_security = op.get("security", global_security)
                if explicit_security is None:
                    secured = tag not in PUBLIC_TAGS   # евристика за тегом
                else:
                    secured = bool(explicit_security)

                body_ref = None
                content = ((op.get("requestBody") or {}).get("content") or {})
                schema = (content.get("application/json") or {}).get("schema") or {}
                if "$ref" in schema:
                    body_ref = schema["$ref"].rsplit("/", 1)[-1]

                operation = Operation(
                    method=method.upper(),
                    path_template=path,
                    operation_id=str(op.get("operationId") or f"{method}_{path}"),
                    tag=tag,
                    summary=str(op.get("summary") or ""),
                    params=tuple(self._param_re.findall(path)),
                    body_schema_ref=body_ref,
                    secured=secured,
                )
                ops[(operation.method, path)] = operation
                matchers.append((self._compile(path), operation))

        # підміна цілком — читачі (match) не застануть «напівпорожній» індекс
        self.raw = spec
        self._ops = ops
        self._matchers = matchers
        self.loaded_from = source
        self.loaded_at = time.time()

    @classmethod
    def _compile(cls, template: str) -> re.Pattern[str]:
        """/v1/mystat/{branch_alias}/hw/{id} → ^/v1/mystat/(?P<branch_alias>[^/]+)/hw/(?P<id>[^/]+)$"""
        parts: list[str] = []
        for segment in template.strip("/").split("/"):
            match = cls._param_re.fullmatch(segment)
            if match:
                parts.append(rf"(?P<{match.group(1)}>[^/]+)")
            else:
                parts.append(re.escape(segment))
        return re.compile("^/" + "/".join(parts) + "$")

    # -------------------------------------------------------------- запити
    def match(self, method: str, concrete_path: str
              ) -> tuple[Operation, dict[str, str]] | None:
        """Знайти операцію за конкретним шляхом. → (операція, параметри шляху)."""
        m = method.upper()
        direct = self._ops.get((m, concrete_path))
        if direct is not None:
            return direct, {}
        for pattern, op in self._matchers:
            if op.method != m:
                continue
            hit = pattern.match(concrete_path)
            if hit:
                return op, hit.groupdict()
        return None

    def schema(self, name: str) -> dict:
        return self.schemas.get(name, {})

    @property
    def schemas(self) -> dict:
        return (self.raw.get("components") or {}).get("schemas") or {}

    def operations(self, tag: str | None = None,
                   q: str | None = None) -> list[Operation]:
        out = list(self._ops.values())
        if tag:
            out = [o for o in out if o.tag == tag]
        if q:
            needle = q.lower()
            out = [
                o for o in out
                if needle in o.operation_id.lower()
                or needle in o.path_template.lower()
            ]
        return sorted(out, key=lambda o: (o.tag, o.path_template, o.method))

    def stats(self) -> dict:
        by_tag = Counter(o.tag for o in self._ops.values())
        info = self.raw.get("info") or {}
        return {
            "openapi": self.raw.get("openapi"),
            "title": info.get("title"),
            "version": info.get("version"),
            "paths": len({template for _, template in self._ops}),
            "operations": len(self._ops),
            "schemas": len(self.schemas),
            "tags": len(by_tag),
            "by_tag": dict(sorted(by_tag.items(), key=lambda kv: -kv[1])),
            "loaded_from": self.loaded_from,
            "loaded_at": self.loaded_at,
        }
