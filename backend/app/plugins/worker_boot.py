"""Worker плагіна: одноразовий процес, який виконує ОДИН хук.

Запуск: python -I worker_boot.py   (stdin = JSON-запит)
Запит:  {"code": "...plugin.py...", "hook": "on_event",
         "args": {"event": "...", "payload": {...}, "settings": {...},
                  "storage": {...}, "params": {...}}}
Відповідь (stdout): "===PLUGIN_RESULT===\n{json}"

Другий шар безпеки (після AST-аналізатора):
  • урізані __builtins__ (без open/eval/файлових функцій);
  • власний __import__: плагін отримує НЕ реальні модулі, а безпечні
    обгортки з явним білим списком імен (random._os, collections._sys,
    json.codecs тощо недосяжні взагалі);
  • getattr/hasattr блокують усі імена, що починаються з «_», а також
    фрейм/код-атрибути (gi_frame, f_back, f_globals, co_*, ...) і
    format/format_map (обхід атрибутів через рядок-шаблон);
  • print заглушений — stdout належить протоколу хоста;
  • розмір відповіді обмежений.
"""
from __future__ import annotations

import json
import re
import sys
import types

def _apply_limits() -> None:
    """LOW/H4-пом'якшення: на POSIX обмежуємо пам'ять і CPU воркера
    (на Windows setrlimit не існує — там Job Object виставляє runner.py)."""
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,
                                                 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    except Exception:  # Windows / resource недоступний / ліміт не застосувався
        pass


def _load_analyzer():
    """Завантажити analyzer.py за шляхом (воркер працює з -I, пакет app
    недосяжний): другий, незалежний від хоста, прогін AST-перевірки."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().with_name("analyzer.py")
    spec = importlib.util.spec_from_file_location("_plugin_analyzer", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_plugin_analyzer"] = mod
    spec.loader.exec_module(mod)
    return mod


MAX_OUTPUT_BYTES = 256 * 1024

# Явні білі списки публічних імен. None = усі публічні імена (модуль
# повністю на C і не містить посилань на os/sys).
_SAFE_API: dict[str, tuple[str, ...] | None] = {
    "json": ("dumps", "loads", "JSONDecodeError"),
    "math": None,
    "itertools": None,
    "random": ("random", "randint", "randrange", "choice", "choices",
               "shuffle", "sample", "uniform", "gauss", "triangular",
               "betavariate", "expovariate", "normalvariate", "seed",
               "getrandbits", "randbytes", "Random"),
    "re": ("compile", "match", "search", "fullmatch", "sub", "subn",
           "split", "findall", "finditer", "escape", "error", "Pattern",
           "Match", "IGNORECASE", "I", "MULTILINE", "M", "DOTALL", "S",
           "VERBOSE", "X", "ASCII", "A", "UNICODE", "U"),
    "datetime": ("datetime", "date", "time", "timedelta", "timezone",
                 "tzinfo", "MINYEAR", "MAXYEAR", "UTC"),
    "textwrap": ("wrap", "fill", "shorten", "dedent", "indent",
                 "TextWrapper"),
    "statistics": ("mean", "fmean", "geometric_mean", "harmonic_mean",
                   "median", "median_low", "median_high", "median_grouped",
                   "mode", "multimode", "pstdev", "pvariance", "stdev",
                   "variance", "quantiles", "correlation", "covariance",
                   "linear_regression", "StatisticsError", "NormalDist"),
    "string": ("ascii_letters", "ascii_lowercase", "ascii_uppercase",
               "digits", "hexdigits", "octdigits", "punctuation",
               "printable", "whitespace", "capwords", "Template"),
    "collections": ("deque", "defaultdict", "OrderedDict", "Counter",
                    "ChainMap", "namedtuple"),
    "functools": ("reduce", "partial", "wraps", "lru_cache", "cache",
                  "cmp_to_key", "total_ordering"),
    "html": ("escape",),  # екранування для Telegram HTML
}
ALLOWED_MODULES = set(_SAFE_API)

# Заборонені імена атрибутів (дублює analyzer.py — тут це runtime-шар).
_DENIED_ATTRS = {
    "mro", "format", "format_map", "vformat", "get_field", "get_value",
    "check_unused_args", "gi_frame", "gi_code", "gi_yieldfrom", "cr_frame",
    "cr_code", "cr_await", "cr_origin", "ag_frame", "ag_code", "ag_await",
    "tb_frame", "tb_next",
}
_FRAME_ATTR_RE = re.compile(r"^(?:co|f|gi|cr|ag|tb)_")


def _attr_denied(name) -> bool:
    return (isinstance(name, str)
            and (name.startswith("_") or name in _DENIED_ATTRS
                 or bool(_FRAME_ATTR_RE.match(name))))


def _build_safe_modules() -> dict:
    """Реальні модулі → безпечні SimpleNamespace-обгортки."""
    import importlib

    out: dict = {}
    for mod_name, names in _SAFE_API.items():
        try:
            real = importlib.import_module(mod_name)
        except Exception:  # модуль недоступний у цьому інтерпретаторі
            continue
        ns = types.SimpleNamespace()
        if names is None:
            names = tuple(n for n in dir(real) if not n.startswith("_"))
        for n in names:
            if not hasattr(real, n):
                continue
            val = getattr(real, n)
            if isinstance(val, types.ModuleType):
                continue  # ніяких вкладених модулів
            setattr(ns, n, val)
        out[mod_name] = ns
    return out


_SAFE_MODULES = _build_safe_modules()


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level != 0 or str(name) not in _SAFE_MODULES:
        raise ImportError(f"Модуль «{name}» заборонений у пісочниці плагінів")
    return _SAFE_MODULES[str(name)]


def _no_print(*_a, **_k) -> None:
    """stdout — протокол хоста; print плагіна нічого не ламає."""


def _safe_getattr(obj, name, *default):
    """getattr без «_»-імен і небезпечних атрибутів: закриває escape через
    складання імен у рантаймі (getattr(x, '_' * 2 + 'class__'), join тощо)
    незалежно від того, як плагін зібрав рядок."""
    if not isinstance(name, str):
        raise TypeError("attribute name must be string")
    if _attr_denied(name):
        raise AttributeError(
            f"Доступ до «{name}» заборонений у пісочниці плагінів")
    if default:
        return getattr(obj, name, default[0])
    return getattr(obj, name)


def _safe_hasattr(obj, name) -> bool:
    if not isinstance(name, str) or _attr_denied(name):
        return False
    return hasattr(obj, name)


SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "bool": bool, "bytes": bytes,
    "dict": dict, "enumerate": enumerate, "filter": filter, "float": float,
    "frozenset": frozenset, "int": int, "len": len, "list": list, "map": map,
    "max": max, "min": min, "range": range, "repr": repr, "round": round,
    "set": set, "sorted": sorted, "str": str, "sum": sum, "tuple": tuple,
    "zip": zip,
    "isinstance": isinstance, "issubclass": issubclass,
    "getattr": _safe_getattr, "hasattr": _safe_hasattr, "hash": hash, "id": id,
    "__import__": _safe_import,
    "print": _no_print,
    # винятки: плагіни ловлять помилки input-даних (json.loads тощо)
    "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
    "KeyError": KeyError, "IndexError": IndexError,
    "AttributeError": AttributeError, "RuntimeError": RuntimeError,
    "ZeroDivisionError": ZeroDivisionError, "StopIteration": StopIteration,
    "ArithmeticError": ArithmeticError, "LookupError": LookupError,
    "OverflowError": OverflowError, "RecursionError": RecursionError,
}

# Значення за замовчуванням, щоб плагіни не падали на відсутньому ключі
# (кнопки TG не передають payload, команди — params тощо).
_CTX_DEFAULTS = {"event": "", "payload": {}, "params": {}, "settings": {},
                 "storage": {}, "args_text": "", "button": ""}


class _Ctx:
    """Контекст виконання: доступ через атрибути (ctx.payload) або
    ctx.get('payload', default)."""

    def __init__(self, data: dict) -> None:
        merged = {**_CTX_DEFAULTS, **{str(k): v for k, v in data.items()}}
        object.__setattr__(self, "_data", merged)
        for key, val in merged.items():
            if not key.startswith("_"):
                object.__setattr__(self, key, val)

    def get(self, key, default=None):
        # читаємо зі словника, а не getattr: ctx.get('__class__') не діє
        return self._data.get(key, default)


def _emit(obj: dict) -> None:
    try:
        raw = json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raw = json.dumps({"ok": False,
                          "error": f"результат не серіалізується: {exc}"})
    if len(raw.encode("utf-8", "replace")) > MAX_OUTPUT_BYTES:
        raw = json.dumps({"ok": False, "error": "результат плагіна "
                          f"більший за {MAX_OUTPUT_BYTES // 1024}КБ"})
    sys.stdout.write("\n===PLUGIN_RESULT===\n")
    sys.stdout.write(raw)
    sys.stdout.flush()


def _main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        req = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except ValueError as exc:
        _emit({"ok": False, "error": f"bad request json: {exc}"})
        return 2

    _apply_limits()
    code = req.get("code") or ""
    hook = str(req.get("hook") or "")
    args = req.get("args") or {}

    # defense in depth: воркер сам ще раз перевіряє код політикою AST
    try:
        _load_analyzer().analyze(code)
    except Exception as exc:  # CodePolicyError або збій завантаження
        _emit({"ok": False, "error": f"code policy: {exc}"})
        return 1

    namespace = {"__builtins__": SAFE_BUILTINS, "__name__": "plugin"}
    try:
        exec(compile(code, "<plugin>", "exec"), namespace)  # noqa: S102
    except BaseException as exc:
        _emit({"ok": False,
               "error": f"load error: {type(exc).__name__}: {exc}"})
        return 1

    fn = namespace.get(hook)
    if not callable(fn):
        _emit({"ok": False, "error": f"функція «{hook}» відсутня в plugin.py"})
        return 1

    try:
        result = fn(_Ctx(args))
    except BaseException as exc:
        _emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return 1

    if not isinstance(result, dict):
        result = {"data": result}
    _emit({"ok": True, "result": result})
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
