"""Смоук-тест M1 Provider (links.db, /api/v1/files/{slug}).

Запуск: python smoke_test_m1link.py (потрібен віртуальний оточенні бека).
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi.testclient import TestClient  # noqa: E402


def main() -> int:
    from app.services import links as L
    from app.main import app

    L.init_links_db()
    client = TestClient(app)

    db = L.new_session()

    # 1) url-редірект
    r1 = L.create_link(target_url="https://youtube.com/watch?v=abc",
                       homework_id=1, hw_title="Тест", hw_subject="Математика")
    assert r1.slug and len(r1.slug) == 8, "slug base62 len8"

    # 2) колізії: другий slug інший
    r2 = L.create_link(target_url="https://x.example")
    assert r2.slug != r1.slug

    # 3) маніфест: підтримувані/непідтримувані файли
    png = (b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    ok_files = [("a.png", png, "image/png")]
    m = L.build_media_manifest(ok_files)
    assert m and m[0]["ext"] == "png"
    assert L.build_media_manifest([("a.exe", b"MZ", "x")]) is None
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as zf:
        zf.writestr("a.png", png)
        zf.writestr("b.png", png)
    assert L.build_media_manifest([("photos.zip", zbuf.getvalue(), "application/zip")]) \
        and len(L.build_media_manifest([("photos.zip", zbuf.getvalue(), "")])) == 2
    zbad = io.BytesIO()
    with zipfile.ZipFile(zbad, "w") as zf:
        zf.writestr("virus.exe", b"MZ")
    assert L.build_media_manifest([("bad.zip", zbad.getvalue(), "")]) is None

    # 4) file-редірект (галерея вимкнена)
    r3 = L.create_link(kind="file", target_url="https://fs.example/x.png",
                       homework_id=2, hw_title="ДЗ")
    resp = client.get(f"/api/v1/files/{r3.slug}", follow_redirects=False)
    assert resp.status_code == 302 and resp.headers["location"] == \
        "https://fs.example/x.png", resp.status_code

    # 5) file-галерея
    r4 = L.create_link(kind="file", target_url="https://fs.example/x.png",
                       homework_id=3, hw_title="Фото ДЗ", hw_subject="Фізика",
                       media=[{"name": "a.png", "ext": "png"}])
    resp = client.get(f"/api/v1/files/{r4.slug}", follow_redirects=False)
    assert resp.status_code == 200 and "Фото ДЗ" in resp.text
    assert "/api/v1/files/" in resp.text and "Скачати" in resp.text
    assert client.get(f"/api/v1/files/{r4.slug}/download",
                      follow_redirects=False).status_code == 302

    # 6) 404 + вилучення
    assert client.get("/api/v1/files/ZZZZZZZZ").status_code == 404
    r1.active = False
    db.merge(r1); db.commit()
    assert client.get(f"/api/v1/files/{r1.slug}").status_code in (404, 410)

    # 7) медіа: непідтримуваний контент → сторінка «Помилка»
    resp = client.get(f"/api/v1/files/{r4.slug}/media/0")
    assert resp.status_code == 502 and "Помилка" in resp.text

    # 8) статистика: register_open рахує
    before = L.new_session().get(L.M1Link, r3.slug).opens
    client.get(f"/api/v1/files/{r3.slug}", follow_redirects=False)
    after = L.new_session().get(L.M1Link, r3.slug).opens
    assert after == before + 1, (before, after)

    # 9) «неправильний» контент не віддається як зображення (сниф)
    assert L._sniff(b"MZ........") == ""
    assert L._sniff(b"\x89PNG\r\n\x1a\n") == "image/png"
    assert L._sniff(b"\xff\xd8\xff\xe0") == "image/jpeg"
    assert L._sniff(b"RIFF\x00\x00\x00\x00WEBP") == "image/webp"
    assert L._sniff(b"\x00\x00\x00\x20ftypisom") == "video/mp4"
    assert L._sniff(b"\x1a\x45\xdf\xa3") == "video/webm"

    print("smoke_test_m1link: OK —", r1.slug, r3.slug, r4.slug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
