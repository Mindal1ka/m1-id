"""Генератор PWA-іконок M1 ID без сторонніх бібліотек (чистий zlib+struct).

Малює: темний скруглений квадрат, кільце-акцент (індиго), ядро (ціан).
Запуск:  python scripts/make_icons.py  → static/icon-192.png, icon-512.png,
maskable-512.png
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "frontend" / "static"
BG = (11, 14, 20)        # #0b0e14
ACCENT = (108, 124, 255)  # #6c7cff
CYAN = (34, 211, 238)     # #22d3ee


def write_png(path: Path, w: int, h: int, pixels: list[list[tuple]]) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        raw = tag + data
        return struct.pack(">I", len(data)) + raw + struct.pack(">I", zlib.crc32(raw))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)  # RGBA8
    body = b"".join(
        b"\x00" + b"".join(struct.pack("BBBB", *px) for px in row)
        for row in pixels
    )
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(body, 9)) + chunk(b"IEND", b""))
    path.write_bytes(png)


def render(size: int, maskable: bool = False) -> list[list[tuple]]:
    s = size
    img = [[(*BG, 0)] * s for _ in range(s)]

    r = s * (0.0 if maskable else 0.22)  # у maskable — повний квадрат
    cx = cy = s / 2

    def inside_round(x: float, y: float) -> bool:
        if r <= 0:
            return True
        qx = min(x, s - x)
        qy = min(y, s - y)
        if qx >= r or qy >= r:
            return True
        return (qx - r) ** 2 + (qy - r) ** 2 <= r * r

    ring_r = s * (0.26 if maskable else 0.30)
    ring_w = s * (0.075 if maskable else 0.075)
    core_r = s * (0.10 if maskable else 0.115)

    for y in range(s):
        for x in range(s):
            if not inside_round(x + 0.5, y + 0.5):
                continue
            d = ((x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2) ** 0.5
            if abs(d - ring_r) <= ring_w / 2:
                img[y][x] = (*ACCENT, 255)
            elif d <= core_r:
                img[y][x] = (*CYAN, 255)

    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    write_png(OUT / "icon-192.png", 192, 192, render(192))
    write_png(OUT / "icon-512.png", 512, 512, render(512))
    write_png(OUT / "maskable-512.png", 512, 512, render(512, maskable=True))
    print("OK:", *(p.name for p in sorted(OUT.glob("*.png"))))


if __name__ == "__main__":
    main()
