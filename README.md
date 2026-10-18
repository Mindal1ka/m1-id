# M1 ID — студентський клієнт MyStat

> **EN:** M1 ID is an unofficial, student-made web client (PWA) for **MyStat** (mystat.itstep.org, IT STEP Academy/School).
> One account, a fast dark-themed app with schedule, homework, marks, shop, payments, news, awards, leaderboard and an optional Telegram bot.
> Not affiliated with IT STEP or MyStat. Use your own credentials.

🌐 **Живий сайт: https://m1id.xyz**

**M1 ID** — неофіційна студентська версія **MyStat** (IT STEP): розклад, домашні завдання, оцінки, магазин,
платежі, новини, нагороди, лідерборд і Telegram-бот у зручній швидкій PWA. Працює в браузері та
встановлюється на телефон як застосунок.

> ⚠️ Проєкт **не пов'язаний** з IT STEP та MyStat і не є офіційним. Ви входите зі своїми даними MyStat на власний ризик.
> Харчування (FoodStep) працює лише для студентів філії **Полтава (pl)**.

## Можливості

- 🏠 **Головна** з налаштовуваними віджетами: дедлайни, уроки сьогодні, оцінки, нарахування, лідери, новини.
- 📅 **Розклад**: тиждень / місяць, кольори предметів, відвідуваність, відео уроків.
- 📚 **Домашка**: «До виконання / На перевірці / Виконано / Ретейк», здача файлів.
- 🧮 **Оцінки та прогрес**, 🏆 **лідери**, 🛍️ **магазин**, 💳 **платежі**, 🎁 **нагороди**, 📰 **новини**, ☎️ **контакти**.
- 🍴 **Харчування (FoodStep)** — лише філія pl: меню, замовлення, автозамовлення.
- 🤖 **Telegram-бот**: сповіщення про оцінки й домашки, розклад, лідерборд.
- 👥 Кілька акаунтів MyStat в одному акаунті M1 ID, миттєве перемикання.
- 📴 PWA: офлайн-кеш, встановлення на домашній екран.
- 🔐 Пароль MyStat **не зберігається**; токен шифрується (AES/Fernet), пароль M1 ID — Argon2id.

## Архітектура

```
Браузер (SvelteKit PWA)  ⇄  FastAPI-бекенд M1 ID  ⇄  MyStat API (mapi.itstep.org)
                                 │
                                 └─ SQLite · Telegram-бот · FoodStep (філія pl)
```

Клієнт ніколи не бачить токен MyStat: усі запити йдуть через бекенд, який приводить відповіді
до єдиного формату. Детальніше — [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
Опис самого API MyStat і мок-сервер — окремий репозиторій **mystat-api**.

## Швидкий старт (розробка)

Потрібно: **Python ≥ 3.12**, **Node.js ≥ 20**.

```bash
# 1. Бекенд (http://127.0.0.1:8080, Swagger: /docs)
cd backend
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # заповніть за потреби (Windows: copy)
set M1ID_DEBUG=1                  # Linux/macOS: export M1ID_DEBUG=1
python -m granian --interface asgi app.main:app --host 127.0.0.1 --port 8080 --reload --reload-paths app

# 2. Фронтенд (http://localhost:5173)
cd frontend
npm install
npm run dev
```

Скрипти запуску для Windows: `backend/start.bat`. Перевірка зв'язки: `scripts/dev_check.ps1`.
Змінні оточення описані в [`backend/.env.example`](backend/.env.example) (префікс `M1ID_`).

### Тести

У `backend/` лежать `smoke_test_*.py` (кожен запускається окремо: `python smoke_test_m2.py`).
Перевірка типів фронтенда: `cd frontend && npm run check`.

## Структура

```
backend/    FastAPI: акаунти, синхронізація, нормалізатори, Telegram-бот, плагіни
frontend/   SvelteKit (SPA, adapter-static) + PWA
plugins/    приклади плагінів
docs/       архітектура, дизайн-система, анімації
scripts/    допоміжні скрипти розробки
```

## Безпека

- Ніколи не комітьте `.env`, `*.db`, ключі `backend/.token_key` і `backend/.jwt_key`, токени (вони в `.gitignore`).
- Пісочниця плагінів — базова, **не** межа безпеки (див. [`DEV.md`](DEV.md)); не запускайте чужі плагіни без окремої ізоляції.
- Знайшли вразливість — напишіть автору приватно, не публікуйте в issue.

## Ліцензія

[MIT](LICENSE) © Mindal1ka
