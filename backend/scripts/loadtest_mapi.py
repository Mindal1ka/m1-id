"""Замоканий mapi для навантажувальних тестів: правдоподібні розміри відповідей."""
from __future__ import annotations

import asyncio
import uuid

import httpx

TOKEN_OK = "LOADTOK_aaaaaaaaaaaaaaaaaaaaaaaaaa"


def _marks(n: int) -> list[dict]:
    subjects = ["Алгебра", "Геометрія", "Фізика", "Хімія", "Історія",
                "Укр.мова", "Інформатика", "Англійська"]
    return [{
        "y": "2026", "m": str(1 + i % 12), "d": str(1 + i % 28),
        "mark": str(3 + i % 10), "name_spec": subjects[i % len(subjects)],
        "theme": f"Тема №{i}", "fio_teach": "Вчитель В. В.",
        "photo_pas": "", "comment": "",
    } for i in range(n)]


def _lessons(n: int, day: int) -> list[dict]:
    return [{
        "date": f"2026-08-{24 + day:02d}", "week_day": str(1 + day % 7),
        "lesson": (i % 8) + 1,
        "started_at": f"0{i % 8}:30:00", "finished_at": f"0{i % 8}:15:00",
        "subject_name": f"Предмет-{i % 9}", "lesson_theme": "Тема",
        "teacher_name": "Вчитель", "room_name": "201", "mark": 11,
        "attendance": "100", "was": 1, "was_type": None,
        "mark_type": 1, "homeworks": [], "video_link": None,
    } for i in range(n)]


def _hw(n: int) -> list[dict]:
    return [{"status": g, "data": [{
        "id": 100000 + i, "name_spec": f"Предмет-{i % 8}",
        "theme": f"ДЗ №{i}", "fio_teach": "Вчитель",
        "creation_time": "2026-08-20 10:00:00",
        "overdue_time": "2026-08-30 23:59:00",
        "status": g, "coins_to_close_deadline": 20,
        "is_autotest": False, "is_retake": False,
        "file_path": "", "homework_stud": {"mark": None},
    } for i in range(n)]} for g in (3, 2, 1)]


_ME = {"id": 0, "id_user_storage": 0, "name": "Навантаж Тест",
       "lang": "uk", "branch_alias": "pl",
       "user_profiles": {"50": {"4": [{"photo": "x.png"}]}}}

_SECTIONS: dict[str, object] = {
    "profile": _ME, "config": {"data": {"ok": 1}},
    "counters": [{"counter_type": f"c{i}", "counter": i} for i in range(20)],
    "balances": [{"alias": a, "value": 100}
                 for a in ("coins", "cristals", "achivements")],
    "schedule_week": {"data": _lessons(40, 0), "start_day": "2026-08-24"},
    "schedule_month": {"data": _lessons(160, 0), "start_day": "2026-08-01"},
    "homework": _hw(20),
    "stat_marks": _marks(40),
    "stat_marks_year": _marks(600),      # ~94 КБ як у живому API
    "stat_attendance": [{"d": 1}],
    "news": [{"id": i, "title": "Новина", "preview_text": "..." * 20,
              "image": "http://x/y.jpg", "is_viewed": i % 3 == 0,
              "published_at": "2026-08-20 10:00:00",
              "created_by_fullname": "Дирекція"} for i in range(15)],
    "shop_products": [{"id": i, "title": "Товар", "text": "..." * 10,
                       "image": ["http://x/y.jpg"], "quantity": 5,
                       "prices": [{"price": "231.00", "min_price": "100",
                                   "currency": "COI"}],
                       "properties": []} for i in range(20)],
    "shop_orders": [{"id": i, "uuid": str(uuid.uuid4()), "status": 4,
                     "created_at": "2026-08-20 10:00:00",
                     "can_discard": False,
                     "products": [{"product_id": 1, "title": "Товар",
                                   "quantity": 1, "image": ["u"],
                                   "order_product_price": [
                                       {"price": 196, "currency": "COI"}]}]}
                    for i in range(10)],
    "qr": "data:image/png;base64," + "A" * 1500,
    "leader_points": {"group": {"totalCount": 500, "studentPosition": 42},
                      "stream": {"totalCount": 2000, "studentPosition": 150}},
    "leader_table": {"group": {"month": {"top": [], "other": [],
                                         "new_students": []},
                               "all_time": {"top": [], "other": [],
                                            "new_students": []}},
                     "stream": {"month": {"top": [], "other": [],
                                          "new_students": []},
                                "all_time": {"top": [], "other": [],
                                             "new_students": []}}},
    "stat_progress": {"ok": 1},
    "payment": {"full_name": "Навантаж Тест", "student_cost": 3000},
    "payment_next": {"debtor_status": 0, "amount": 0},
    "payment_history": [], "payment_schedule": [],
    "clubs": [], "club_abonements": [], "club_balance": {"amount": 0},
    "club_transactions": [], "contacts": {"address": "Київ"},
    "custom_awards_items": [], "custom_awards_balance": {"amount": 0},
}


async def _handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    await asyncio.sleep(0.003)  # RTT mapi ~3мс
    if url.endswith("/v1/mystat/auth/me"):
        return httpx.Response(200, json=_ME)
    if url.endswith("/v1/mystat/auth/refresh"):
        return httpx.Response(200, text=TOKEN_OK)
    if "/schedule/get-month" in url:
        return httpx.Response(200, json=_SECTIONS["schedule_month"]
                              if "type=month" in url
                              else _SECTIONS["schedule_week"])
    if "/statistic/marks" in url:
        return httpx.Response(200, json=_SECTIONS["stat_marks_year"]
                              if "period=" not in url
                              else _SECTIONS["stat_marks"])
    for key in ("profile", "config", "counters", "balances", "homework",
                "stat_attendance", "news", "shop_products", "shop_orders",
                "qr", "leader_points", "leader_table", "stat_progress",
                "payment", "clubs", "club_abonements", "club_balance",
                "club_transactions", "contacts", "custom-awards/items",
                "custom-awards/balance"):
        if f"/{key}" in url:
            return httpx.Response(200, json=_SECTIONS.get(key, {"ok": 1}))
    if "/students/get-qr-code" in url:
        return httpx.Response(200, json=_SECTIONS["qr"])
    return httpx.Response(200, json={"ok": 1})


def install_mapi_mock() -> None:
    import app.services.mystat_client as ms

    ms.set_transport(sync=httpx.MockTransport(_handler),
                     async_=httpx.MockTransport(_handler))
