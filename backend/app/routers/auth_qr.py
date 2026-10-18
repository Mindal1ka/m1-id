"""Вхід за QR (ПК показує QR → підтверджує телефон або Telegram)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.responses import ApiError, ok
from app.db.models import User
from app.deps import get_current_user, get_db
from app.routers.auth_m1 import _user_out
from app.services import qr_login as qr
from app.services.ratelimit import client_ip, rate_limit

router = APIRouter(prefix="/api/auth/qr", tags=["M1 ID Auth"])

_TOKEN = Field(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")


class PollIn(BaseModel):
    token: str = _TOKEN
    secret: str = Field(min_length=16, max_length=64)


class ApproveIn(BaseModel):
    token: str = _TOKEN
    code: str = Field(min_length=2, max_length=2, pattern=r"^\d\d$")


class TokenIn(BaseModel):
    token: str = _TOKEN


@router.post("/start", dependencies=[rate_limit(times=20)])
def start(request: Request, db: Session = Depends(get_db)) -> dict:
    ua = request.headers.get("user-agent", "")
    token, secret, row = qr.create(db, client_ip(request), ua)
    url = qr.link_for(token, request.headers.get("origin"))
    return ok({
        "token": token, "secret": secret, "url": url,
        "qr": qr.make_qr_data_uri(url), "code": row.code,
        "expires_in": int(qr.QR_TTL.total_seconds()),
    })


@router.post("/poll", dependencies=[rate_limit(times=90)])
def poll(body: PollIn, request: Request,
         db: Session = Depends(get_db)) -> dict:
    status, pair = qr.poll(db, body.token, body.secret,
                           request.headers.get("user-agent", ""))
    if pair is not None:
        pair["user"] = _user_out(pair["user"])
    return ok({"status": status, "pair": pair})


@router.get("/info", dependencies=[rate_limit(times=30)])
def info(token: str, user: User = Depends(get_current_user),
         db: Session = Depends(get_db)) -> dict:
    row = qr.get_live(db, token) if len(token) == 32 else None
    if row is None or row.status != "pending":
        raise ApiError(404, "qr_expired", "token", "qr_expired")
    return ok({
        "device": qr.describe_ua(row.req_ua), "ip": row.req_ip,
        "created_at": row.created_at.isoformat(),
        "options": qr.code_options(token, row.code),
    })


@router.post("/approve", dependencies=[rate_limit(times=20)])
def approve(body: ApproveIn, user: User = Depends(get_current_user),
            db: Session = Depends(get_db)) -> dict:
    res = qr.approve(db, body.token, user.id, body.code, "web")
    if res == "wrong_code":
        raise ApiError(403, "qr_wrong_code", "code", "qr_wrong_code")
    if res != "ok":
        raise ApiError(404, "qr_expired", "token", "qr_expired")
    return ok({"approved": True})


@router.post("/deny", dependencies=[rate_limit(times=20)])
def deny(body: TokenIn, user: User = Depends(get_current_user),
         db: Session = Depends(get_db)) -> dict:
    return ok({"denied": qr.deny(db, body.token)})
