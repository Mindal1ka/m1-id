# PROJECT.md — Актуальний стан проєкту M1 ID

> Оновлено: 2026-09-22. Це актуальний опис проєкту; `README.md` — оригінальний
> документ візії, його Roadmap («M5–M7 не зроблено») і структура вже застаріли:
> насправді реалізовано значно більше (Telegram-бот, плагіни, M1 Provider/short-links,
> write-операції, прод m1id.xyz).

---

## Що таке M1 ID

«Твій MyStat — таким, яким він має бути»: власна система акаунтів (M1 ID) + підключення
акаунтів MyStat (mystat.itstep.org) + single-page PWA з усіма розділами оригіналу
(розклад, домашка, оцінки, магазин, харчування, клуби, нагороди, чат, новини).
Дизайн — «Aurora Glass»: темна тема, скло, суцільні кольори без градієнтів.

**Прод:** `m1id.xyz` (фронт + бекенд на одному домені). **Дев:** фронт 5173, бек 8080
(порти через `start_host_backend.bat` / `start_host_frontend.bat` / `scripts/dev_check.ps1`).

---

## Архітектура

```
PWA (SvelteKit 5/2, SPA, adapter-static, m1id.xyz)
   │  HTTPS, конверт {ok, data, meta, error}
   ▼
FastAPI-шлюз (Python, granian/uvicorn, порт 8080 dev / 8000 prod за reverse-proxy)
   ├─ SpecRegistry (openapi.json, 162 paths / 167 операцій / 51 схема)
   ├─ SQLite: app.db (users, акаунти, снапшоти), plugins.db, links.db, notes.db (нотатки, паролі, метадані файлів)
   ├─ Telegram-бот (aiogram 3, у тому самому процесі)
   ├─ Notify-socket клієнт (socket.io → notify MyStat)
   ├─ Плагін-система (subprocess-воркери)
   └─ прямий маршрут до mapi.itstep.org
```

Ключовий принцип — **spec-driven**: бекенд не хардкодить шляхи MyStat; маршрутизація,
валідація і гілкові шляхи (`/v1/mystat/{branch_alias}/…`) беруться з `openapi.json`.
Джерело спеки: SPEC_URL → кеш → снапшот (відповідність шляхів у `main.py` і
`system.py` РІЗНА — див. BUGS.md B7).

### Стек
- **Backend**: FastAPI + granian (fallback uvicorn), SQLAlchemy + aiosqlite, Argon2id
  (паролі), Fernet/AES-GCM (токени MyStat), PyJWT, dnspython (MX-перевірка email без
  листів), httpx (async), python-socketio, aiogram 3, segno (QR).
- **Frontend**: SvelteKit 2 + Svelte 5 (runes, `ssr=false`), adapter-static, власний
  `static/sw.js` (без Workbox), vite-плагіни build-stamp + css-prefix-guard.
- **Деплой-девіси**: `old_link/` —
  міграційний ASGI-сервіс, що форсить оновлення старого клієнта і показує «посилання
  застаріло» → m1id.xyz.

---

## Backend (`m1-id/backend/app`)

| Модуль | Що робить |
|---|---|
| `core/config.py` | pydantic-settings: `M1ID_*` env; без секретів у коді |
| `core/security.py` | Argon2id, AES-GCM шифрування токенів, JWT M1 ID; ключ .jwt_key переживає рестарти |
| `core/responses.py` | Єдиний конверт `{ok, data, meta, error}` + глобальні хендлери помилок |
| `db/` | SQLAlchemy-моделі; SQLite WAL + авто-міграції на старті (`_migrate_sqlite`) |
| `spec/registry.py` | SpecRegistry: paths/methods/schemas з openapi.json, матчинг `{branch_alias}` |
| `routers/auth_m1.py` | register/login/refresh/me; ротація refresh з grace-вікном і OWASP reuse-detection (див. BUGS B3) |
| `routers/accounts.py` | прив'язка акаунтів MyStat (логін на сервері, токен шифрується), перемикання |
| `routers/app_api.py` | агреговане API для фронта: `/api/app/{dashboard,homework,schedule,marks,…}` — 1-2 виклики замість десятків сирих; снапшоти за TTL + fresh-first |
| `routers/mystat_proxy.py` | spec-driven проксі `ANY /api/mystat/{path}`: валідація за спекою, підстановка Bearer/X-UserId, ланцюжок 401→refresh→retry |
| `routers/links.py` | **M1 Provider**: короткі посилання `/api/v1/files/{slug}` (slug = секрет) для здачі ДЗ вчителю; анонімна галерея медіа + TG-сповіщення власнику |
| `routers/telegram.py` | API прив'язок бота (QR/depth-link) |
| `routers/plugins.py` | маркетплейс плагінів: upload (JSON/ZIP), verify (адмін), share-by-token, run |
| `routers/system.py` | health, spec/stats, spec/operations, spec/reload |
| `services/mystat_client.py` | httpx AsyncClient: гілки, заголовки, семафор, retry, 401-refresh (дедуп refresh — BUGS B4) |
| `services/sync_engine.py` | SYNC_PLAN по секціях (profile/core/study/money/fun), паралельний збір, снапшоти |
| `services/app_data.py` | TTL-кеш снапшотів + хук `on_fresh_data` (єдина подія «свіжі дані» для сайта і бота) |
| `services/notify_socket.py` | socket.io-клієнт до notify MyStat: миттєві події → точковий перезапит секцій + «Автооцінювання» (dedupe, тихі години, pending-черга) |
| `services/links.py` | БД links.db, слаги, фетч файлів ДЗ, галерея, лічильник відкриттів, тротлінг нотифікацій |
| `services/ratelimit.py` | rate-limit auth-роутів (спільний IP за Caddy/Cloudflare CDN) |
| `services/email_check.py` | верифікація email без SMTP: синтаксис + DNS MX + блоклист одноразових доменів |
| `telegram/` | aiogram 3 бот у тому ж процесі: прив'язка через deep-link з HMAC (TTL 24 год), poller раз на ~30 хв ганяє детекти змін (домашка, оцінки, розклад, лідерборд, магазин) по снапшотах, пер-акаунтні asyncio.Lock |
| `plugins/` | система плагінів (див. нижче) |

### Дані
- `users`, `mystat_accounts` (токен AES-GCM, пароль MyStat **не зберігається**; 401 →
  `POST /auth/refresh` → повтор → інакше `needs_relogin`), `snapshots` (per-section),
  `sessions` (refresh з ротацією). Окремі БД: `plugins.db`, `links.db`, `notes.db`.

---

## Фронтенд (`m1-id/frontend`)

- **SPA/PWA**: SvelteKit 2 + Svelte 5 runes, `ssr=false`, adapter-static з fallback
  `index.html`. `/api/*` в dev проксюється на 127.0.0.1:8080.
- **Маршрути**: `/login`, `/onboarding/[id]`, `/reset`, `/accounts`, головний
  `/app` (контролер ~1.7к рядків + вигляди вкладок у `lib/components/app/`, важкі вкладки й модалки — lazy-чанки).
- **Стан** (Svelte 5 `$state`-класи): `auth.svelte.ts` (сесія → localStorage),
  `appStore.svelte.ts` (пер-акаунтний кеш Dashboard/ДЗ/розклад/оцінки/новини/магазин +
  freshness 5 хв, дубль у localStorage), `theme.svelte.ts` (2 виміри: dark/light/neon ×
  11 акцентів → CSS-змінні), `widgets.svelte.ts` (розкладка віджетів), `devmode`.
- **API-клієнт** (`lib/api/client.ts`): обгортка fetch над конвертом; таймаути 20с/120с,
  single-flight refresh при 401, retry тільки GET.
- **PWA**: власний `sw.js` — precache app-shell + BFS по immutable-чанках, SWR для
  навігацій, `/api/*` не перехоплює; `__BUILD_STAMP__` ↔ `/version.json` ↔ VERSION у
  sw.js (щохвилинна перевірка → блокуючий `UpdateGate` «прод новіший за вкладку»).
- **Компоненти**: 25+ вкладок/модалок (ShopTab, SubmitModal, HomeworkDetailsModal,
  TelegramPanel, PluginsPanel, SettingsModal, ProfileModal, ContactsTab, NotesTab тощо).
  HTML з mapi → `{@html}` тільки після allow-list санітайзера (`lib/sanitize.ts`).
- **Стиль**: «Aurora Glass» — tokens.css, Inter + Unbounded, іконки lucide.

---

## Плагіни (`m1-id/plugins`, `backend/app/plugins`)

«Сплячі лямбди» користувача: код у plugins.db → на аплоаді **AST-аналізатор**
(білий список імпортів, заборона eval/exec/dunder) → запуск в одноразовому subprocess
(`python -I worker_boot.py`, таймаут 2с, kill). Дані юзера передаються «сліпими» —
PII підмінюється псевдонімами (`sanitizer.py` → `#T1`), `unredact` на відповіді.
Сповіщення плагінів — через чергу outbox (Telegram) з квотами 60/год на юзера,
30/год на плагін. Полер плагінів працює навіть без Telegram. Готові плагіни:
`hw-watch` (нагадування про ДЗ), `streak-note`. Розробка плагінів: `plugins/DEV.md`.

⚠️ Пісочниця на базі exec + урізаних builtins — не гарантія безпеки (BUGS H4).

---

## Telegram-бот

Живе в процесі бекенда: poller кожні ~30 хв порівнює снапшоти секцій mapi зі станом
у БД і шле сповіщення про зміни; миттєве реагування через хук `on_fresh_data` (сайт,
сокет або цикл витягнув свіжі дані → бот одразу ганяє детекти, без очікування циклу).
Прив'язка акаунта — deep-link з HMAC-підписом, TTL 24 год, QR-код (segno).

---

## Розмазування фонових mapi-запитів (env `M1ID_POLL_PACE`)

- `account` (дефолт) — вікно poller'а (30 хв) ділиться на акаунти; запити юзера
  всередині слота летять пачкою. Добре для кількох юзерів.
- `request` — вікно ділиться на **запити**: `services/mapi_pacer.py` роздає кожному
  mapi-виклику власний момент (`window / total_requests`) — рівний потік
  (при 50 юзерах ≈ 1 запит / 3.6–9с) без пачок незалежно від кількості акаунтів.
  Рекомендовано при зростанні юзерів. Інтерактивні
  запити (сайт, сокет fast-path) pacер не проходять. Якщо mapi почне обмежувати —
  просто збільшуємо `M1ID_TELEGRAM_POLL_SECONDS`.

## Реалтайм

- Pacування автооцінювань (`notify_socket`): після довгої вимкненої автоматичної оцінки
  пачка накопичених уроків більше не оцінюється поспіль — перші 4 оцінювання за
  10 с одразу, далі не частіше ніж раз на 5с (mapi перестає «відбивати» спам
  `evaluate-lesson`).

- Клієнт ↔ наш бекенд: миттєві події приходять через точкові перезапити секцій;
  `/api/health` пінгується часто, оновлення версії — щохвилинний опит `/version.json`.
- Бекенд ↔ MyStat: socket.io (notify) — події одразу тригерять перезапит даних
  і автооцінювання уроків; лог-сокет (імітація активності) свідомо не відтворюється.

## M1 Provider (short-links)

`POST /api/links/...` → слаг; анонімний вчитель відкриває `/api/v1/files/{slug}`:
галерея файлів ДЗ (медіа проксіюється), кнопка download, власнику йде Telegram-
сповіщення про перегляд. Окрема БД `links.db`. У проді перед бекендом стоїть Caddy
(з Cloudflare CDN попереду): маршрут `/api/v1/files/*` проксіюється на бекенд (:4174)
як і решта `/api/*`, окремого воркера/egress-шару немає.

---

## Сусідні каталоги (не частина прод-шляху)

| Каталог | Призначення |
|---|---|
| `fastapi/` | Мок-сервер справжнього API MyStat (Swagger, mock/proxy режими) — джерело снапшота спеки і фікстур `examples/`. Порт 8000. |
| `old_link/` | Міні-ASGI сервіс (granian, 4181): старий клієнт бачить «посилання застаріле» → m1id.xyz. |
| `examples/` | Живі відповіді API (фікстури для мока/тестів). |
| `bundles/` | Розкриті чанки справжнього Angular-фронту MyStat (джерело реверсу). |
| `tools/`, `m1-id/backend/app/scripts/`, `m1-id/scripts/` | Debug/probe/навантажувальні скрипти, не входять у прод. |
| `MYSTAT_API.md`, `how.md`, `openapi.json` | Документація реверсу API MyStat — єдине джерело правди для спеки. |

---

## Тестування

Smoke-тести в `m1-id/backend/`: `smoke_test_m0.py` (спека/реєстр), `smoke_test_m1.py`
(акаунти/JWT), `smoke_test_m2.py` (прив'язка+синк, 21/21 на мок-транспорті),
`smoke_test_m3.py`, `smoke_test_plugins*.py`, `smoke_test_telegram.py`,
`smoke_test_refresh_grace.py`, `smoke_test_lb_monitor.py` тощо. Живі перевірки —
`scripts/live_check_m2.py` та ін. Навантажувальні: `loadtest_*.py` + `loadtest_run.ps1`.

---

## Roadmap (фактичний стан)

| Етап | Стан |
|---|---|
| M0 скелети + SpecRegistry | ✅ |
| M1: M1 ID (JWT, Argon2id, шифрування, БД) | ✅ |
| M2: прив'язка акаунтів MyStat + Sync Engine | ✅ |
| M3–M4: агреговане API, вкладки, PWA/офлайн, оновлення по build-stamp | ✅ |
| M5: гроші/магазин/харчування/нагороди/новини/клуби | ✅ |
| M6: write-операції (здача ДЗ, заяви), чат/сокети, Telegram-бот, плагіни | ✅ |
| Прод m1id.xyz: M1 Provider, old_link-міграція | ✅ |

Наступні кроки — див. BUGS.md (безпека: пісочниця плагінів,
витік токена бота в логи, чистка кешу при logout).