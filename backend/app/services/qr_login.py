"""Вхід за QR: ПК показує QR із посиланням `<site>/qr/<token>`, вже
залогінений пристрій (сайт чи Telegram) підтверджує, ПК одноразово
забирає нову сесію.

Захист від фішингу: на ПК під QR стоїть 2-значний код збігу; підтверджуючий
пристрій показує 3 варіанти коду й лише правильний вибір дозволяє вхід
(помилка = запит відхилено). Варіанти-приманки детерміновані від токена.
"""
from __future__ import annotations

import hashlib
import random
import re
import secrets
from datetime import timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.clock import naive_utcnow
from app.core.config import get_settings
from app.core.security import create_session, hash_token
from app.db.models import QrLogin, User

QR_TTL = timedelta(seconds=120)
TOKEN_RE = re.compile(r"/qr/([0-9a-f]{32})(?![0-9a-f])")


def extract_token(text: str) -> str | None:
    """Токен із посилання (будь-який хост) або з голого 32-hex рядка."""
    text = (text or "").strip()
    m = TOKEN_RE.search(text)
    if m:
        return m.group(1)
    if re.fullmatch(r"[0-9a-f]{32}", text):
        return text
    return None


def site_base(origin: str | None = None) -> str:
    s = get_settings()
    if s.debug and origin and re.fullmatch(r"https?://[\w.\-:\[\]]+", origin):
        return origin.rstrip("/")
    return s.telegram_site_url.rstrip("/")


def link_for(token: str, origin: str | None = None) -> str:
    return f"{site_base(origin)}/qr/{token}"


def make_qr_data_uri(url: str) -> str:
    """QR для скану з екрана: рівень корекції H, білий фон + тиха зона 4
    (темна тема сайту не повинна інвертувати код)."""
    import segno
    qr = segno.make(url, error="h", micro=False)
    return qr.svg_data_uri(scale=8, border=4, dark="#000000", light="#ffffff")


def describe_ua(ua: str) -> str:
    ua = ua or ""
    browser = next((n for k, n in (("Edg/", "Edge"), ("OPR/", "Opera"),
                                   ("Firefox/", "Firefox"), ("Chrome/", "Chrome"),
                                   ("Safari/", "Safari")) if k in ua), "Браузер")
    os_ = next((n for k, n in (("Windows", "Windows"), ("Android", "Android"),
                               ("iPhone", "iOS"), ("iPad", "iPadOS"),
                               ("Mac OS", "macOS"), ("Linux", "Linux")) if k in ua),
               "невідома ОС")
    return f"{browser} · {os_}"


def create(db: Session, ip: str, ua: str) -> tuple[str, str, QrLogin]:
    """→ (link_token, poll_secret, запис). Старі протухлі чистимо тут же."""
    now = naive_utcnow()
    db.query(QrLogin).filter(QrLogin.expires_at < now - timedelta(minutes=10)).delete()
    token = secrets.token_hex(16)
    secret = secrets.token_urlsafe(24)
    row = QrLogin(
        id=hash_token(token), poll_hash=hash_token(secret),
        code=f"{secrets.randbelow(90) + 10}",
        req_ip=ip[:64], req_ua=(ua or "")[:255],
        expires_at=now + QR_TTL,
    )
    db.add(row)
    db.commit()
    return token, secret, row


def get_live(db: Session, token: str) -> QrLogin | None:
    row = db.get(QrLogin, hash_token(token or ""))
    if row is None or row.expires_at < naive_utcnow():
        return None
    return row


def code_options(token: str, real: str) -> list[str]:
    """3 варіанти коду (правильний + 2 приманки), стабільні для токена."""
    rnd = random.Random(hash_token(token))
    opts = {real}
    while len(opts) < 3:
        opts.add(f"{rnd.randrange(10, 100)}")
    out = sorted(opts)
    rnd.shuffle(out)
    return out


def approve(db: Session, token: str, user_id: int, code: str, via: str) -> str:
    """→ 'ok' | 'expired' | 'wrong_code' | 'not_pending'. Хибний код гасить
    запит (підбір неможливий)."""
    row = get_live(db, token)
    if row is None:
        return "expired"
    if row.status != "pending":
        return "not_pending"
    if code != row.code:
        res = db.execute(update(QrLogin).where(
            QrLogin.id == row.id, QrLogin.status == "pending")
            .values(status="denied"))
        db.commit()
        return "wrong_code"
    res = db.execute(update(QrLogin).where(
        QrLogin.id == row.id, QrLogin.status == "pending")
        .values(status="approved", user_id=user_id, approved_via=via))
    db.commit()
    return "ok" if res.rowcount else "not_pending"


def deny(db: Session, token: str) -> bool:
    row = get_live(db, token)
    if row is None:
        return False
    res = db.execute(update(QrLogin).where(
        QrLogin.id == row.id, QrLogin.status == "pending")
        .values(status="denied"))
    db.commit()
    return bool(res.rowcount)


def poll(db: Session, token: str, secret: str, ua: str) -> tuple[str, dict | None]:
    """→ (status, пара токенів | None). Пара віддається ОДИН раз."""
    row = db.get(QrLogin, hash_token(token or ""))
    if row is None or row.poll_hash != hash_token(secret or ""):
        return "expired", None
    if row.expires_at < naive_utcnow() and row.status != "approved":
        return "expired", None
    if row.status != "approved":
        return row.status, None
    # атомарно «забираємо» схвалення — друга вкладка/повтор отримає consumed
    res = db.execute(update(QrLogin).where(
        QrLogin.id == row.id, QrLogin.status == "approved")
        .values(status="consumed"))
    db.commit()
    if not res.rowcount:
        return "consumed", None
    user = db.get(User, row.user_id)
    if user is None:
        return "expired", None
    t = create_session(db, user.id, ua)
    return "approved", {"access_token": t, "refresh_token": t, "user": user}
