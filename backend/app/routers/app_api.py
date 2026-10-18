"""Наше агреговане API для фронтенда (M3): мало викликів — готовий формат."""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.clock import naive_kyiv_now
from app.core.responses import ApiError, ok
from app.db.models import MystatAccount, User
from app.deps import get_current_user, get_db
from app.services import app_data
from app.services.ratelimit import rate_limit_user

# N-M10: сумарний ліміт усіх файлів однієї здачі ДЗ (50×25МБ = 1.25ГБ
# без ліміту → OOM на одному запиті)
MAX_HOMEWORK_TOTAL_BYTES = 60 * 1024 * 1024
# запас на multipart-обгортку (межі, заголовки частин, текстові поля)
_MULTIPART_OVERHEAD = 2 * 1024 * 1024
MAX_HOMEWORK_REQUEST_BYTES = MAX_HOMEWORK_TOTAL_BYTES + _MULTIPART_OVERHEAD

# Ліміти довжини полів «написати директору/викладачу»
MAX_CONTACT_SUBJECT = 200
MAX_CONTACT_MESSAGE = 2000
MAX_CONTACT_TEACHER = 200

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class _SubmitSizeLimitRoute(APIRoute):
    """Обмежує розмір тіла ЗАПИТУ здачі ДЗ до того, як Starlette зіб'є весь
    multipart на диск/в пам'ять: перевірка Content-Length + підрахунок
    байтів, що реально надходять (chunked без Content-Length теж ріжемо)."""

    def get_route_handler(self):
        original = super().get_route_handler()
        if not self.path.endswith("/submit"):
            return original

        def _too_large() -> ApiError:
            return ApiError(413, "hw_payload_too_large", "files",
                            "total_files_size_exceeds_60mb")

        async def handler(request: Request):
            cl = request.headers.get("content-length")
            if cl and (cl.isascii() and cl.isdigit()) and int(cl) > MAX_HOMEWORK_REQUEST_BYTES:
                raise _too_large()
            inner_receive = request.receive
            received = 0

            async def counting_receive():
                nonlocal received
                message = await inner_receive()
                if message.get("type") == "http.request":
                    received += len(message.get("body") or b"")
                    if received > MAX_HOMEWORK_REQUEST_BYTES:
                        raise _too_large()
                return message

            return await original(Request(request.scope, counting_receive,
                                          request._send))

        return handler


router = APIRouter(prefix="/api/app", tags=["M1 App"],
                   dependencies=[rate_limit_user(times=300)],
                   route_class=_SubmitSizeLimitRoute)

DASHBOARD_SECTIONS = ["profile", "balances", "counters", "homework",
                      "schedule_week", "stat_marks", "stat_marks_year"]

def _upstream_error(status: int, data: Any) -> ApiError:
    """4xx/5xx від mapi → чесний конверт ok:false з тим самим статусом.

    Раніше операції shop/clubs/contacts повертали 200 + ok:true,
    а код помилки лежав усередині data.status — це порушувало контракт
    {ok, data, meta, error} (помилка мусить бути ok:false + error[])."""
    message = f"mystat_error_{status}"
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict) and first.get("message"):
            message = str(first["message"])[:300]
    elif isinstance(data, dict):
        for key in ("error", "message"):
            value = data.get(key)
            if isinstance(value, str) and value:
                message = value[:300]
                break
            if isinstance(value, dict) and value.get("message"):
                message = str(value["message"])[:300]
                break
    mapped = 502 if status >= 500 else status
    return ApiError(mapped, "mystat_error", "__all__", message)


def _get_account(db: Session, user: User, account_id: int | None) -> MystatAccount:
    q = db.query(MystatAccount).filter(MystatAccount.user_id == user.id)
    if account_id is not None:
        # __account — публічний номер акаунта користувача (user_seq)
        account = q.filter(MystatAccount.user_seq == account_id).first()
    else:
        # віддаємо перевагу активному акаунту: needs_relogin першого не мусить
        # валить усе дашборда, якщо поруч є робочий
        account = (q.filter(MystatAccount.status == "active")
                   .order_by(MystatAccount.id).first())
        if account is None:
            account = q.order_by(MystatAccount.id).first()
    if account is None:
        from app.core.responses import ApiError

        raise ApiError(404, "account_not_found", "__all__",
                       "link_mystat_account_first")
    return account


@router.get("/dashboard")
async def dashboard(__account: int | None = Query(default=None, alias="__account"),
                    force: bool = Query(default=False),
                    db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)) -> dict:
    """Усе для головного екрана ОДНИМ викликом."""
    account = _get_account(db, user, __account)
    payloads = await app_data.get_payloads(db, account, DASHBOARD_SECTIONS,
                                           force=force)
    view = app_data.dashboard_view(payloads)
    # один запит замість N+1 (по запиту на секцію)
    rows = (db.query(app_data.Snapshot.section, app_data.Snapshot.fetched_at)
            .filter(app_data.Snapshot.account_id == account.id,
                    app_data.Snapshot.section.in_(DASHBOARD_SECTIONS))
            .all())
    fetched_at = dict(rows)
    view["meta"] = {
        k: (v.isoformat() if v else None) for k, v in fetched_at.items()
    }
    return ok(view)


@router.get("/homework")
async def homework(__account: int | None = Query(default=None, alias="__account"),
                   force: bool = Query(default=False),
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)) -> dict:
    """Усі статуси домашки одним викликом, нормалізовано."""
    account = _get_account(db, user, __account)
    payloads = await app_data.get_payloads(
        db, account, ["homework"], force=force)
    return ok(app_data.homework_view(payloads))


@router.get("/homework/{homework_id}")
async def homework_card(
    homework_id: int,
    __account: int | None = Query(default=None, alias="__account"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)) -> dict:
    """Повна картка ДЗ: викладач, опис, файли, відповідь учня, історія."""
    account = _get_account(db, user, __account)
    card = await app_data.homework_card(db, account, homework_id)
    return ok(app_data.homework_card_view(card))


@router.post("/homework/{homework_id}/submit")
async def homework_submit(
    homework_id: int,
    comment: str = Form(default=""),
    files: list[UploadFile] = File(default=[]),
    zip_mode: str = Form(default="auto", description=(
        "auto | always | off: коли пакувати файли в один .zip "
        "(mapi приймає лише один файл на здачу).")),
    zip_name: str = Form(default="", description=(
        "Ім'я архіва без розширення (за замовчуванням homework-{id}).")),
    compress_level: int = Form(default=6, ge=0, le=9, description=(
        "Ступінь стиснення zip: 0 = без стиснення, 1 = найшвидше, "
        "9 = максимальне.")),
    rename: bool = Form(default=True, description=(
        "Переіменовувати файли у «Прізвище_Ім'я»; false = лишити "
        "оригінальні імена.")),
    link: str = Form(default="", description=(
        "Зовнішнє посилання замість файлу на fs-сервері itstep — лягає у "
        "filename /homework/create, MyStat відкриє його як файл розв'язку.")),
    provider: str = Form(default="itstep", description=(
        "itstep | m1: m1 = наше коротке посилання /api/v1/files/<slug>. "
        "Файли при цьому так само лягають на fs itstep, але в filename "
        "ідє посилання на нас (302 або сторінка-галерея).")),
    open_in_browser: bool = Form(default=False, description=(
        "Тільки provider=m1 + файли: якщо всі файли підтримувані "
        "(png/jpg/webp/mp4/webm, zip з фото) — відкриття показує "
        "сторінку-галерею замість редіректу на скачування.")),
    __account: int | None = Query(default=None, alias="__account"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)) -> dict:
    """Здача домашки (M4e): файл(и) ≤25МБ + коментар.

    mapi приймає лише один файл, тому:
      • кілька файлів → ЗАВЖДИ пакуються в один .zip (напряму надіслати
        кілька не можна);
      • один png/jpg → надсилається напряму (лише перейменовується);
      • один файл іншого формату → теж пакується в .zip;
      • усі файли/архів перейменовуються у «Прізвище_Ім'я» з профілю,
        якщо користувач не вказав свій текст (zip_name, підтримує
        {surname}/{name}/{n}).
    """
    if zip_mode not in ("auto", "always", "off"):
        raise ApiError(422, "hw_zip_mode_invalid", "zip_mode",
                       "must_be_auto_always_off")
    account = _get_account(db, user, __account)
    files = list(files or [])
    if len(files) > 50:
        raise ApiError(422, "hw_too_many_files", "files",
                       "max_50_files_per_submission")
    payload_files: list[tuple[str, bytes, str]] = []
    total_files_bytes = 0  # N-M10: сумарний ліміт усіх файлів здачі
    for f in files:
        # читаємо не більше за ліміт файлу І за залишок сумарного ліміту (+1 байт
        # для детекції перевищення): відмова до повного завантаження в пам'ять
        # (інакше 25МБ×N на кожен запит → ризик OOM під навантаженням)
        remaining = MAX_HOMEWORK_TOTAL_BYTES - total_files_bytes
        allowed = min(app_data.MAX_FILE_SIZE, max(remaining, 0))
        data = await f.read(allowed + 1)
        if len(data) > allowed:
            if len(data) > app_data.MAX_FILE_SIZE:
                raise ApiError(422, "hw_file_too_large", "files",
                               f.filename or "file.bin")
            raise ApiError(413, "hw_payload_too_large", "files",
                           "total_files_size_exceeds_60mb")
        total_files_bytes += len(data)
        payload_files.append((f.filename or "file.bin", data,
                              f.content_type or "application/octet-stream"))
    result = await app_data.submit_homework(db, account, homework_id,
                                            comment, payload_files,
                                            zip_mode=zip_mode,
                                            zip_name=zip_name,
                                            compress_level=compress_level,
                                            rename=rename, link=link,
                                            provider=provider,
                                            open_in_browser=open_in_browser)
    return ok(result)


@router.delete("/homework/{homework_id}/submission")
async def homework_delete_submission(
    homework_id: int,
    __account: int | None = Query(default=None, alias="__account"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)) -> dict:
    """Видалити здану роботу, поки вона «на перевірці»."""
    account = _get_account(db, user, __account)
    return ok(await app_data.delete_submission(db, account, homework_id))


@router.get("/schedule")
async def schedule(
    kind: str = Query(default="week", pattern="^(week|month)$"),
    date: str | None = Query(default=None,
                             description="ISO: YYYY-MM-DD для week, YYYY-MM для month"),
    __account: int | None = Query(default=None, alias="__account"),
    force: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)) -> dict:
    """Розклад на будь-який тиждень/місяць (mapi нормалізує дату до Пн–Нд)."""
    account = _get_account(db, user, __account)

    if kind == "week":
        from datetime import date as _date, timedelta as _td

        try:
            # B6: дефолт — київська дата (одне джерело часу,
            # див. _server_today)
            from app.routers.app_api import _server_today as _srv_today
            if date is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                raise ValueError("bad_week_date_format")
            d = (_date.fromisoformat(date) if date else _srv_today())
        except ValueError:
            raise ApiError(422, "bad_date", "date",
                           "date_must_be_ISO_YYYY-MM-DD")
        monday = d - _td(days=d.weekday())
        section = f"schedule_week@{monday.isoformat()}"
    else:
        if date is not None and not _MONTH_RE.fullmatch(date):
            raise ApiError(422, "bad_date", "date",
                           "month_must_be_YYYY-MM")
        section = f"schedule_month@{date or _today_ym()}"

    payloads = await app_data.get_payloads(db, account, [section], force=force)
    return ok(app_data.schedule_view(payloads, section))


def _server_today():
    """ЄДИНЕ ДЖЕРЕЛО ЧАСУ для schedule-фільтрів (B6): «сьогодні» за КИЇВСЬКИМ
    часом (core.clock), а не за локальною зоною сервера. mapi-дати розкладу
    живуть у київській зоні, тож на сервері в іншій зоні «сьогодні» не
    зсувається. Мікс UTC і локального часу тут заборонений."""
    return naive_kyiv_now().date()


def _today_ym() -> str:
    return _server_today().strftime("%Y-%m")


@router.get("/activity")
async def activity(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=50),
    __account: int | None = Query(default=None, alias="__account"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)) -> dict:
    """Стрічка нарахувань (progress/activity) з пагінацією."""
    account = _get_account(db, user, __account)
    result = await app_data.activity_page(db, account, page, per_page)
    return ok(result)


@router.get("/marks")
async def marks(period: str = Query(default="year", pattern="^(month|year)$"),
                __account: int | None = Query(default=None, alias="__account"),
                force: bool = Query(default=False),
                db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> dict:
    """Оцінки: середні по предметах + останні оцінки."""
    account = _get_account(db, user, __account)
    section = "stat_marks_year" if period == "year" else "stat_marks"
    payloads = await app_data.get_payloads(db, account, [section], force=force)
    if section not in payloads and period == "month":
        payloads.update(await app_data.get_payloads(
            db, account, ["stat_marks_year"], force=force))
    return ok(app_data.marks_view(payloads))


@router.get("/news")
async def news(__account: int | None = Query(default=None, alias="__account"),
               force: bool = Query(default=False),
               db: Session = Depends(get_db),
               user: User = Depends(get_current_user)) -> dict:
    """Новини: стрічка для картки на Головній + модалки."""
    account = _get_account(db, user, __account)
    payloads = await app_data.get_payloads(db, account, ["news"], force=force)
    return ok(app_data.news_view(payloads))


@router.get("/news/{news_id}")
async def news_item(
        news_id: int,
        __account: int | None = Query(default=None, alias="__account"),
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user)) -> dict:
    """Повний текст новини (живий запит, HTML)."""
    account = _get_account(db, user, __account)
    return ok(await app_data.news_detail(db, account, news_id))


@router.get("/reference-data")
async def reference_data(
        type: int = Query(default=1),
        __account: int | None = Query(default=None, alias="__account"),
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user)):
    """Довідка (файл з MyStat, blob) — проксі із content-disposition."""
    account = _get_account(db, user, __account)
    content, media, cd = await app_data.reference_file(db, account, type)
    headers = {"Content-Disposition":
               cd or 'attachment; filename="dovidka.pdf"'}
    return Response(content=content, media_type=media, headers=headers)


@router.post("/contacts/send",
             dependencies=[rate_limit_user(times=5, per_seconds=600,
                                           name="contacts_send")])
async def contacts_send(data: dict,
                        __account: int | None = Query(default=None,
                                                      alias="__account"),
                        db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)) -> dict:
    """Написати директору/викладачу: {subject, message[, target, teacher]}."""
    subject = str(data.get("subject") or "").strip()
    message = str(data.get("message") or "").strip()
    target = str(data.get("target") or "ceo").strip()
    teacher = str(data.get("teacher") or "").strip() or None
    if (len(subject) > MAX_CONTACT_SUBJECT
            or len(message) > MAX_CONTACT_MESSAGE
            or (teacher is not None and len(teacher) > MAX_CONTACT_TEACHER)):
        raise ApiError(422, "validation_error", "__all__",
                       "subject_or_message_too_long")
    if target not in ("ceo", "teach"):
        raise ApiError(422, "validation_error", "target", "bad_target")
    # як у формі офіційного MyStat: тема й текст — щонайменше 3 символи
    if len(subject) < 3 or len(message) < 3:
        raise ApiError(422, "validation_error", "__all__",
                       "subject_and_message_required")
    # викладач адресується за числовим id_teach (не ПІБ)
    if target == "teach" and not (teacher and re.fullmatch(r"[0-9]{1,12}", teacher)):
        raise ApiError(422, "validation_error", "teacher",
                       "teacher_required")
    account = _get_account(db, user, __account)
    result = await app_data.contacts_send(db, account, subject, message,
                                          target, teacher)
    st = int(result.get("status") or 0)
    if st >= 400:
        raise _upstream_error(st, result.get("data"))
    return ok(result)


@router.post("/clubs/buy")
async def clubs_buy(data: dict,
                    __account: int | None = Query(default=None,
                                                  alias="__account"),
                    db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)) -> dict:
    """Придбати абонемент: {club_id, abonement_id} (з бандла MyStat)."""
    try:
        club_id = int(data.get("club_id") or 0)
        abonement_id = int(data.get("abonement_id") or 0)
    except (TypeError, ValueError):
        club_id = abonement_id = 0
    if club_id <= 0 or abonement_id <= 0:
        raise ApiError(422, "validation_error", "__all__",
                       "club_and_abonement_required")
    account = _get_account(db, user, __account)
    result = await app_data.club_buy(db, account, club_id, abonement_id)
    st = int(result.get("status") or 0)
    if st >= 400:
        raise _upstream_error(st, result.get("data"))
    return ok(result)


@router.get("/payments")
async def payments(__account: int | None = Query(default=None, alias="__account"),
                   force: bool = Query(default=False),
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)) -> dict:
    """Платежі: зведення, борг, наступний платіж, історія."""
    account = _get_account(db, user, __account)
    payloads = await app_data.get_payloads(
        db, account,
        ["payment_info", "payment_next", "payment_history", "payment_schedule"],
        force=force)
    return ok(app_data.payments_view(payloads))


@router.get("/clubs")
async def clubs(__account: int | None = Query(default=None, alias="__account"),
                force: bool = Query(default=False),
                db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> dict:
    """Клуби філії: каталог, абонементи, баланс, транзакції."""
    if not app_data.CLUBS_ENABLED:
        raise ApiError(404, "clubs_disabled", "__all__", "feature_disabled")
    account = _get_account(db, user, __account)
    payloads = await app_data.get_payloads(
        db, account,
        ["clubs", "club_abonements", "club_balance", "club_transactions"],
        force=force)
    return ok(app_data.clubs_view(payloads))


@router.get("/contacts")
async def contacts(__account: int | None = Query(default=None, alias="__account"),
                   force: bool = Query(default=False),
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)) -> dict:
    """Контакти філії (адреса, телефони, соцмережі, навчальна частина)."""
    account = _get_account(db, user, __account)
    payloads = await app_data.get_payloads(db, account, ["contacts"],
                                           force=force)
    return ok(app_data.contacts_view(payloads, account.branch_alias or ""))


class AwardsBuyIn(BaseModel):
    items: list[int] = Field(min_length=1, max_length=50,
                             description="[<id предмета з каталогу>]")


class AwardsEquipIn(BaseModel):
    item_id: int = Field(ge=1)


@router.get("/awards")
async def awards(__account: int | None = Query(default=None, alias="__account"),
                 force: bool = Query(default=False),
                 db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)) -> dict:
    """Нагороди: баланс бобрів + каталог предметів аватара по категоріях."""
    account = _get_account(db, user, __account)
    payloads = await app_data.get_payloads(
        db, account, ["awards_items", "awards_balance"], force=force)
    return ok(app_data.awards_view(payloads))


@router.post("/awards/buy")
async def awards_buy(body: AwardsBuyIn,
                     __account: int | None = Query(default=None, alias="__account"),
                     db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)) -> dict:
    """Купівля предметів аватара за бобрів (POST /custom-awards/items/buy).
    Код mapi прокидуємо як є: 4xx — напр. недостатньо бобрів."""
    account = _get_account(db, user, __account)
    result = await app_data.awards_buy(db, account, body.items)
    st = int(result.get("status") or 0)
    if st >= 400:
        raise _upstream_error(st, result.get("data"))
    return ok(result)


@router.post("/awards/equip")
async def awards_equip(body: AwardsEquipIn,
                       __account: int | None = Query(default=None, alias="__account"),
                       db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)) -> dict:
    """Надіти предмет на аватар (POST /custom-awards/items/equip)."""
    account = _get_account(db, user, __account)
    result = await app_data.awards_equip(db, account, body.item_id)
    st = int(result.get("status") or 0)
    if st >= 400:
        raise _upstream_error(st, result.get("data"))
    return ok(result)


@router.get("/progress")
async def progress(__account: int | None = Query(default=None, alias="__account"),
                   force: bool = Query(default=False),
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)) -> dict:
    """Прогрес: графіки середнього балу по місяцях (statistic/progress)."""
    account = _get_account(db, user, __account)
    payloads = await app_data.get_payloads(db, account, ["stat_progress"],
                                           force=force)
    return ok(app_data.progress_view(payloads))


@router.get("/shop")
async def shop(__account: int | None = Query(default=None, alias="__account"),
               force: bool = Query(default=False),
               db: Session = Depends(get_db),
               user: User = Depends(get_current_user)) -> dict:
    """Магазин: каталог + мої замовлення одним викликом."""
    account = _get_account(db, user, __account)
    payloads = await app_data.get_payloads(
        db, account, ["shop_products", "shop_orders"], force=force)
    return ok(app_data.shop_view(payloads))


@router.post("/shop/order")
async def shop_buy(
        product_id: int = Query(ge=1),
        quantity: int = Query(default=1, ge=1, le=10),
        __account: int | None = Query(default=None, alias="__account"),
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user)) -> dict:
    """Купівля за бонуси (merchant Gaming). Код mapi прокидуємо як є:
    201 — успіх, 4xx — напр. недостатньо монет."""
    account = _get_account(db, user, __account)
    result = await app_data.shop_create_order(db, account, product_id,
                                              quantity)
    st = int(result.get("status") or 0)
    if st >= 400:  # 4xx/5xx від mapi → ok:false, а не 200 з кодом усередині data
        raise _upstream_error(st, result.get("data"))
    return ok(result)


@router.delete("/shop/order/{uuid}")
async def shop_discard(
        uuid: str,
        __account: int | None = Query(default=None, alias="__account"),
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user)) -> dict:
    """Скасування замовлення (PUT /shop/discard-order {uuid})."""
    account = _get_account(db, user, __account)
    result = await app_data.shop_discard_order(db, account, uuid)
    st = int(result.get("status") or 0)
    if st >= 400:
        raise _upstream_error(st, result.get("data"))
    return ok(result)


@router.get("/qr")
async def qr_code(__account: int | None = Query(default=None, alias="__account"),
                  force: bool = Query(default=False),
                  db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)) -> dict:
    """QR-код студента (data:image/png;base64) для проходу."""
    account = _get_account(db, user, __account)
    payloads = await app_data.get_payloads(db, account, ["qr"], force=force)
    return ok(app_data.qr_view(payloads))


@router.get("/leaderboard")
async def leaderboard(
        __account: int | None = Query(default=None, alias="__account"),
        force: bool = Query(default=False),
        db: Session = Depends(get_db),
        user: User = Depends(get_current_user)) -> dict:
    """Лідерборд: позиція (points) + таблиці group/stream × month/all_time."""
    account = _get_account(db, user, __account)
    payloads = await app_data.get_payloads(
        db, account, ["leader_points", "leader_table"], force=force)
    return ok(app_data.leaderboard_view(payloads))
