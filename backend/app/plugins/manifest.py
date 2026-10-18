"""Валідація маніфеста плагіна (manifest.json) + дозволи/секції даних."""
from __future__ import annotations

import re

SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,47}", re.ASCII)
SEMVER_RE = re.compile(r"\d{1,6}\.\d{1,6}\.\d{1,6}", re.ASCII)
CMD_RE = re.compile(r"[a-z][a-z0-9_]{1,31}", re.ASCII)
# системні TG-команди M1 ID — плагіни їх зайняти не можуть
RESERVED_COMMANDS = {"start", "help", "settings", "homework", "marks",
                     "schedule", "leaderboard"}
BTN_ID_RE = re.compile(r"[a-z0-9_]{1,32}", re.ASCII)

# Дозволи (білий список). «Сліпий API»: сирих персональних даних немає.
PERMISSIONS = {
    "homework:read", "marks:read", "schedule:read", "leaderboard:read",
    "balances:read", "shop:read", "news:read", "payments:read",
    "clubs:read", "progress:read", "notify:telegram", "storage",
}

# Секції app_data, які плагін отримує за дозволами (кешовані, sanitized)
SECTIONS_BY_PERM = {
    "homework:read": ["homework"],
    "marks:read": ["stat_marks_year"],
    "schedule:read": ["schedule_week"],
    "leaderboard:read": ["leader_points", "leader_table"],
    "balances:read": ["balances"],
    "shop:read": ["shop_products"],
    "news:read": ["news"],
    "payments:read": ["payment_next", "payment_info"],
    "clubs:read": ["clubs", "club_abonements"],
    "progress:read": ["stat_progress"],
}

MANIFEST_KEYS = {
    "id", "name", "version", "author", "description",
    "permissions", "tg_commands", "tg_buttons", "hooks", "ui",
    "entry", "storage_limit_kb", "min_host_version",
    "settings_schema",
}

KNOWN_HOOKS = {"on_install", "on_uninstall", "on_event", "on_ui",
               "on_command", "on_buttons", "on_daily"}
WIDGETS = {"countdown", "stat", "list", "custom"}


class ManifestError(ValueError):
    pass


def validate(manifest: dict) -> dict:
    """→ повертає маніфест як є (нормалізація дозволів); кидає ManifestError.

    Будь-які неправильні типи (не-рядки, не-об'єкти, нехешовані значення)
    дають ManifestError, а не TypeError/AttributeError (→ 500)."""
    if not isinstance(manifest, dict):
        raise ManifestError("Маніфест має бути JSON-об'єктом")
    for key in ("id", "name", "version"):
        if not manifest.get(key):
            raise ManifestError(f"Відсутнє обов'язкове поле «{key}»")
        if not isinstance(manifest[key], str):
            raise ManifestError(f"{key}: має бути рядком")
    if not SLUG_RE.fullmatch(manifest["id"]):
        raise ManifestError("id: 2–48 символів [a-z0-9-], з літери/цифри")
    if not SEMVER_RE.fullmatch(manifest["version"]):
        raise ManifestError("version: формат semver (1.0.0)")
    if len(manifest["name"]) > 96:
        raise ManifestError("name: довше 96 символів")
    author = manifest.get("author") or ""
    if not isinstance(author, str) or len(author) > 96:
        raise ManifestError("author: рядок до 96 символів")
    desc = manifest.get("description") or ""
    if not isinstance(desc, str):
        raise ManifestError("description: має бути рядком")
    if len(desc) > 200:
        raise ManifestError("description: довше 200 символів")

    perms = manifest.get("permissions") or []
    if (not isinstance(perms, list)
            or any(not isinstance(p, str) or p not in PERMISSIONS
                   for p in perms)
            or len(set(perms)) != len(perms)):
        raise ManifestError(
            "permissions: список унікальних дозволів з: "
            + ", ".join(sorted(PERMISSIONS)))

    commands = manifest.get("tg_commands") or []
    if not isinstance(commands, list) or len(commands) > 5:
        raise ManifestError("tg_commands: максимум 5 команд")
    seen: set[str] = set()
    for c in commands:
        if (not isinstance(c, dict) or not isinstance(c.get("command"), str)
                or not CMD_RE.fullmatch(c["command"])):
            raise ManifestError(
                "tg_commands: команда [a-z][a-z0-9_], 2–32 символи")
        if c["command"] in RESERVED_COMMANDS:
            raise ManifestError(f"Команда /{c['command']} системна M1 ID")
        if (not isinstance(c.get("description"), str)
                or not c["description"] or len(c["description"]) > 64):
            raise ManifestError("tg_commands: description обов'язкове (≤64)")
        if c["command"] in seen:
            raise ManifestError(f"tg_commands: дублікат /{c['command']}")
        seen.add(c["command"])

    buttons = manifest.get("tg_buttons") or []
    if not isinstance(buttons, list) or len(buttons) > 8:
        raise ManifestError("tg_buttons: максимум 8 кнопок")
    seen_b: set[str] = set()
    for b in buttons:
        if not isinstance(b, dict):
            raise ManifestError(
                "tg_buttons: кожна кнопка — об'єкт {id, label}")
        bid = b.get("id")
        if (not isinstance(bid, str) or not BTN_ID_RE.fullmatch(bid)
                or bid in seen_b):
            raise ManifestError(
                "tg_buttons: id [a-z0-9_]{1,32}, унікальний")
        label = b.get("label", "")
        if not isinstance(label, str) or len(label) > 64:
            raise ManifestError("tg_buttons: label — рядок до 64 символів")
        seen_b.add(bid)

    hooks = manifest.get("hooks") or {}
    if not isinstance(hooks, dict):
        raise ManifestError("hooks: об'єкт")
    unknown = set(hooks) - KNOWN_HOOKS
    if unknown:
        raise ManifestError(f"Невідомі hooks: {', '.join(sorted(unknown))}")
    for k, v in hooks.items():
        if not (v is True or v is False or v is None):
            raise ManifestError(f"hooks.{k}: лише true/false")

    ui = manifest.get("ui") or {}
    if not isinstance(ui, dict):
        raise ManifestError("ui: об'єкт")
    if ui.get("entry") and str(ui["entry"]) != "index.html":
        raise ManifestError("ui.entry: лише index.html (один файл)")
    if ui.get("widget") and str(ui["widget"]) not in WIDGETS:
        raise ManifestError("ui.widget: countdown|stat|list|custom")
    if ui.get("widget") == "custom" and not ui.get("entry"):
        raise ManifestError("ui.widget=custom вимагає ui.entry=index.html")

    st_kb = manifest.get("storage_limit_kb", 64)
    if (isinstance(st_kb, bool) or not isinstance(st_kb, int)
            or not (0 < st_kb <= 256)):
        raise ManifestError("storage_limit_kb: ціле число 1..256")

    schema = manifest.get("settings_schema") or []
    if not isinstance(schema, list) or len(schema) > 20:
        raise ManifestError("settings_schema: максимум 20 полів")
    allowed_types = {"text", "number", "boolean", "select", "textarea"}
    for idx, s in enumerate(schema):
        if (not isinstance(s, dict) or not isinstance(s.get("key"), str)
                or not s["key"] or not isinstance(s.get("type"), str)
                or s["type"] not in allowed_types):
            raise ManifestError(
                f"settings_schema[{idx}]: "
                "потрібні key (рядок) та type ("
                f"{'|'.join(sorted(allowed_types))})")

    extra = set(manifest) - MANIFEST_KEYS
    if extra:
        raise ManifestError(
            f"Невідомі поля маніфеста: {', '.join(sorted(extra))}")
    return manifest


def sections_for(perms: list[str], monday_iso: str | None = None) -> list[str]:
    """Секції даних app_data для дозволів плагіна."""
    out: list[str] = []
    for p in perms or []:
        for sec in SECTIONS_BY_PERM.get(p, []):
            if sec == "schedule_week" and monday_iso:
                sec = f"schedule_week@{monday_iso}"
            out.append(sec)
    return out


def check_conflicts(manifest: dict, occupied_commands: set[str]) -> None:
    """TG-команди глобальні: хто перший зайняв — той володіє."""
    for c in manifest.get("tg_commands") or []:
        cmd = str(c["command"])
        if cmd in occupied_commands:
            raise ManifestError(
                f"TG-команда /{cmd} уже зайнята іншим плагіном")
