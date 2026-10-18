"""Telegram-бот M1 ID (aiogram 3) — живе в одному процесі з API.

Модулі:
  linking  — deep-link прив'язки (?start=<uid>-<hmac>, підпис jwt-секретом)
  bot      — обробники команд/кнопок + форматування повідомлень
  poller   — фоновий опитувальник MyStat: детект змін → сповіщення
  runtime  — старт/стоп разом із FastAPI lifespan
"""
