"""Швидка перевірка pacування автооцінювань (notify_socket)."""
from __future__ import annotations

import time

from app.services import notify_socket as ns


def main() -> None:
    acc = 99999  # фейковий акаунт, щоб не зачепити стан інших тестів

    # перші 4 — без затримки
    delays = [ns._eval_claim_slot(acc) for _ in range(4)]
    assert all(d == 0.0 for d in delays), delays

    # 5-те і далі — по ~5с одна за одною
    d5 = ns._eval_claim_slot(acc)
    assert 4.0 < d5 <= 5.5, f"5-е оцінювання: {d5}"
    d6 = ns._eval_claim_slot(acc)
    assert 9.0 < d6 <= 10.5, f"6-е оцінювання: {d6}"  # 5с після попереднього слота

    # інший акаунт — свій незайманий бюджет
    d_other = ns._eval_claim_slot(88888)
    assert d_other == 0.0, d_other

    # старі мітки (>10 хв) викидаються: імітуємо вікно
    ns._eval_times[acc].clear()
    ns._eval_next_free.pop(acc, None)
    assert ns._eval_claim_slot(acc) == 0.0

    print("AUTOEVAL PACER OK")


if __name__ == "__main__":
    main()