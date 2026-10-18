"""M3 smoke-test: агреговане /api/app/* у нашому форматі + кеш + асинхронність.

Мок mapi віддає урізані РЕАЛЬНІ структури (див. docs/live_shapes/).
Запуск:  python smoke_test_m3.py   (з папки backend)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import uuid

_tmp = tempfile.mkdtemp(prefix="m1id_m3_")
os.environ["M1ID_DB_URL"] = f"sqlite:///{_tmp}/test.db".replace("\\", "/")
os.environ["M1ID_SECRET_KEY"] = "test-secret-key-m3-0123456789abcdef-0123456789"
os.environ["M1ID_TELEGRAM_BOT_TOKEN"] = ''   # бот у smoke-тестах не стартує
os.environ["M1ID_EMAIL_MX_CHECK"] = "false"
os.environ["M1ID_DEBUG"] = "1"  # link-token — dev-ендпоінт

import json  # noqa: E402

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.services import mystat_client as ms  # noqa: E402

ME = {
    "id": 111213, "id_user_storage": 998877, "name": "Тестов Тест",
    "username": "test_user", "lang": "uk", "profile": "student",
    "branch_alias": "pl", "branch_id": 4, "project_id": 50,
    "user_profiles": {"50": {"4": [{"user_id": 998877,
                                    "photo": "p.png"}]}},
}

HW_ITEM = {
    "id": 131607, "name_spec": "Python", "theme": "Tkinter",
    "fio_teach": "Прилуцький О.", "creation_time": "2026-08-20",
    "overdue_time": "2027-10-12", "status": 3, "file_path": "f.zip",
    "is_autotest": 0, "completion_days": -5,
    "homework_stud": {"mark": None, "status": 6},
}
HW_DONE_ITEM = {**HW_ITEM, "id": 100, "status": 1, "completion_days": -100,
                "homework_stud": {"mark": 11, "status": 2}}

SCHEDULE = {
    "data": [
        {"date": "2026-05-02", "lesson": 2, "started_at": "12:10:00",
         "finished_at": "13:30:00", "teacher_name": "Великолуг М.",
         "subject_name": "AI Assistant", "room_name": "210 ауд.", "mark": 10,
         "week_day": "6", "attendance": "75", "was": 1},
        {"date": "2026-05-02", "lesson": 1, "started_at": "10:40:00",
         "finished_at": "12:10:00", "teacher_name": "Великолуг М.",
         "subject_name": "AI Assistant", "room_name": "210 ауд.", "mark": None,
         "week_day": "6", "attendance": "75", "was": 1},
    ],
    "start_day": "2026-05-01", "end_date": "2026-05-07",
}
MARKS = [
    {"mark_date": "2026-05-16", "mark": "12", "name_spec": "AI-геймплей",
     "theme": "Вступ", "fio_teach": "Кальницкий Н."},
    {"mark_date": "2026-05-10", "mark": "9", "name_spec": "AI-геймплей",
     "theme": "Сцена", "fio_teach": "Кальницкий Н."},
    {"mark_date": "2026-04-02", "mark": "11", "name_spec": "Python",
     "theme": "ООП", "fio_teach": "Прилуцький О."},
]
NEWS = [
    {"id": 137789, "title": "День відкритих дверей",
     "preview_text": "Запрошуємо", "image": "http://test/fs/news.jpg",
     "is_viewed": False, "mark": None,
     "published_at": "2026-08-20 14:40:37",
     "created_by_fullname": "Лилия Назарова"},
    {"id": 137700, "title": "Стара новина", "preview_text": "",
     "image": None, "is_viewed": True, "mark": 5,
     "published_at": "2026-06-01 10:00:00", "created_by_fullname": None},
]
NEWS_DETAIL = {"id": 137789, "title": "День відкритих дверей",
               "text": "<p>Привіт</p>",
               "preview_text": "", "image": "http://test/fs/news.jpg",
               "published_at": "2026-08-20 14:40:37",
               "created_by_fullname": "Лилия Назарова", "avg_mark": 4.5}
PRODUCTS = [
    {"id": 46000, "title": "Антистрес", "text": "кільце",
     "image": ["http://test/fs/p.jpg"], "quantity": 10,
     "properties": [{"name": "Color", "value": "Різнокольорові"},
                    {"name": "Material", "value": "Пластик"}],
     "prices": [{"price": "231.00", "currency": "COI"},
                {"price": "45.00", "currency": "DIA"}]},
    {"id": 46001, "title": "Кришталевий бонус", "text": "",
     "image": [], "quantity": 0,
     "prices": [{"price": "99.50", "currency": "DIA"}]},
]
ORDERS = [
    {"id": 489556, "uuid": "efc", "status": 5, "can_discard": True,
     "created_at": "2026-05-16T12:14:39.000000Z",
     "products": [{"product_id": 45976, "title": "Стікери", "quantity": 2,
                   "image": ["http://test/fs/o.jpg"],
                   "order_product_price": [{"price": 100, "currency": "COI"}]}]},
]
QR_DATA = "data:image/png;base64,iVBORw0KGgoAAAANS"
LEADER_POINTS = {"group": {"totalCount": 14, "studentPosition": 12,
                           "weekDiff": 0, "monthDiff": 0},
                 "stream": {"totalCount": 86, "studentPosition": 58,
                            "weekDiff": 0, "monthDiff": 0}}
LEADER_TABLE = {"group": {"month": {
    "new_students": [],
    "top": [{"id_stud": "14534", "fio_stud": "Яцун Іван", "photo": "p1.png",
             "amount": 174, "position": 1, "is_new": False},
            {"id_stud": "14432", "fio_stud": "Шевченко Я.", "photo": None,
             "amount": 160, "position": 2, "is_new": False}],
    "other": [{"id_stud": "14582", "fio_stud": "Мендєлєєв І.",
               "photo": None, "amount": 110, "position": 12,
               "is_new": False}]},
    "all_time": {"top": [], "other": [], "new_students": []}},
    "stream": {"month": {"top": [], "other": [], "new_students": []},
               "all_time": {"top": [], "other": [], "new_students": []}}}
BALANCES = [{"alias": "cristals", "value": 170, "rating": 446},
            {"alias": "coins", "value": 429, "rating": 1070}]
COUNTERS = [{"counter_type": "homework", "counter": 2}]

hit_counter = {"n": 0}


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "/v1/v1/" in url:
        return httpx.Response(404, json={"message": "double_v1_prefix_bug"})
    token = request.headers.get("authorization", "").replace("Bearer ", "")

    if url.endswith("/mystat/auth/me"):
        if request.method != "POST" or not token.startswith("TOK_OK"):
            return httpx.Response(401, json=[])
        hit_counter["n"] += 1
        return httpx.Response(200, json=ME)

    if not url.startswith("http://test/v1/mystat/pl/"):
        pass
    hit_counter["n"] += 1
    path = request.url.path
    if path.endswith("/homework/list"):
        # жива форма: список груп [{status, data}, ...], параметри ігноруються
        return httpx.Response(200, json=[
            {"status": 3, "data": [HW_ITEM]},
            {"status": 2, "data": []},
            {"status": 1, "data": [HW_DONE_ITEM]},
        ])
    if path.endswith("/user/file-token"):
        return httpx.Response(200, json={
            "url": "http://test/fs", "token": "FJWT",
            "directories": {"homeworkDirId": "HWDIRHASH"}})
    if path == "/fs":
        # файловий сервер: multipart directory + files[] → посилання
        body = request.content.decode("utf-8", "replace")
        if "HWDIRHASH" not in body or "FJWT" not in \
                request.headers.get("authorization", ""):
            return httpx.Response(403, json={"message": "bad upload"})
        return httpx.Response(200, json=[
            {"token": "f1", "link": "http://test/fs/f1"}])
    if path.endswith("/homework/create"):
        # єдиний живий контракт: application/json answerText/filename
        if request.headers.get("content-type", "").startswith(
                "application/json"):
            try:
                payload = json.loads(request.content)
            except Exception:
                payload = {}
            if payload.get("id") != 131607:
                return httpx.Response(400, json={
                    "name": "Bad Request",
                    "message": "Missing required parameter", "status": 400})
            if payload.get("answerText") == "REJECT":
                return httpx.Response(422, json={
                    "name": "Unprocessable entity",
                    "message": "Can't save homework",
                    "code": 3004, "status": 422})
            return httpx.Response(201, json={
                "id": 900, "status": 2, "file_path": None,
                "stud_answer": "", "communication_history": [
                    {"type_name": "homework_student_comment",
                     "comment": payload.get("answerText") or "",
                     "date": "2026-08-26 01:01:20", "file": None}]})
        return httpx.Response(400, json={
            "name": "Bad Request", "message": "Missing required parameter",
            "status": 400})
    if path.endswith("/schedule/get-month"):
        kind = request.url.params.get("type")
        df = request.url.params.get("date_filter", "")
        if kind == "week":
            # нормалізація до Пн тижня, як робить mapi
            from datetime import date as _d, timedelta as _td

            if df and df != "понеділок":
                base = _d.fromisoformat(df)
            else:
                base = _d(2026, 8, 24)
            monday = base - _td(days=base.weekday())
            body = {**SCHEDULE, "start_day": "2026-05-01"}
            if monday.isoformat() == "2026-05-04":
                body = dict(SCHEDULE)
            return httpx.Response(200, json=body)
        return httpx.Response(200, json={"data": []})
    if path.endswith("/statistic/marks"):
        # план синка запитує без period → повна історія (фікстура MARKS);
        # period=month (секція stat_marks) лишається порожньою
        return httpx.Response(200, json=MARKS
                              if not request.url.params.get("period") else [])
    if path.endswith("/news"):
        return httpx.Response(200, json=NEWS)
    if "/news/" in path:
        return httpx.Response(200, json=NEWS_DETAIL)
    if path.endswith("/shop/products"):
        return httpx.Response(200, json=PRODUCTS)
    if path.endswith("/shop/orders"):
        return httpx.Response(200, json=ORDERS)
    if path.endswith("/shop/create-order"):
        return httpx.Response(201, json={"id": 489600, "status": 1})
    if path.endswith("/shop/discard-order"):
        return httpx.Response(200, json={"result": True})
    if path.endswith("/students/get-qr-code"):
        return httpx.Response(200, json=QR_DATA)
    if path.endswith("/progress/leader-points"):
        return httpx.Response(200, json=LEADER_POINTS)
    if path.endswith("/progress/leader-table"):
        return httpx.Response(200, json=LEADER_TABLE)
    if path.endswith("/gaming/get-balances"):
        return httpx.Response(200, json=BALANCES)
    if path.endswith("/count/page-counters"):
        return httpx.Response(200, json=COUNTERS)
    if path.endswith("/config") or "/news" in path or "/custom-awards/" in path \
            or "/statistic/" in path:
        return httpx.Response(200, json={"ok": True})
    return httpx.Response(200, json={})


ms.set_transport(sync=httpx.MockTransport(handler),
                 async_=httpx.MockTransport(handler))

from app.main import app  # noqa: E402

# Демо-тиждень розкладу не повинен перехоплювати фікстури тестів:
# зсуваємо його тригер у минуле (при видаленні демо-файлу блок мовчить).
try:
    from app.services import demo_schedule as _demo
    _demo.DEMO_MONDAY = "2000-01-03"
except ImportError:
    pass

passed = failed = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra and not cond else ""))


UNIQ = uuid.uuid4().hex[:10]
with TestClient(app) as c:
    r = c.post("/api/auth/register", json={
        "username": f"m3_{UNIQ}", "password": "SuperSecret1!",
        "email": f"{UNIQ}@example.com"})
    H = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}

    r = c.post("/api/accounts/link-token",
               json={"access_token": "TOK_OK_aaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
               headers=H)
    if r.status_code != 200:
        print("LINK-TOKEN ВІДПОВІДЬ:", r.status_code, r.text[:400])
        sys.exit(1)
    AID = r.json()["data"]["account"]["id"]
    check("акаунт прив'язано", r.status_code == 200)

    # чекаємо завершення фонового синку
    deadline = time.time() + 20
    while time.time() < deadline:
        st = c.get(f"/api/accounts/{AID}/sync/status", headers=H).json()["data"]
        if st.get("status") in ("done", "error"):
            break
        time.sleep(0.2)
    check("асинхронний синк завершено", st.get("status") == "done",
          str(st)[:300])

    hits_after_sync = hit_counter["n"]

    # ---------- dashboard одним викликом ----------
    r = c.get(f"/api/app/dashboard?__account={AID}", headers=H)
    d = r.json()["data"]
    check("dashboard → наш формат user/balances/homework/marks/meta",
          r.status_code == 200 and set(d) >= {
              "user", "balances", "homework_counts",
              "nearest_deadlines", "today_lessons", "marks_summary", "meta"})
    check("user із живої структури (fio/branch/photo)",
          d["user"]["fio"] == "Тестов Тест" and d["user"]["branch_alias"] == "pl"
          and d["user"]["photo_url"] == "p.png")
    check("баланси нормалізовано (іконки/rating)",
          any(i["key"] == "cristals" and i["value"] == 170 and i["rating"] == 446
              for i in d["balances"]["items"]))
    check("лічильники unread_counters словником",
          d["balances"]["unread_counters"].get("homework") == 2)
    # регресія: schedule_view мусить читати снапшот «schedule_week»,
    # а не неіснуючий ключ «week» (інакше картка дня/тижня порожня)
    check("дашборд бере РОЗКЛАД тижня (не порожній ключ «week»)",
          d["week_lessons_total"] == 2 and isinstance(d["today_lessons"], list),
          f"week_lessons_total={d.get('week_lessons_total')}, "
          f"days={len((d.get('today_lessons') or []))}")
    check("домашку пораховано за групами",
          d["homework_counts"] == {"pending": 1, "checking": 0,
                                   "done": 1})
    check("найближчі дедлайни відсортовано й нормалізовано",
          len(d["nearest_deadlines"]) == 1
          and d["nearest_deadlines"][0]["due"] == "2027-10-12"
          and d["nearest_deadlines"][0]["subject"] == "Python")

    # ---------- кеш: другий виклик не б'є в mapi ----------
    hits_before = hit_counter["n"]
    c.get(f"/api/app/dashboard?__account={AID}", headers=H)
    check("TTL-кеш працює (0 нових запитів до mapi)",
          hit_counter["n"] == hits_before,
          f"{hits_before} → {hit_counter['n']}")

    # force=1 обходить кеш
    c.get(f"/api/app/dashboard?__account={AID}&force=true", headers=H)
    check("force=true оновлює секції з mapi", hit_counter["n"] > hits_before)

    # ---------- homework ----------
    hw = c.get(f"/api/app/homework?__account={AID}", headers=H).json()["data"]
    check("homework: плаский список + counts + subjects + тип/прострочення",
          hw["counts"] == {"pending": 1, "checking": 0, "done": 1}
          and hw["items"][0]["title"] == "Tkinter"
          and hw["items"][0]["status_label"] == "до виконання"
          and hw["items"][0]["overdue_days"] == 5
          and hw["items"][0]["is_test"] is False
          and hw["items"][-1]["mark"] == 11
          and hw["items"][-1]["overdue_days"] == 0
          and hw["subjects"] == ["Python"]
          and hw["total"] == 2)

    # ---------- schedule ----------
    sch = c.get(f"/api/app/schedule?kind=week&__account={AID}",
                headers=H).json()["data"]
    day0 = sch["days"][0]
    check("schedule згруповано за днями й відсортовано за номером пари",
          len(sch["days"]) == 1 and sch["days"][0]["date"] == "2026-05-02"
          and [l["start"] for l in day0["lessons"]] == ["10:40", "12:10"]
          and day0["lessons"][0]["weekday"] == "Сб")

    # гортання: довільна дата → своя секція кешу, нормалізація до Пн
    r1 = c.get(f"/api/app/schedule?kind=week&date=2026-05-06&__account={AID}",
               headers=H).json()["data"]
    check("гортання тижнів: дату нормалізовано до Пн (section key)",
          r1.get("section") == "schedule_week@2026-05-04"
          and r1["range"].get("start_day") == "2026-05-01")
    hits_mid = hit_counter["n"]
    c.get(f"/api/app/schedule?kind=week&date=2026-05-07&__account={AID}",
          headers=H)
    check("той самий тиждень з іншої дати → з кешу",
          hit_counter["n"] == hits_mid)

    # ---------- marks ----------
    mk = c.get(f"/api/app/marks?period=year&__account={AID}",
               headers=H).json()["data"]
    ai = next(s for s in mk["subjects"] if s["subject"] == "AI-геймплей")
    check("marks: середні за предметами (10.5) + загальний середній",
          ai["avg"] == 10.5 and ai["count"] == 2
          and mk["overall_avg"] == 10.7
          and mk["recent"][0]["date"] == "2026-05-16")

    # ---------- news / shop (M5) ----------
    nw = c.get(f"/api/app/news?__account={AID}",
               headers=H).json()["data"]
    check("news: стрічка + unread за is_viewed",
          len(nw["items"]) == 2 and nw["unread"] == 1
          and nw["items"][0]["id"] == 137789,
          str(nw)[:220])
    nd = c.get(f"/api/app/news/137789?__account={AID}",
               headers=H).json()["data"]
    check("news detail: живий текст новини",
          nd["title"] == "День відкритих дверей" and nd["avg_mark"] == 4.5)
    sh = c.get(f"/api/app/shop?__account={AID}",
               headers=H).json()["data"]
    p0 = sh["products"][0]
    check("shop: каталог нормалізовано (ціна/валюта/картинка)",
          p0["price"] == "231.00" and p0["currency"] == "coins"
          and p0["image"] == "http://test/fs/p.jpg"
          and [x["currency"] for x in p0["prices"]] == ["coins", "cristals"]
          and p0["properties"][0]["name"] == "Color"
          and sh["products"][1]["currency"] == "cristals",
          str(sh["products"])[:260])
    o0 = sh["orders"][0]
    check("shop: замовлення → позиції/сума/статус/can_discard/archived",
          o0["total"] == 200.0 and o0["currency"] == "coins"
          and o0["status_label"] == "скасовано"
          and o0["items"][0]["title"] == "Стікери"
          and o0["can_discard"] is True and o0["archived"] is True,
          str(o0)[:220])

    r = c.post(
        f"/api/app/shop/order?product_id=46000&quantity=1&__account={AID}",
        headers=H)
    check("shop buy: create-order → код mapi 201 прокинуто",
          r.status_code == 200 and r.json()["data"]["status"] == 201,
          str(r.json())[:220])
    hits_before = hit_counter["n"]
    c.get(f"/api/app/shop?__account={AID}", headers=H)
    check("після покупки кеш shop інвалідовано (live-дозапит)",
          hit_counter["n"] > hits_before)
    r = c.delete(f"/api/app/shop/order/efc?__account={AID}", headers=H)
    check("shop discard: PUT {uuid} → 200",
          r.status_code == 200 and r.json()["data"]["status"] == 200,
          str(r.json())[:220])

    # ---------- qr / лідерборд (M5) ----------
    q = c.get(f"/api/app/qr?__account={AID}", headers=H).json()["data"]
    check("qr: рядок data:image із live-відповіді",
          q["qr"].startswith("data:image/png;base64,"), str(q)[:120])
    lb = c.get(f"/api/app/leaderboard?__account={AID}",
               headers=H).json()["data"]
    check("leaderboard: гілка академії визначена (є all_time)",
          lb["branch"] == "academy", str(lb.get("branch")))
    check("leaderboard: points нормалізовано",
          lb["points"]["group"]["position"] == 12
          and lb["points"]["group"]["total"] == 14,
          str(lb["points"])[:160])
    g = lb["sections"]["group"]["month"]
    check("leaderboard: секції top/nearby/new_students роздільно",
          [r["position"] for r in g["top"]] == [1, 2]
          and [r["position"] for r in g["nearby"]] == [12]
          and g["nearby"][0]["fio"] == "Мендєлєєв І."
          and g["nearby"][0]["amount"] == 110
          and g["new_students"] == [],
          str(g)[:260])
    check("leaderboard: періоди динамічні (академія: month+all_time, укр)",
          [p["key"] for p in lb["scopes"][0]["periods"]]
          == ["month", "all_time"]
          and lb["scopes"][0]["periods"][1]["label"] == "За весь час"
          and lb["scopes"][0]["label"] == "Група",
          str(lb["scopes"])[:200])
    check("leaderboard: all_time секція дісталась клієнту",
          "all_time" in lb["sections"]["group"]
          and "all_time" in lb["sections"]["stream"],
          str(list(lb["sections"].keys())))

    # ---------- здача домашки (M4e) ----------
    r = c.post(f"/api/app/homework/131607/submit?__account={AID}",
               headers=H,
               data={"comment": "Моє рішення"},
               files={"files": ("a.txt", b"M1 ID test", "text/plain")})
    sub = r.json()["data"] if r.status_code == 200 else {}
    check("здача ДЗ: file-token → upload → create → 201",
          r.status_code == 200 and sub.get("submission_id") == 900
          and sub.get("status") == 2
          and sub.get("files") == ["http://test/fs/f1"],
          str(r.json())[:250])
    # кеш домашки інвалідовано → наступний запит ходить у mapi
    hits_before = hit_counter["n"]
    c.get(f"/api/app/homework?__account={AID}", headers=H)
    check("після здачі кеш домашки інвалідовано (live-дозапит)",
          hit_counter["n"] > hits_before)

    r = c.post(f"/api/app/homework/131607/submit?__account={AID}",
               headers=H,
               data={"comment": "REJECT"},
               files={"files": ("a.txt", b"x", "text/plain")})
    check("mapi відмовив (422/3004) → hw_submit_rejected, не 500",
          r.status_code == 422
          and r.json()["error"][0]["code"] == "hw_submit_rejected",
          str(r.json())[:200])

    r = c.post(f"/api/app/homework/131607/submit?__account={AID}",
               headers=H, data={"comment": ""})
    check("без файлу → 422 hw_file_required (answer-only API не приймає)",
          r.status_code == 422
          and r.json()["error"][0]["code"] == "hw_file_required",
          str(r.json())[:200])

    # ---------- нечитабельний токен (після «рестарту» з іншим ключем) ----------
    from app.core.security import encrypt_secret as _es
    from app.db.base import SessionLocal as _SL
    from app.db.models import MystatAccount as _MA

    _db = _SL()
    _acc = _db.get(_MA, AID)
    _acc.access_token_enc = "garbage-not-a-fernet-token"
    _db.commit()
    _db.close()

    r = c.get(f"/api/app/dashboard?__account={AID}&force=true", headers=H)
    check("нечитабельний токен + force (потрібен live) → 401 needs_relogin (не 500)",
          r.status_code == 401
          and r.json()["error"][0]["code"] == "account_needs_relogin",
          str(r.json())[:200])
    r = c.get(f"/api/mystat/v1/mystat/pl/count/page-counters?__account={AID}",
              headers=H)
    check("проксі завжди live → теж needs_relogin",
          r.status_code == 401
          and r.json()["error"][0]["code"] == "account_needs_relogin")

    accs = c.get("/api/accounts", headers=H).json()["data"]
    check("статус акаунта перемкнено на needs_relogin",
          accs[0]["status"] == "needs_relogin")

    # кеш усе одно віддається (офлайн-first) — дані не зникли
    d2 = c.get(f"/api/app/dashboard?__account={AID}", headers=H).json()
    check("офлайн-first: свіжий кеш читається навіть із битим токеном",
          d2["ok"] is True and d2["data"]["user"]["fio"] == "Тестов Тест")

print(f"\nПідсумок M3: {passed} PASS / {failed} FAIL")
sys.exit(1 if failed else 0)
