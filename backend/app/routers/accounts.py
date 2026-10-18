"""Підключені акаунти MyStat: прив'язка, список, видалення, синк, снапшоти."""
from __future__ import annotations

import json

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.responses import ApiError, ok
from app.db.models import MystatAccount, Snapshot, User
from app.deps import get_current_user, get_db
from app.services import mystat_client as ms
from app.services.branch_names import branch_display_name
from app.services import notify_socket
from app.services import sync_engine
from app.services.ratelimit import rate_limit

router = APIRouter(prefix="/api/accounts", tags=["MyStat Accounts"])


class LinkIn(BaseModel):
    login: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=128)


class LinkTokenIn(BaseModel):
    access_token: str = Field(min_length=20, max_length=4096)


def _out(a: MystatAccount) -> dict:
    """Акаунт без секретів — токен ніколи не покидає сервер."""
    state = sync_engine.get_state(a.id)
    return {
        "id": a.user_seq,
        "label": a.label or a.fio,
        "branch_alias": a.branch_alias,
        "branch_name": branch_display_name(a.branch_alias),
        "logbook_id": a.logbook_id,
        "id_user_storage": a.id_user_storage,
        "fio": a.fio,
        "login": a.mystat_login or "",
        "photo_url": a.photo_url,
        "status": a.status,
        "language": a.language,
        "last_synced_at": a.last_synced_at.isoformat() if a.last_synced_at else None,
        "sync_status": state.get("status", "idle"),
    }


def _get_owned(db: Session, user: User, account_id: int) -> MystatAccount:
    """account_id тут — публічний номер користувача (user_seq), не PK."""
    account = (db.query(MystatAccount)
               .filter(MystatAccount.user_id == user.id,
                       MystatAccount.user_seq == account_id)
               .first())
    if account is None:
        raise ApiError(404, "account_not_found", "__all__")
    return account


async def _link_with_token(db: Session, user: User,
                           token: str) -> tuple[MystatAccount, bool]:
    """Валідуємо токен через /auth/me і створюємо/оновлюємо акаунт. → (акаунт, створений)."""
    try:
        me = await ms.auth_me_async(token)
    except ms.MystatError as exc:
        if exc.status_code in (400, 401, 403):
            raise ApiError(401, "mystat_invalid_credentials", "login",
                           "invalid_mystat_login_or_token") from exc
        raise ApiError(502, "mystat_unavailable", "__all__",
                       f"mystat_api_error[{exc.status_code}]: {exc.message}") from exc
    except httpx.HTTPError as exc:  # мережа/таймаут/DNS — апстрім недоступний
        raise ApiError(502, "mystat_unavailable", "__all__",
                       "mystat_network_error") from exc

    norm = ms.parse_me(me)
    existing = (db.query(MystatAccount)
                .filter(MystatAccount.user_id == user.id,
                        MystatAccount.logbook_id == norm["logbook_id"])
                .first()) if norm["logbook_id"] else None

    created = existing is None
    account = existing or MystatAccount(user_id=user.id)
    if created:
        # публічний номер = «N-й акаунт цього користувача»
        account.user_seq = (
            db.query(func.coalesce(func.max(MystatAccount.user_seq), 0))
            .filter(MystatAccount.user_id == user.id)
            .scalar() or 0) + 1
    account.branch_alias = norm["branch_alias"] or account.branch_alias
    account.logbook_id = norm["logbook_id"] or account.logbook_id
    account.id_user_storage = norm["id_user_storage"] or account.id_user_storage
    account.fio = norm["fio"]
    account.mystat_login = norm["login"] or account.mystat_login
    account.photo_url = norm["photo_url"]
    account.language = norm["language"]
    ms.set_account_token(account, token)  # шифруємо + фіксуємо exp із JWT
    account.status = "active"
    db.add(account)
    try:
        db.commit()
    except IntegrityError:
        # гонка двох паралельних лінків: обидва порахували max+1 → конфлікт
        # uq_accounts_user_seq. Перераховуємо seq за фактом і повторюємо.
        db.rollback()
        existing = (db.query(MystatAccount)
                    .filter(MystatAccount.user_id == user.id,
                            MystatAccount.logbook_id == norm["logbook_id"])
                    .first()) if norm["logbook_id"] else None
        if existing is not None and existing.id == account.id:
            return account, created
        if existing is not None:
            # конкурент створив акаунт із тим самим logbook_id — повернемо його
            return existing, False
        account.user_seq = (
            db.query(func.coalesce(func.max(MystatAccount.user_seq), 0))
            .filter(MystatAccount.user_id == user.id)
            .scalar() or 0) + 1
        try:
            db.commit()
        except IntegrityError:
            # третій гонець встиг зайняти той самий seq — не 500, а чесний 409
            db.rollback()
            raise ApiError(409, "account_link_conflict", "__all__",
                           "account_link_race_please_retry") from None
    return account, created


@router.post("/link", dependencies=[rate_limit(times=6)])
async def link(body: LinkIn, request: Request,
               db: Session = Depends(get_db),
               user: User = Depends(get_current_user)) -> dict:
    """Логін у справжній MyStat на сервері; пароль ніде не зберігаємо."""
    try:
        # async: НЕ блокує event loop на 15с (sync-логін заморожував
        # весь API на час запиту до mapi)
        result = await ms.login_async(body.login.strip(), body.password)
    except ms.MystatError as exc:
        if exc.status_code in (400, 401, 403):
            raise ApiError(401, "mystat_invalid_credentials", "password",
                           "invalid_mystat_login_or_password") from exc
        raise ApiError(502, "mystat_unavailable", "__all__",
                       f"mystat_api_error[{exc.status_code}]: {exc.message}") from exc
    except httpx.HTTPError as exc:
        raise ApiError(502, "mystat_unavailable", "__all__",
                       "mystat_network_error") from exc

    account, created = await _link_with_token(db, user, result["access_token"])
    # логін MyStat — для списку акаунтів (topbar-селектор)
    account.mystat_login = (body.login.strip()
                            or account.mystat_login)
    db.commit()
    started = sync_engine.start_sync(account.id)
    return ok({"account": _out(account), "created": created,
               "sync_started": started})


@router.post("/link-token")
async def link_token(body: LinkTokenIn, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)) -> dict:
    """Dev-зручність: прив'язка готовим access-токеном (наприклад, із token.txt).
    На проді вимкнена (M1ID_DEBUG=0 за замовчуванням)."""
    if not get_settings().debug:
        raise ApiError(404, "not_found", "__all__", "dev_endpoint_disabled")
    account, created = await _link_with_token(db, user, body.access_token.strip())
    started = sync_engine.start_sync(account.id)
    return ok({"account": _out(account), "created": created,
               "sync_started": started})


@router.get("")
def list_accounts(db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)) -> dict:
    rows = (db.query(MystatAccount)
            .filter(MystatAccount.user_id == user.id)
            .order_by(MystatAccount.id)
            .all())

    # лінивий добір логіна: get-personal-data віддає username топ-рівнем;
    # якщо міграційний бекфілл не спрацював (снапшот з'явився пізніше) —
    # добираємо при першому запиті списку
    if any(not a.mystat_login for a in rows):
        from app.services.app_data import profile_login_from_snapshot
        changed = False
        for a in rows:
            if a.mystat_login:
                continue
            login = profile_login_from_snapshot(db, a.id)
            if login:
                a.mystat_login = login
                changed = True
        if changed:
            db.commit()

    return ok([_out(a) for a in rows])


@router.delete("/{account_id}")
def unlink(account_id: int, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)) -> dict:
    account = _get_owned(db, user, account_id)
    pk = account.id
    db.query(Snapshot).filter(Snapshot.account_id == pk).delete()
    db.delete(account)
    # user_seq НЕ перенумеровуємо: на нього посилаються
    # PluginInstall.account_seqs, M1Link.account_seq та URL клієнта;
    # зсув номерів мовчки перепризначив би залежні записи на чужий акаунт.
    # Діри в нумерації допустимі (нові акаунти беруть max+1).
    db.commit()
    # зупиняємо notify-сокет видаленого акаунта (інакше задача висить)
    try:
        notify_socket.stop_account(pk)
    except Exception:  # fail-soft: акаунт уже видалено
        pass
    return ok({"deleted": True, "id": account_id})


@router.post("/{account_id}/sync")
async def start_account_sync(account_id: int, db: Session = Depends(get_db),
                             user: User = Depends(get_current_user)) -> dict:
    account = _get_owned(db, user, account_id)
    if account.status == "needs_relogin":
        raise ApiError(409, "account_needs_relogin", "__all__",
                       "re_enter_mystat_credentials")
    if not sync_engine.start_sync(account.id):
        raise ApiError(409, "sync_already_running", "__all__")
    return ok({"started": True, "id": account.user_seq})


@router.get("/{account_id}/sync/status")
def sync_status(account_id: int, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> dict:
    account = _get_owned(db, user, account_id)
    return ok(sync_engine.get_state(account.id))


@router.get("/{account_id}/snapshots")
def snapshots_index(account_id: int, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)) -> dict:
    account = _get_owned(db, user, account_id)
    rows = (db.query(Snapshot.section, Snapshot.fetched_at,
                     func.length(Snapshot.payload))
            .filter(Snapshot.account_id == account.id)
            .order_by(Snapshot.section)
            .all())
    # length() у SQL: не вивантажуємо мегабайти payload у пам'ять заради size
    return ok([
        {
            "section": section,
            "fetched_at": fetched_at.isoformat() if fetched_at else None,
            "size_bytes": size or 0,
        }
        for section, fetched_at, size in rows
    ])


@router.get("/{account_id}/snapshots/{section}")
def snapshot_payload(account_id: int, section: str,
                     db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)) -> dict:
    account = _get_owned(db, user, account_id)
    row = (db.query(Snapshot)
           .filter(Snapshot.account_id == account.id,
                   Snapshot.section == section)
           .first())
    if row is None:
        raise ApiError(404, "snapshot_not_found", "section")
    try:
        payload = json.loads(row.payload)
    except json.JSONDecodeError:
        payload = row.payload
    return ok(payload, meta={"fetched_at":
                             row.fetched_at.isoformat() if row.fetched_at else None})
