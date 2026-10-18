"""API плагінів: маркетплейс, інсталяція, налаштування, логи, UI.

Усі ендпоінти під JWT. Верифікація — тільки адмін (конфіг: M1ID_ADMIN_USER_IDS
та/або M1ID_ADMIN_USERNAMES; неявного «user_id == 1» немає).
"""
from __future__ import annotations

import base64
import hmac
import io
import json
import zipfile

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy import select

from app.core.responses import ApiError
from app.deps import get_current_user
from app.db.models import User
from app.plugins import manifest as mf
from app.plugins import service
from app.plugins.access import is_admin_user, is_admin_user_id, may_run
from app.plugins.analyzer import CodePolicyError, analyze
from app.plugins.store import (
    PluginFile, PluginInstall, PluginMeta, PluginRun, TgButton, TgCommand,
    new_session,
)

router = APIRouter(prefix="/api/plugins", tags=["plugins"])

ALLOWED_UPLOAD_EXT = {".py", ".html", ".json", ".md", ".png", ".txt"}
# лише ці розширення можуть бути бінарними (base64); код і маніфест — тільки UTF-8
BINARY_EXT = {".png"}
MAX_ZIP_BYTES = 512 * 1024
MAX_FILES = 20


def _is_admin(user: User) -> bool:
    return is_admin_user(user)


def _is_admin_by_id(user_id: int) -> bool:
    return is_admin_user_id(user_id)


def _meta_or_404(db, plugin_id: str) -> PluginMeta:
    meta = db.get(PluginMeta, plugin_id)
    if meta is None:
        raise ApiError(404, "plugin_not_found", "__all__")
    return meta


def _norm_visibility(raw: str | None) -> str:
    v = str(raw or "public").lower()
    return v if v in ("public", "link", "private") else "public"


def _is_owner_or_admin(meta: PluginMeta, user: User) -> bool:
    return meta.uploaded_by == user.id or _is_admin(user)


def _visible_or_404(db, meta: PluginMeta, user: User,
                    token: str | None = None) -> PluginMeta:
    """N-M3: приватні плагіни недоступні через /install та /source
    для чужих користувачів — 404 (не 403, щоб не розкривати існування).
    Адмін і власник (uploaded_by) мають доступ завжди.

    visibility=link: потрібен share-токен (порівняння сталого часу) —
    або юзер уже має інсталяцію (повторне відкриття вкладки)."""
    vis = meta.visibility or "public"
    if vis == "public" or _is_owner_or_admin(meta, user):
        return meta
    if vis == "link":
        expected = meta.share_token or ""
        if token and expected and hmac.compare_digest(
                str(token).encode("utf-8"), expected.encode("utf-8")):
            return meta
        has_install = (db.query(PluginInstall)
                       .filter_by(user_id=user.id, plugin_id=meta.id)
                       .first() is not None)
        if has_install:
            return meta
    raise ApiError(404, "plugin_not_found", "__all__")


def _plugin_out(db, meta: PluginMeta, user_id: int | None) -> dict:
    inst = None
    if user_id is not None:
        inst = (db.query(PluginInstall)
                .filter_by(user_id=user_id, plugin_id=meta.id).first())
    manifest = meta.manifest or {}
    out = {
        "id": meta.id,
        "name": meta.name,
        "version": meta.version,
        "author": meta.author,
        "description": meta.description,
        "verified": meta.verified,
        "visibility": meta.visibility or "public",
        # H6: share_token НЕ віддаємо у списках/чужим — лише адміну
        # та автору аплоаду (нижче, разом зі stats)
        "permissions": manifest.get("permissions") or [],
        "tg_commands": manifest.get("tg_commands") or [],
        "hooks": manifest.get("hooks") or {},
        "ui": manifest.get("ui") or {},
        "settings_schema": manifest.get("settings_schema") or [],
        "installed": bool(inst),
        "enabled": bool(inst and inst.enabled),
        # дозволи змінились після згоди юзера -> потрібно прийняти знову
        "needs_reaccept": bool(inst) and sorted(
            inst.accepted_permissions or []) != sorted(
            manifest.get("permissions") or []),
        "settings": (inst.settings if inst else None) or {},
        "account_seqs": (inst.account_seqs if inst else None) or [],
        "code_hash": meta.code_hash,
    }
    # адмін/автор бачить статистику і володіння
    is_admin = user_id is not None and _is_admin_by_id(user_id)
    out["is_admin"] = is_admin
    if user_id is not None and (is_admin or meta.uploaded_by == user_id):
        # H6: share-токен — тільки адмін/автор
        out["share_token"] = meta.share_token or ""
        out["stats"] = {
            "installs": db.query(PluginInstall)
                          .filter_by(plugin_id=meta.id).count(),
            "runs": db.query(PluginRun)
                      .filter_by(plugin_id=meta.id).count(),
        }
        out["can_admin"] = True
    return out


# ---------------------------------------------------------------- список

@router.get("")
async def list_plugins(user: User = Depends(get_current_user)):
    db = new_session()
    try:
        metas = db.query(PluginMeta).order_by(PluginMeta.name).all()
        installed_ids = {r.plugin_id for r in db.query(PluginInstall)
                         .filter_by(user_id=user.id).all()}
        admin = _is_admin(user)
        # public - усім; link/private - лише автору, адміну або (для link)
        # тому, хто вже встановив: link-плагіни не світяться у каталозі
        visible = [m for m in metas
                   if (m.visibility or "public") == "public"
                   or m.uploaded_by == user.id or admin
                   or ((m.visibility or "public") == "link"
                       and m.id in installed_ids)]
        return {"ok": True, "data": [_plugin_out(db, m, user.id)
                                     for m in visible]}
    finally:
        db.close()


# ---------------------------------------------------------------- аплоад

def _register_tg(db, manifest: dict, plugin_id: str) -> None:
    for c in manifest.get("tg_commands") or []:
        db.merge(TgCommand(command=str(c["command"]), plugin_id=plugin_id,
                           description=str(c.get("description") or "")))
    for b in manifest.get("tg_buttons") or []:
        db.merge(TgButton(plugin_id=plugin_id, button_id=str(b["id"]),
                          label=str(b.get("label") or "")))


def _unregister_tg(db, plugin_id: str) -> None:
    db.query(TgCommand).filter(TgCommand.plugin_id == plugin_id) \
        .delete(synchronize_session=False)
    db.query(TgButton).filter(TgButton.plugin_id == plugin_id) \
        .delete(synchronize_session=False)


def _store_plugin(db, manifest: dict, files: dict[str, str],
                  user_id: int, verified: bool,
                  visibility: str = "public",
                  binary: frozenset[str] | set[str] = frozenset(),
                  is_admin: bool = False) -> PluginMeta:
    """Запис у БД: AST-перевірка коду, конфлікти TG-команд, версіонування.

    Повторний аплоад існуючого id - лише власник (meta.uploaded_by) або
    адмін. Після нього: verified знімається (крім адміна), а всі
    інсталяції вимикаються й вимагають повторної згоди на дозволи."""
    code = files.get("plugin.py")
    code_hash = ""
    if code:
        try:
            code_hash = analyze(code)["hash"]
        except CodePolicyError as exc:
            raise ApiError(422, "code_policy", "__all__", str(exc))
    occupied = {c.command for c in db.query(TgCommand).all()
                if c.plugin_id != manifest["id"]}
    try:
        mf.check_conflicts(manifest, occupied)
    except mf.ManifestError as exc:
        raise ApiError(422, "command_conflict", "__all__", str(exc))

    meta = db.get(PluginMeta, manifest["id"])
    if meta is not None:
        if not (is_admin or meta.uploaded_by == user_id):
            # чужий id: не розкриваємо подробиць, лише відмова
            raise ApiError(403, "not_plugin_owner", "__all__",
                           "Цей id плагіна належить іншому автору")
        # ре-аплоад: version мусить зрости, verified злітає (код змінився)
        old = [int(x) for x in (meta.version or "0.0.0").split(".")]
        new = [int(x) for x in manifest["version"].split(".")]
        if new <= old:
            raise ApiError(422, "version_not_bumped", "__all__",
                           "version мусить зрости при повторному аплоаді")
        for f in db.query(PluginFile).filter_by(plugin_id=meta.id):
            db.delete(f)
        # нова версія/дозволи: усі інсталяції вимикаються, дозволи треба
        # прийняти знову (інакше код/права змінились би без відома юзера)
        for inst in db.query(PluginInstall).filter_by(plugin_id=meta.id):
            inst.enabled = False
            inst.accepted_permissions = []
        _unregister_tg(db, meta.id)  # прибрати команди/кнопки, яких більше нема
        owner_id = meta.uploaded_by
    else:
        meta = PluginMeta(id=manifest["id"])
        db.add(meta)
        owner_id = user_id
    meta.name = manifest["name"]
    meta.version = manifest["version"]
    meta.author = str(manifest.get("author") or "")
    meta.description = str(manifest.get("description") or "")
    meta.manifest = manifest
    meta.code_hash = code_hash
    meta.uploaded_by = owner_id
    meta.verified = bool(verified)
    meta.visibility = _norm_visibility(visibility)
    if meta.visibility != "link":
        meta.share_token = ""
    db.flush()
    for path, content in files.items():
        db.merge(PluginFile(plugin_id=meta.id, path=path, content=content,
                            encoding="base64" if path in binary else "utf-8"))
    _register_tg(db, manifest, meta.id)
    return meta


def _check_files(files: dict[str, str],
                 binary: set[str] | frozenset[str] = frozenset()) -> None:
    if not files:
        raise ApiError(422, "no_files", "__all__", "Потрібен хоча б один файл")
    if len(files) > MAX_FILES:
        raise ApiError(422, "too_many_files", "__all__",
                       f"Максимум {MAX_FILES} файлів")
    if sum(len(v) for v in files.values()) > MAX_ZIP_BYTES:
        raise ApiError(422, "too_large", "__all__", "Плагін більший за 512КБ")
    for path in files:
        if (not path or len(path) > 128 or "/" in path or "\\" in path
                or path.startswith(".") or any(ord(ch) < 32 for ch in path)):
            raise ApiError(422, "bad_path", "__all__",
                           f"Підпапки у плагіні заборонені: {path}")
        ext = "." + path.rsplit(".", 1)[-1].lower()
        if ext not in ALLOWED_UPLOAD_EXT:
            raise ApiError(422, "bad_ext", "__all__",
                           f"Розширення «{path}» заборонене")
        if path in binary and ext not in BINARY_EXT:
            raise ApiError(422, "bad_encoding", "__all__",
                           f"«{path}» має бути текстом UTF-8")


def _validated_manifest(raw: bytes | str) -> dict:
    try:
        manifest = json.loads(raw if isinstance(raw, str)
                              else raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise ApiError(422, "manifest_invalid", "__all__",
                       "manifest.json — не валідний JSON")
    try:
        mf.validate(manifest)
    except mf.ManifestError as exc:
        raise ApiError(422, "manifest_invalid", "__all__", str(exc))
    return manifest


async def _read_json_body(request: Request) -> dict:
    """Тіло JSON з жорстким лімітом: розмір перевіряється ДО парсингу.
    (FastAPI-параметр `payload: dict` парсив би тіло без ліміту.)"""
    cl = request.headers.get("content-length")
    if cl and (cl.isascii() and cl.isdigit()) and int(cl) > MAX_ZIP_BYTES:
        raise ApiError(413, "too_large", "__all__",
                       "Тіло запиту більше за 512КБ")
    chunks: list[bytes] = []
    total = 0
    # chunked/без Content-Length: основний захист - читання потоку з лімітом
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_ZIP_BYTES:
            raise ApiError(413, "too_large", "__all__",
                           "Тіло запиту більше за 512КБ")
        chunks.append(chunk)
    try:
        payload = json.loads(b"".join(chunks))
    except (ValueError, RecursionError):
        raise ApiError(422, "bad_json", "__all__",
                       "Тіло запиту — не валідний JSON")
    if not isinstance(payload, dict):
        raise ApiError(422, "bad_json", "__all__",
                       "Тіло запиту має бути JSON-об'єктом")
    return payload


def _upload_result(meta: PluginMeta) -> dict:
    return {"ok": True, "data": {"id": meta.id,
                                 "verified": meta.verified,
                                 "visibility": meta.visibility,
                                 "share_token": meta.share_token}}


@router.post("")
async def upload_plugin(request: Request,
                        user: User = Depends(get_current_user)):
    """JSON-аплоад: {manifest: {...}, files: {'plugin.py': '...'}}."""
    payload = await _read_json_body(request)
    manifest = payload.get("manifest")
    files = payload.get("files")
    if not isinstance(manifest, dict):
        raise ApiError(422, "manifest_invalid", "__all__",
                       "manifest має бути JSON-об'єктом")
    if not isinstance(files, dict) or any(
            not isinstance(k, str) or not isinstance(v, str)
            for k, v in files.items()):
        raise ApiError(422, "no_files", "__all__",
                       "files: об'єкт {ім'я: текст}")
    visibility = _norm_visibility(payload.get("visibility"))
    _check_files(files)
    try:
        mf.validate(manifest)
    except mf.ManifestError as exc:
        raise ApiError(422, "manifest_invalid", "__all__", str(exc))
    db = new_session()
    try:
        admin = _is_admin(user)
        meta = _store_plugin(db, manifest, files, user.id, verified=admin,
                             visibility=visibility, is_admin=admin)
        db.commit()
        return _upload_result(meta)
    finally:
        db.close()


@router.post("/upload-zip")
async def upload_zip(file: UploadFile = File(...),
                     visibility: str = Form("public"),
                     user: User = Depends(get_current_user)):
    """Аплоад zip (маркетплейс): manifest.json + plugin.py + index.html..."""
    raw = await file.read(MAX_ZIP_BYTES + 1)
    if len(raw) > MAX_ZIP_BYTES:
        raise ApiError(422, "too_large", "__all__", "zip більший за 512КБ")
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise ApiError(422, "bad_zip", "__all__")
    names = [n for n in zf.namelist()
             if not n.endswith("/") and not n.startswith("__MACOSX")]
    if len(names) > MAX_FILES:
        raise ApiError(422, "too_many_files", "__all__")
    files: dict[str, str] = {}
    binary: set[str] = set()
    manifest_raw: bytes | None = None
    for name in names:
        info = zf.getinfo(name)
        # B1: bomb-захист — ліміт на РОЗПАКОВАНИЙ розмір кожного файла
        # (перевірений лише розмір zip — недостатньо)
        if info.file_size > MAX_ZIP_BYTES:
            raise ApiError(422, "file_too_large", "__all__",
                           f"«{name}» більший за 512КБ у розпакованому вигляді")
        base = name.rsplit("/", 1)[-1]
        if not base or "\\" in base or base.startswith("."):
            raise ApiError(422, "bad_path", "__all__", name)
        ext = "." + base.rsplit(".", 1)[-1].lower()
        if ext not in ALLOWED_UPLOAD_EXT:
            raise ApiError(422, "bad_ext", "__all__", name)
        if base in files or (base == "manifest.json"
                             and manifest_raw is not None):
            raise ApiError(422, "duplicate_file", "__all__",
                           f"Дублікат імені файла: {base}")
        # B1: читаємо максимум MAX_ZIP_BYTES+1 — не довіряємо file_size
        with zf.open(name) as fh:
            blob = fh.read(MAX_ZIP_BYTES + 1)
        if len(blob) > MAX_ZIP_BYTES:
            raise ApiError(422, "file_too_large", "__all__",
                           f"«{name}» більший за 512КБ у розпакованому вигляді")
        if base == "manifest.json":
            manifest_raw = blob
            continue
        try:
            files[base] = blob.decode("utf-8")
        except UnicodeDecodeError:
            # бінарний файл (png): base64 + encoding="base64" у БД
            files[base] = base64.b64encode(blob).decode("ascii")
            binary.add(base)
    if manifest_raw is None:
        raise ApiError(422, "manifest_missing", "__all__",
                       "У zip немає manifest.json")
    manifest = _validated_manifest(manifest_raw)
    _check_files(files, binary)
    if "plugin.py" not in files and "index.html" not in files:
        raise ApiError(422, "no_entry", "__all__",
                       "Потрібен plugin.py або index.html")
    db = new_session()
    try:
        admin = _is_admin(user)
        meta = _store_plugin(db, manifest, files, user.id, verified=admin,
                             visibility=_norm_visibility(visibility),
                             binary=binary, is_admin=admin)
        db.commit()
        return _upload_result(meta)
    finally:
        db.close()


@router.post("/upload-files")
async def upload_files(files: list[UploadFile] = File(...),
                       visibility: str = Form("public"),
                       user: User = Depends(get_current_user)):
    """Аплоад окремими файлами: manifest.json + plugin.py + index.html..."""
    if len(files) > MAX_FILES:
        raise ApiError(422, "too_many_files", "__all__",
                       f"Максимум {MAX_FILES} файлів")
    total = 0
    parsed: dict[str, str] = {}
    binary: set[str] = set()
    manifest_raw: bytes | None = None
    for f in files:
        base = (f.filename or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        if not base or "/" in base or "\\" in base or base.startswith("."):
            raise ApiError(422, "bad_path", "__all__", base)
        ext = "." + base.rsplit(".", 1)[-1].lower()
        if ext not in ALLOWED_UPLOAD_EXT:
            raise ApiError(422, "bad_ext", "__all__",
                           f"Розширення «{base}» заборонене")
        if base in parsed or (base == "manifest.json"
                              and manifest_raw is not None):
            raise ApiError(422, "duplicate_file", "__all__",
                           f"Дублікат імені файла: {base}")
        blob = await f.read(MAX_ZIP_BYTES + 1)  # ліміт ДО повного читання
        total += len(blob)
        if total > MAX_ZIP_BYTES:
            raise ApiError(422, "too_large", "__all__",
                           "Плагін більший за 512КБ")
        if base == "manifest.json":
            manifest_raw = blob
            continue
        try:
            parsed[base] = blob.decode("utf-8")
        except UnicodeDecodeError:
            parsed[base] = base64.b64encode(blob).decode("ascii")
            binary.add(base)
    if manifest_raw is None:
        raise ApiError(422, "manifest_missing", "__all__",
                       "Серед файлів немає manifest.json")
    manifest = _validated_manifest(manifest_raw)
    _check_files(parsed, binary)
    if "plugin.py" not in parsed and "index.html" not in parsed:
        raise ApiError(422, "no_entry", "__all__",
                       "Потрібен plugin.py або index.html")
    db = new_session()
    try:
        admin = _is_admin(user)
        meta = _store_plugin(db, manifest, parsed, user.id, verified=admin,
                             visibility=_norm_visibility(visibility),
                             binary=binary, is_admin=admin)
        db.commit()
        return _upload_result(meta)
    finally:
        db.close()


# ---------------------------------------------------------------- share

@router.post("/{plugin_id}/share")
async def share_plugin(plugin_id: str, body: dict,
                       user: User = Depends(get_current_user)):
    """Згенерувати/повернути share-посилання (адмін або автор аплоаду)."""
    import secrets
    db = new_session()
    try:
        meta = _meta_or_404(db, plugin_id)
        if not (_is_admin(user) or meta.uploaded_by == user.id):
            raise ApiError(403, "forbidden", "__all__")
        if body.get("visibility"):
            meta.visibility = _norm_visibility(body.get("visibility"))
        if meta.visibility == "link" and not meta.share_token:
            meta.share_token = secrets.token_urlsafe(24)
        if meta.visibility != "link":
            meta.share_token = ""
        db.commit()
        return {"ok": True, "data": {"visibility": meta.visibility,
                                     "share_token": meta.share_token}}
    finally:
        db.close()


@router.get("/shared/{token}")
async def shared_plugin(token: str, user: User = Depends(get_current_user)):
    """Доступ до плагіна за share-посиланням (видимість «по посиланню»)."""
    db = new_session()
    try:
        meta = (db.query(PluginMeta)
                .filter(PluginMeta.share_token == token,
                        PluginMeta.visibility == "link").first())
        if meta is None:
            raise ApiError(404, "not_found", "__all__")
        return {"ok": True, "data": _plugin_out(db, meta, user.id)}
    finally:
        db.close()


# ---------------------------------------------------------------- адмін

@router.post("/{plugin_id}/verify")
async def verify_plugin(plugin_id: str, body: dict,
                        user: User = Depends(get_current_user)):
    """Верифікація (тільки адмін). Новий аплоад знімає прапорець."""
    if not _is_admin(user):
        raise ApiError(403, "not_admin", "__all__", "Лише адмін")
    db = new_session()
    try:
        meta = _meta_or_404(db, plugin_id)
        meta.verified = bool(body.get("verified", True))
        db.commit()
        return {"ok": True, "data": {"verified": meta.verified}}
    finally:
        db.close()


# ---------------------------------------------------------------- інсталяція

def _parse_seqs(raw) -> list[int]:
    """account_seqs: список цілих (<=50); не список -> 400, сміття ігноруємо."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ApiError(400, "bad_account_seqs", "account_seqs",
                       "account_seqs має бути списком")
    out: list[int] = []
    for x in raw[:50]:
        if isinstance(x, bool):
            continue
        sx = str(x).strip()
        if sx.isascii() and sx.lstrip("-").isdigit():
            out.append(int(sx))
    return out


@router.post("/{plugin_id}/install")
async def install(plugin_id: str, body: dict,
                  user: User = Depends(get_current_user)):
    """Встановити плагін: юзер явно приймає дозволи.

    Не верифікований плагін ставить лише його автор або адмін;
    link-плагін - лише з правильним share_token у тілі."""
    db = new_session()
    try:
        meta = _meta_or_404(db, plugin_id)
        # N-M3: приватний чужий плагін / link без токена -> 404
        _visible_or_404(db, meta, user, token=body.get("share_token"))
        if not may_run(meta, user.id):
            raise ApiError(403, "plugin_unverified", "__all__",
                           "Плагін ще не верифіковано адміністратором")
        perms = body.get("accept_permissions")
        if perms is None:
            perms = []
        if not isinstance(perms, list) or any(
                not isinstance(p, str) for p in perms):
            raise ApiError(400, "bad_permissions", "accept_permissions",
                           "accept_permissions: список рядків")
        if sorted(perms) != sorted(meta.manifest.get("permissions") or []):
            raise ApiError(422, "permissions_not_accepted", "__all__",
                           "Потрібно прийняти всі дозволи плагіна")
        seqs = _parse_seqs(body.get("account_seqs"))
        existing = (db.query(PluginInstall)
                    .filter_by(user_id=user.id, plugin_id=plugin_id)
                    .first())
        if existing is None:
            db.add(PluginInstall(user_id=user.id, plugin_id=plugin_id,
                                 accepted_permissions=perms, enabled=True,
                                 settings={}, storage="{}",
                                 account_seqs=seqs))
        else:
            existing.accepted_permissions = perms
            existing.enabled = True
            existing.account_seqs = seqs
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@router.post("/{plugin_id}/uninstall")
async def uninstall(plugin_id: str,
                    user: User = Depends(get_current_user)):
    db = new_session()
    try:
        _meta_or_404(db, plugin_id)
        row = (db.query(PluginInstall)
               .filter_by(user_id=user.id, plugin_id=plugin_id).first())
        if row is not None:
            db.delete(row)
            db.commit()
        return {"ok": True}
    finally:
        db.close()


@router.post("/{plugin_id}/enable")
async def enable(plugin_id: str, body: dict,
                 user: User = Depends(get_current_user)):
    db = new_session()
    try:
        row = (db.query(PluginInstall)
               .filter_by(user_id=user.id, plugin_id=plugin_id).first())
        if row is None:
            raise ApiError(404, "not_installed", "__all__")
        want = bool(body.get("enabled", True))
        if want:
            meta = _meta_or_404(db, plugin_id)
            # після оновлення плагіна дозволи треба прийняти знову
            if sorted(row.accepted_permissions or []) != sorted(
                    meta.manifest.get("permissions") or []):
                raise ApiError(409, "needs_reaccept", "__all__",
                               "Прийміть дозволи плагіна знову (перевстановіть)")
            if not may_run(meta, user.id):
                raise ApiError(403, "plugin_unverified", "__all__",
                               "Плагін ще не верифіковано адміністратором")
        row.enabled = want
        db.commit()
        return {"ok": True, "data": {"enabled": row.enabled}}
    finally:
        db.close()


# ---------------------------------------------------------------- налаштування

@router.get("/{plugin_id}/settings")
async def get_plugin_settings(plugin_id: str,
                              user: User = Depends(get_current_user)):
    db = new_session()
    try:
        meta = _meta_or_404(db, plugin_id)
        inst = (db.query(PluginInstall)
                .filter_by(user_id=user.id, plugin_id=plugin_id).first())
        return {"ok": True, "data": {
            "schema": meta.manifest.get("settings_schema") or [],
            "values": (inst.settings if inst else None) or {},
            "account_seqs": (inst.account_seqs if inst else None) or [],
            "storage_kb": int(meta.manifest.get("storage_limit_kb", 64)),
        }}
    finally:
        db.close()


@router.put("/{plugin_id}/settings")
async def put_plugin_settings(plugin_id: str, body: dict,
                              user: User = Depends(get_current_user)):
    """Персональні налаштування: приймаємо лише ключі зі schema."""
    db = new_session()
    try:
        meta = _meta_or_404(db, plugin_id)
        row = (db.query(PluginInstall)
               .filter_by(user_id=user.id, plugin_id=plugin_id).first())
        if row is None:
            raise ApiError(404, "not_installed", "__all__")
        schema = meta.manifest.get("settings_schema") or []
        known = {s.get("key") for s in schema if isinstance(s, dict)}
        incoming = body.get("settings") or {}
        if not isinstance(incoming, dict):
            raise ApiError(400, "bad_settings", "settings",
                           "settings: має бути об'єктом")
        clean = {k: v for k, v in incoming.items() if k in known}
        if len(json.dumps(clean, ensure_ascii=False, default=str)) > 16384:
            raise ApiError(413, "settings_too_large", "settings",
                           "Налаштування більші за 16КБ")
        row.settings = clean
        if "account_seqs" in body:
            row.account_seqs = _parse_seqs(body.get("account_seqs"))
        db.commit()
        return {"ok": True, "data": {"settings": clean,
                                     "account_seqs": row.account_seqs or []}}
    finally:
        db.close()


# ---------------------------------------------------------------- UI / логи

@router.post("/{plugin_id}/ui")
async def ui_request(plugin_id: str, body: dict,
                     user: User = Depends(get_current_user)):
    """Лямбда-тригер «юзер відкрив вкладку плагіна» → хук on_ui."""
    params = body.get("params") or {}
    if not isinstance(params, dict):
        raise ApiError(400, "bad_params", "params",
                       "params: має бути об'єктом")
    result = await service.run_ui_request(plugin_id, user.id, params)
    return {"ok": bool(result.get("ok")), "data": result}


@router.get("/{plugin_id}/runs")
async def runs(plugin_id: str, user: User = Depends(get_current_user)):
    """Логи виконань юзера (дебаг + аудит верифікації)."""
    db = new_session()
    try:
        rows = (db.query(PluginRun)
                .filter(PluginRun.user_id == user.id,
                        PluginRun.plugin_id == plugin_id)
                .order_by(PluginRun.id.desc()).limit(30).all())
        return {"ok": True, "data": [{
            "ok": r.ok, "trigger": r.trigger, "detail": r.trigger_detail,
            "ms": r.duration_ms, "error": r.outcome[:300],
            "at": str(r.created_at or ""),
        } for r in rows]}
    finally:
        db.close()


@router.get("/{plugin_id}/download")
async def download(plugin_id: str, user: User = Depends(get_current_user)):
    """Завантажити плагін як zip (адмін або автор аплоаду)."""
    from fastapi.responses import Response
    db = new_session()
    try:
        meta = _meta_or_404(db, plugin_id)
        if not (_is_admin(user) or meta.uploaded_by == user.id):
            raise ApiError(403, "forbidden", "__all__",
                           "Лише адмін або автор аплоаду")
        files = db.query(PluginFile).filter_by(plugin_id=plugin_id).all()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("manifest.json",
                       json.dumps(meta.manifest, ensure_ascii=False,
                                  indent=2))
            for f in files:
                if f.encoding == "base64":
                    try:
                        z.writestr(f.path, base64.b64decode(f.content))
                    except ValueError:  # пошкоджений base64 у БД
                        z.writestr(f.path, f.content)
                else:
                    z.writestr(f.path, f.content)
        return Response(
            content=buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition":
                     f'attachment; filename="{plugin_id}.zip"'},
        )
    finally:
        db.close()


# CSP для iframe плагіна: жодних зовнішніх ресурсів і мережі; скрипти лише
# inline. Фронт має вбудовувати html у <iframe sandbox="allow-scripts"
# srcdoc> (без allow-same-origin) і може додати цей рядок як <meta> CSP.
PLUGIN_UI_CSP = ("sandbox allow-scripts; default-src 'none'; "
                 "script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                 "img-src data:; font-src data:; connect-src 'none'; "
                 "form-action 'none'; base-uri 'none'")


@router.get("/{plugin_id}/source")
async def source(plugin_id: str, path: str = "index.html",
                 token: str | None = None,
                 user: User = Depends(get_current_user)):
    """UI-файл плагіна для iframe (srcdoc). Тільки index.html.

    Відповідь - JSON; заголовки nosniff + CSP sandbox + no-store, щоб
    навіть прямий перегляд URL не виконав HTML плагіна в origin додатка."""
    from fastapi.responses import JSONResponse
    if path != "index.html":
        raise ApiError(422, "bad_path", "__all__")
    db = new_session()
    try:
        meta = _meta_or_404(db, plugin_id)
        # N-M3: приватний чужий плагін -> 404 (не розкривати існування)
        _visible_or_404(db, meta, user, token=token)
        if not may_run(meta, user.id):
            raise ApiError(404, "plugin_not_found", "__all__")
        row = (db.query(PluginFile)
               .filter_by(plugin_id=plugin_id, path=path).first())
        if row is None or row.encoding != "utf-8":
            raise ApiError(404, "no_ui", "__all__")
        return JSONResponse(
            {"ok": True, "data": {"html": row.content,
                                  "csp": PLUGIN_UI_CSP}},
            headers={"X-Content-Type-Options": "nosniff",
                     "Content-Security-Policy": PLUGIN_UI_CSP,
                     "Cache-Control": "private, no-store"})
    finally:
        db.close()


@router.delete("/{plugin_id}")
async def delete_plugin(plugin_id: str,
                        user: User = Depends(get_current_user)):
    """Видалення плагіна: адмін або автор (той, хто аплоадив)."""
    db = new_session()
    try:
        meta = _meta_or_404(db, plugin_id)
        if not (_is_admin(user) or meta.uploaded_by == user.id):
            raise ApiError(403, "forbidden", "__all__")
        db.query(PluginFile).filter_by(plugin_id=plugin_id) \
            .delete(synchronize_session=False)
        db.query(PluginInstall).filter_by(plugin_id=plugin_id) \
            .delete(synchronize_session=False)
        db.query(PluginRun).filter_by(plugin_id=plugin_id) \
            .delete(synchronize_session=False)
        _unregister_tg(db, plugin_id)
        db.delete(meta)
        db.commit()
        return {"ok": True}
    finally:
        db.close()