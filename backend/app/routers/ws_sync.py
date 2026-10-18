"""WebSocket: живий пуш стану синку акаунтів користувача.

Замість постійного полінгу GET /accounts/{id}/sync/status клієнт сайту
підключається один раз (токен = довгоживучий сесійний токен, валідність
за БД — той самий механізм, що й у Bearer). Сервер одразу надсилає
поточний стан кожного акаунта, далі — пуш на кожну зміну (_update у
sync_engine). Пінги від клієнта тримають сокет живим.

Автентифікація (протокол):
  1) РЕКОМЕНДОВАНО: підключитися до /api/ws/sync БЕЗ токена в URL (query
     потрапляє в access-логи проксі), після відкриття сокета першим
     текстовим повідомленням надіслати
         {"type":"auth","token":"<session token>"}
     (також приймається сам токен «голим» рядком). Чекаємо до 10 с.
  2) Застаріле (сумісність): ?token=<session token> у URL.
При невдалій автентифікації сокет закривається з кодом 4401, при
таймауті першого повідомлення — 4408. Після успіху сервер шле стан
акаунтів як раніше: {"account": <seq>, ...state}.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import session_user_from_token
from app.db.base import SessionLocal
from app.db.models import MystatAccount
from app.services import sync_engine

router = APIRouter(tags=["Sync WS"])


_AUTH_TIMEOUT = 10.0
_MAX_AUTH_MSG = 4096


def _token_from_first_message(raw: str) -> str:
    """{"type":"auth","token":"..."} або «голий» токен."""
    raw = (raw or "").strip()
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except ValueError:
            return ""
        if isinstance(data, dict) and isinstance(data.get("token"), str):
            return data["token"].strip()
        return ""
    return raw


@router.websocket("/api/ws/sync")
async def ws_sync(ws: WebSocket) -> None:
    token = ws.query_params.get("token", "")  # застарілий спосіб
    db = SessionLocal()
    subscribed = False
    try:
        accepted = False
        if not token:
            # токен не в URL: приймаємо сокет і чекаємо auth-повідомлення
            await ws.accept()
            accepted = True
            try:
                raw = await asyncio.wait_for(ws.receive_text(),
                                             timeout=_AUTH_TIMEOUT)
            except asyncio.TimeoutError:
                await ws.close(code=4408)
                return
            if len(raw) > _MAX_AUTH_MSG:
                await ws.close(code=4401)
                return
            token = _token_from_first_message(raw)
        user = session_user_from_token(db, token) if token else None
        if user is None:
            # 4401 — валідний WS-код застосунку «не автентифіковано»
            await ws.close(code=4401)
            return
        account_pks = [row.id for row in
                       (db.query(MystatAccount.id)
                        .filter(MystatAccount.user_id == user.id)
                        .order_by(MystatAccount.id).all())]
        if not accepted:
            await ws.accept()
        # стартовий стан: клієнт миттю знає, що робить сервер, —
        # без чекання першої зміни
        for pk in account_pks:
            seq = (db.query(MystatAccount.user_seq)
                   .filter(MystatAccount.id == pk).scalar())
            state = sync_engine.get_state(pk)
            await ws.send_text(json.dumps({"account": seq, **state},
                                          ensure_ascii=False))
        sync_engine.sync_ws_register(ws, account_pks)
        subscribed = True
        while True:
            # клієнтський keepalive («p»); повідомлення ігноруємо
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        import logging

        logging.getLogger("m1id").warning("ws/sync: з'єднання обірвано",
                                          exc_info=True)
    finally:
        if subscribed:
            sync_engine.sync_ws_unregister(ws)
        db.close()