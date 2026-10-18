"""AST-аналізатор коду плагіна: відхилення на аплоаді.

Блокуємо:
  • import/from — все, крім білого списку (модулі без доступу до системи),
    без крапок у шляху, без відносних імпортів і імен, що починаються з «_»;
  • eval/exec/compile/__import__/globals/locals/vars/input/open;
  • ВСІ атрибути, що починаються з «_» (random._os, collections._sys,
    __class__, __globals__ ...) — класичний escape в Python-пісочниці;
  • фрейм/код-атрибути (gi_frame, f_back, f_globals, co_*, tb_*...),
    mro та format/format_map/vformat (обхід атрибутів через рядок-шаблон:
    "{0.__class__}".format(x));
  • dunder-рядки в літералах і у статично згорнутих виразах
    (+, *, %, f-рядки, join);
  • parser-бомби: ліміт розміру, глибини AST і кількості вузлів.

Справжній захист — подвійний: тут (AST) і в worker_boot.py (безпечні
обгортки модулів + runtime-getattr з тими самими правилами).
"""
from __future__ import annotations

import ast
import hashlib
import re

MAX_CODE_BYTES = 64 * 1024
MAX_AST_DEPTH = 50
MAX_AST_NODES = 50_000

# Має збігатися з ключами _SAFE_API у worker_boot.py (перевіряє smoke-тест).
ALLOWED_MODULES = {
    "json", "math", "random", "re", "datetime", "textwrap", "statistics",
    "string", "itertools", "collections", "functools", "html",
}

BANNED_CALLS = {
    "eval", "exec", "compile", "globals", "locals", "vars", "input",
    "open", "__import__", "breakpoint", "help", "exit", "quit",
}

DUNDER_STRING_RE = re.compile(r"__\w+__")
# Дублює worker_boot._DENIED_ATTRS / _FRAME_ATTR_RE (runtime-шар).
DENIED_ATTRS = {
    "mro", "format", "format_map", "vformat", "get_field", "get_value",
    "check_unused_args", "gi_frame", "gi_code", "gi_yieldfrom", "cr_frame",
    "cr_code", "cr_await", "cr_origin", "ag_frame", "ag_code", "ag_await",
    "tb_frame", "tb_next",
}
FRAME_ATTR_RE = re.compile(r"^(?:co|f|gi|cr|ag|tb)_")
MAX_FOLD_LEN = 4096


class CodePolicyError(ValueError):
    pass


def attr_denied(name: str) -> bool:
    return (name.startswith("_") or name in DENIED_ATTRS
            or bool(FRAME_ATTR_RE.match(name)))


def _fold_str(node: ast.AST, depth: int = 0):
    """Статично фолдити сталі вирази → str | int | tuple | None."""
    if depth > 12:
        return None
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (str, int)) \
                and not isinstance(node.value, bool):
            return node.value
        return None
    if isinstance(node, (ast.Tuple, ast.List)):
        items = [_fold_str(e, depth + 1) for e in node.elts]
        return tuple(items) if all(i is not None for i in items) else None
    if isinstance(node, ast.BinOp):
        left = _fold_str(node.left, depth + 1)
        right = _fold_str(node.right, depth + 1)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Add) and isinstance(left, str) \
                and isinstance(right, str):
            return (left + right)[:MAX_FOLD_LEN]
        if isinstance(node.op, ast.Mult):
            if isinstance(left, int) and isinstance(right, str):
                left, right = right, left
            if isinstance(left, str) and isinstance(right, int):
                return (left * max(0, min(right, MAX_FOLD_LEN)))[:MAX_FOLD_LEN]
        if isinstance(node.op, ast.Mod) and isinstance(left, str):
            try:
                args = right if isinstance(right, tuple) else (right,)
                return (left % args)[:MAX_FOLD_LEN]
            except (TypeError, ValueError):
                return None
        return None
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            elif isinstance(v, ast.FormattedValue) and v.conversion == -1 \
                    and v.format_spec is None:
                inner = _fold_str(v.value, depth + 1)
                if not isinstance(inner, (str, int)):
                    return None
                parts.append(str(inner))
            else:
                return None
        return "".join(parts)[:MAX_FOLD_LEN]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "join" and len(node.args) == 1 \
            and not node.keywords:
        sep = _fold_str(node.func.value, depth + 1)
        seq = _fold_str(node.args[0], depth + 1)
        if isinstance(sep, str) and isinstance(seq, tuple) \
                and all(isinstance(i, str) for i in seq):
            return sep.join(seq)[:MAX_FOLD_LEN]
    return None


class _Checker(ast.NodeVisitor):
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.nodes = 0
        self.depth = 0
        self.max_depth = 0

    def generic_visit(self, node: ast.AST) -> None:
        self.nodes += 1
        if self.nodes > MAX_AST_NODES:
            raise CodePolicyError("Код занадто великий (parser-bomb guard)")
        self.depth += 1
        self.max_depth = max(self.max_depth, self.depth)
        try:
            super().generic_visit(node)
        finally:
            self.depth -= 1

    # --- import ---
    def _check_module(self, name: str, shown: str) -> None:
        if "." in name or name not in ALLOWED_MODULES:
            self.errors.append(
                f"Імпорт заборонений: {shown} "
                f"(дозволені: {', '.join(sorted(ALLOWED_MODULES))})")

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._check_module(alias.name, alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            self.errors.append("Відносні імпорти заборонені")
        else:
            self._check_module(node.module or "", f"from {node.module} ...")
        for alias in node.names:
            if alias.name != "*" and attr_denied(alias.name):
                self.errors.append(
                    f"Імпорт приватного імені заборонений: {alias.name}")
        self.generic_visit(node)

    # --- заборонені виклики ---
    def visit_Call(self, node: ast.Call) -> None:
        fn = node.func
        name = None
        if isinstance(fn, ast.Name):
            name = fn.id
        elif isinstance(fn, ast.Attribute):
            name = fn.attr
        if name in BANNED_CALLS:
            self.errors.append(f"Виклик заборонений: {name}()")
        if name == "join":
            self._check_folded(node)
        self.generic_visit(node)

    # --- імена: __builtins__, __import__, __class__ ... ---
    def visit_Name(self, node: ast.Name) -> None:
        if node.id.startswith("__"):
            self.errors.append(f"Ім'я {node.id} заборонене (dunder)")
        self.generic_visit(node)

    # --- атрибути: усе приватне («_...») та небезпечне ---
    def visit_Attribute(self, node: ast.Attribute) -> None:
        if attr_denied(node.attr):
            self.errors.append(
                f"Доступ до .{node.attr} заборонений (sandbox-escape)")
        self.generic_visit(node)

    # case Foo(_x=1) теж робить getattr(subject, "_x")
    def visit_MatchClass(self, node: ast.MatchClass) -> None:
        for attr in node.kwd_attrs:
            if attr_denied(attr):
                self.errors.append(
                    f"Доступ до .{attr} заборонений (match-pattern)")
        self.generic_visit(node)

    # --- dunder-рядки в літералах ---
    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and DUNDER_STRING_RE.search(node.value):
            self.errors.append(
                f"Рядок з dunder-іменем заборонений: {node.value!r}")
        self.generic_visit(node)

    # --- dunder, зібраний виразом: "_"*2+"class"+"__", "%s__" % "x",
    # f-рядок, "".join([...]). Складаємо сталі й перевіряємо результат.
    # Це лише додатковий шар: справжній захист — заборона «_»-атрибутів
    # в AST і в runtime-getattr воркера.
    def _check_folded(self, node: ast.AST) -> None:
        folded = _fold_str(node)
        if isinstance(folded, str) and DUNDER_STRING_RE.search(folded):
            self.errors.append(
                f"Вираз зі збіркою dunder-імені заборонений: {folded!r}")

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if isinstance(node.op, (ast.Add, ast.Mult, ast.Mod)):
            self._check_folded(node)
        self.generic_visit(node)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        self._check_folded(node)
        self.generic_visit(node)


def analyze(code: str) -> dict:
    """→ {'hash': sha256, 'nodes': n} або кидає CodePolicyError з причиною."""
    raw = code.encode("utf-8")
    if len(raw) > MAX_CODE_BYTES:
        raise CodePolicyError(
            f"Код більший за {MAX_CODE_BYTES // 1024}КБ")
    if raw.startswith(b"\xef\xbb\xbf"):
        code = code.lstrip("﻿")
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise CodePolicyError(f"Синтаксична помилка: {exc}") from None
    except (RecursionError, MemoryError, ValueError):
        raise CodePolicyError("Код не вдалося розібрати (надто складний)")

    checker = _Checker()
    try:
        checker.visit(tree)
    except CodePolicyError:
        raise
    except RecursionError:
        raise CodePolicyError("Глибина вкладеності коду надмірна")
    if checker.max_depth > MAX_AST_DEPTH:
        raise CodePolicyError("Занадто глибока вкладеність (>50)")
    if checker.errors:
        raise CodePolicyError(
            "Використання системних можливостей заборонено: "
            + "; ".join(checker.errors[:5]))
    return {"hash": hashlib.sha256(raw).hexdigest(), "nodes": checker.nodes}


def entry_functions(code: str) -> set[str]:
    """Топ-рівневі def у коді плагіна (для перевірки наявності хуків)."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, RecursionError, MemoryError, ValueError):
        return set()
    return {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
