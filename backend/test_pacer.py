"""Швидка перевірка RequestPacer (режим «по запитах»)."""
import asyncio
import time

from app.services.mapi_pacer import RequestPacer


async def main() -> None:
    # 8 запитів у вікні 16с -> інтервал 2с: перший t=0, останній t=14 (<=16)
    p = RequestPacer(16 / 8)

    async def w(i: int) -> float:
        await p.slot()
        return time.monotonic()

    t0 = time.monotonic()
    ts = sorted(await asyncio.gather(*(w(i) for i in range(8))))
    rel = [round(t - t0, 2) for t in ts]
    gaps = [round(b - a, 2) for a, b in zip(rel, rel[1:])]
    print("moments:", rel)
    print("gaps:", gaps)
    assert all(1.5 < g < 2.5 for g in gaps), gaps
    # після простою перший запит не чекає більше одного інтервалу
    # (таймлайн продовжується з моменту виклику, старі слоти не «наздоганяються»)
    await asyncio.sleep(1)
    t1 = time.monotonic()
    await p.slot()
    assert time.monotonic() - t1 <= 2.1, "слот після простою чекає надто довго"
    print("PACER OK")


asyncio.run(main())