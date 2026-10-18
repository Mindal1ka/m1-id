"""API вкладки «Додаткові» на сайті: notify-сокет MyStat + Автооцінювання.

GET  /api/extras/status   → по кожному акаунту: сокет, автооцінка, стан
                             з'єднання, остання подія, відкладені оцінки
POST /api/extras/settings → {account_seq, socket_enabled?, auto_eval?}
                             (увімкнення/вимкнення застосовується негайно)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.responses import ApiError, ok
from app.db.models import (
    AutoEvalLog,
    MystatAccount,
    SocketAccountConfig,
    TelegramAccountConfig,
    User,
)
from app.deps import get_current_user, get_db
from app.services import notify_socket

router = APIRouter(prefix="/api/extras", tags=["extras"])


class ExtrasSettingsIn(BaseModel):
    account_seq: int
    socket_enabled: bool | None = None
    auto_eval: bool | None = None


def _acc_login(acc: MystatAccount) -> str:
    return acc.mystat_login or acc.label or acc.fio or f"Акаунт #{acc.user_seq}"


def _get_or_create_cfg(db: Session, acc: MystatAccount) -> SocketAccountConfig:
    cfg = (db.query(SocketAccountConfig)
           .filter(SocketAccountConfig.account_id == acc.id).first())
    if cfg is None:
        cfg = SocketAccountConfig(account_id=acc.id, user_id=acc.user_id)
        db.add(cfg)
    return cfg


@router.get("/status")
async def extras_status(user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)) -> dict:
    accs = (db.query(MystatAccount)
            .filter(MystatAccount.user_id == user.id,
                    MystatAccount.status != "disabled")
            .order_by(MystatAccount.user_seq).all())
    out: list[dict] = []
    for acc in accs:
        cfg = (db.query(SocketAccountConfig)
               .filter(SocketAccountConfig.account_id == acc.id).first())
        tcfg = (db.query(TelegramAccountConfig)
                .filter(TelegramAccountConfig.account_id == acc.id).first())
        st = notify_socket.status_for(acc.id)
        pending = (db.query(AutoEvalLog)
                   .filter(AutoEvalLog.account_id == acc.id,
                           AutoEvalLog.status == "pending").count())
        last_eval = (db.query(AutoEvalLog)
                     .filter(AutoEvalLog.account_id == acc.id,
                             AutoEvalLog.status.in_(["ok", "already"]))
                     .order_by(AutoEvalLog.id.desc()).first())
        out.append({
            "account_seq": acc.user_seq,
            "login": _acc_login(acc),
            "socket_enabled": bool(cfg.socket_enabled) if cfg else False,
            "auto_eval": bool(cfg.auto_eval) if cfg else False,
            "quiet_hours": bool(tcfg.quiet_hours) if tcfg else True,
            "connected": bool(st.get("connected")),
            "last_event_at": st.get("last_event_at"),
            "events": int(st.get("events") or 0),
            "evals_ok": int(st.get("evals_ok") or 0),
            "pending_evals": pending,
            "last_error": st.get("last_error") or "",
            "last_eval": ({
                "theme": last_eval.theme,
                "teach_name": last_eval.teach_name,
                "rated_at": last_eval.rated_at.isoformat(timespec="seconds")
                if last_eval.rated_at else None,
            } if last_eval else None),
        })
    return ok({
        "available": notify_socket.socketio is not None,
        "accounts": out,
    })


@router.post("/settings")
async def extras_settings(body: ExtrasSettingsIn,
                          user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)) -> dict:
    acc = (db.query(MystatAccount)
           .filter(MystatAccount.user_id == user.id,
                   MystatAccount.user_seq == body.account_seq).first())
    if acc is None:
        raise ApiError(404, "account_not_found", "account_seq",
                       "no_such_mystat_account")
    cfg = _get_or_create_cfg(db, acc)
    changed_socket = False
    if body.socket_enabled is not None \
            and cfg.socket_enabled != body.socket_enabled:
        cfg.socket_enabled = body.socket_enabled
        changed_socket = True
    if body.auto_eval is not None:
        cfg.auto_eval = body.auto_eval
        if cfg.auto_eval and not cfg.socket_enabled:
            # автооцінка живе тільки на сокеті - увімкнюємо і його
            cfg.socket_enabled = True
            changed_socket = True
    db.commit()
    if changed_socket:
        notify_socket.restart_account(acc.id, cfg.socket_enabled)
    return ok({
        "account_seq": acc.user_seq,
        "socket_enabled": cfg.socket_enabled,
        "auto_eval": cfg.auto_eval,
    })
