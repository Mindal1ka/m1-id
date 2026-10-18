"""API вкладки «Telegram» на сайті: статус прив'язки, QR, налаштування
сповіщень (ОКРЕМО для кожного акаунта MyStat), відв'язка, тест.

GET  /api/telegram/status   → linked, bot, deep_link, qr, accounts[+конфіги]
POST /api/telegram/settings → {account_seq, ...тумблери} - конфіг акаунта
POST /api/telegram/unlink   → відв'язати Telegram (прив'язка + конфіги)
POST /api/telegram/test     → {account_seq?} тестове сповіщення в чат
"""
from __future__ import annotations

import base64
import html
import io

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.responses import ApiError, ok
from app.db.models import MystatAccount, TelegramAccountConfig, TelegramLink, User
from app.deps import get_current_user, get_db
from app.telegram import runtime as tg_runtime
from app.telegram.linking import make_start_payload

router = APIRouter(prefix="/api", tags=["telegram"])


class TelegramSettingsIn(BaseModel):
    account_seq: int
    homework_new: bool | None = None
    rating_change: bool | None = None
    schedule_week_change: bool | None = None
    schedule_day_change: bool | None = None
    schedule_daily: bool | None = None
    marks_new: bool | None = None
    leaderboard_change: bool | None = None
    leaderboard_mine_only: bool | None = None
    leaderboard_scope: str | None = None
    leaderboard_period: str | None = None
    shop_change: bool | None = None
    deadlines: bool | None = None
    quiet_hours: bool | None = None
    auto_eval_notify: bool | None = None
    link_open_notify: bool | None = None


class TelegramTestIn(BaseModel):
    account_seq: int | None = None


_FIELD_MAP = {
    "homework_new": "notify_homework",
    "deadlines": "notify_deadlines",
    "rating_change": "notify_rating",
    "schedule_week_change": "notify_schedule_week",
    "schedule_day_change": "notify_schedule_day",
    "schedule_daily": "notify_schedule_daily",
    "marks_new": "notify_marks",
    "leaderboard_change": "notify_leaderboard",
    "leaderboard_mine_only": "leaderboard_mine_only",
    "leaderboard_scope": "lb_scope",
    "leaderboard_period": "lb_period",
    "shop_change": "notify_shop",
    "quiet_hours": "quiet_hours",
    "auto_eval_notify": "notify_auto_eval",
    "link_open_notify": "notify_link_open",
}


def _settings_out(cfg: TelegramAccountConfig) -> dict:
    return {
        "homework_new": cfg.notify_homework,
        "deadlines": cfg.notify_deadlines,
        "rating_change": cfg.notify_rating,
        "schedule_week_change": cfg.notify_schedule_week,
        "schedule_day_change": cfg.notify_schedule_day,
        "schedule_daily": cfg.notify_schedule_daily,
        "marks_new": cfg.notify_marks,
        "leaderboard_change": cfg.notify_leaderboard,
        "leaderboard_mine_only": cfg.leaderboard_mine_only,
        "leaderboard_scope": cfg.lb_scope or "",
        "leaderboard_period": cfg.lb_period or "",
        "shop_change": cfg.notify_shop,
        "quiet_hours": cfg.quiet_hours,
        "auto_eval_notify": cfg.notify_auto_eval,
        "link_open_notify": cfg.notify_link_open,
    }


def _acc_login(acc: MystatAccount) -> str:
    """Логін (як у виборі акаунтів на сайті): ПІБ в людей однакове."""
    return acc.mystat_login or acc.label or acc.fio or f"Акаунт #{acc.user_seq}"


def _qr_data_uri(text: str) -> str | None:
    """PNG data-URI (segno - без зовнішніх залежностей). None якщо segno
    не встановлено - фронт тоді показує лише кнопку-посилання."""
    try:
        import segno
    except ImportError:
        return None
    try:
        buf = io.BytesIO()
        segno.make(text, error="m").save(buf, kind="png", scale=8, border=2)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def _get_link(db: Session, user: User) -> TelegramLink | None:
    return (db.query(TelegramLink)
            .filter(TelegramLink.user_id == user.id).first())


def _account_by_seq(db: Session, user: User, seq: int) -> MystatAccount:
    acc = (db.query(MystatAccount)
           .filter(MystatAccount.user_id == user.id,
                   MystatAccount.user_seq == seq).first())
    if acc is None:
        raise ApiError(404, "account_not_found", "account_seq",
                       "no_such_mystat_account")
    return acc


def _get_or_create_cfg(db: Session, acc: MystatAccount, chat_id: int = 0) \
        -> TelegramAccountConfig:
    cfg = (db.query(TelegramAccountConfig)
           .filter(TelegramAccountConfig.account_id == acc.id).first())
    if cfg is None:
        cfg = TelegramAccountConfig(account_id=acc.id, user_id=acc.user_id,
                                    chat_id=chat_id)
        db.add(cfg)
    return cfg


@router.get("/telegram/status")
async def telegram_status(user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    link = _get_link(db, user)
    username = tg_runtime.bot_username()
    if username is None:
        # бот ще стартує (або впав) - одноразовий on-demand getMe з кешем
        username = await tg_runtime.ensure_username()
    if username is None and link is not None and link.bot_username:
        username = link.bot_username  # останнє відоме ім'я
    bot_configured = bool((settings.telegram_bot_token or "").strip())
    deep_link = None
    if username and bot_configured:
        deep_link = f"https://t.me/{username}?start={make_start_payload(user.id)}"
    qr = _qr_data_uri(deep_link) if deep_link and link is None else None

    # конфіги ПЕР-АКАУНТ: кожен акаунт має власні тумблери
    accounts = (db.query(MystatAccount)
                .filter(MystatAccount.user_id == user.id,
                        MystatAccount.status != "disabled")
                .order_by(MystatAccount.user_seq).all())
    cfgs = {c.account_id: c for c in
            db.query(TelegramAccountConfig)
            .filter(TelegramAccountConfig.user_id == user.id).all()}
    tg_accounts = []
    for a in accounts:
        cfg = cfgs.get(a.id)
        tg_accounts.append({
            "account_seq": a.user_seq,
            "login": _acc_login(a),
            "fio": a.fio or "",
            "label": a.label or "",
            "status": a.status,
            "settings": _settings_out(cfg) if cfg else None,
        })
    return ok({
        "linked": link is not None,
        "bot_configured": bot_configured,
        "bot_running": tg_runtime.is_running(),
        "bot_username": username,
        "deep_link": deep_link,
        "qr_data_uri": qr,
        "site_url": settings.telegram_site_url,
        "linked_at": link.linked_at.isoformat() if link else None,
        "accounts": tg_accounts,
    })


@router.post("/telegram/settings")
async def telegram_settings(body: TelegramSettingsIn,
                            user: User = Depends(get_current_user),
                            db: Session = Depends(get_db)) -> dict:
    link = _get_link(db, user)
    if link is None:
        raise ApiError(404, "telegram_not_linked", "__all__",
                       "link_telegram_first_scan_qr_or_open_bot")
    acc = _account_by_seq(db, user, body.account_seq)
    cfg = _get_or_create_cfg(db, acc, chat_id=link.chat_id)
    str_fields = {"leaderboard_scope", "leaderboard_period"}
    for key, val in body.model_dump(exclude_unset=True).items():
        if key == "account_seq":
            continue
        if key in str_fields:
            # вибір зрізу лідерборда: короткий рядок, '' = усі зрізи
            setattr(cfg, _FIELD_MAP[key], str(val or "").strip()[:32])
        else:
            setattr(cfg, _FIELD_MAP[key], bool(val))
    cfg.chat_id = link.chat_id  # на випадок переприв'язки
    db.commit()
    return ok(_settings_out(cfg))


@router.post("/telegram/unlink")
async def telegram_unlink(user: User = Depends(get_current_user),
                          db: Session = Depends(get_db)) -> dict:
    link = _get_link(db, user)
    if link is not None:
        db.delete(link)
    # конфіги теж прибираємо: «відв'язати» = повністю вимкнути бота
    for cfg in (db.query(TelegramAccountConfig)
                .filter(TelegramAccountConfig.user_id == user.id).all()):
        db.delete(cfg)
    db.commit()
    return ok({"unlinked": True})


@router.post("/telegram/test")
async def telegram_test(body: TelegramTestIn,
                        user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)) -> dict:
    link = _get_link(db, user)
    if link is None:
        raise ApiError(404, "telegram_not_linked", "__all__",
                       "link_telegram_first_scan_qr_or_open_bot")
    if not tg_runtime.is_running():
        raise ApiError(503, "telegram_bot_not_running", "__all__",
                       "bot_is_not_running_right_now")
    prefix = ""
    if body.account_seq is not None:
        acc = _account_by_seq(db, user, body.account_seq)
        prefix = f"<b>{html.escape(str(_acc_login(acc)))}</b>\n"
    try:
        await tg_runtime.send_to_chat(
            link.chat_id,
            prefix + "🔔 <b>Тестове сповіщення M1 ID</b>\n\nУсе працює - сюди "
            "приходитимуть сповіщення, увімкнені у вкладці «Telegram».",
        )
    except RuntimeError as exc:
        raise ApiError(503, "telegram_bot_not_running", "__all__",
                       "bot_is_not_running_right_now") from exc
    except Exception as exc:
        raise ApiError(502, "telegram_send_failed", "__all__",
                       "could_not_deliver_message_check_bot") from exc
    return ok({"sent": True})
