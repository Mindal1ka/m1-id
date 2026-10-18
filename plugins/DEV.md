# Плагіни M1 ID — повна спека (для розробників та ШІ-асистентів)

> **Це єдина спека платформи плагінів M1 ID.** Прочитавши її, ти маєш ТОЧНО
> розуміти, як твій скрипт буде виконано на сервері: коли він прокидається,
> що він бачить, що може повернути, що його вб'є і що відхилить аналізатор.
> Якщо тебе просять «напиши плагін для M1 ID» — генеруй код СТРОГО за цими
> правилами. Недотримання = відхилення на аплоаді або падіння у runtime.

---

## 1. Модель виконання: «спляча лямбда»

Плагін **ніколи не працює у фоні**. Кожен запуск — такий цикл:

1. **Подія** (тригер): TG-команда, кнопка в TG, нові дані з сайту (poller),
   відкриття вкладки юзером.
2. Сервер піднімає **одноразовий** процес: `python -I worker_boot.py`
   (Windows-safe: kill по таймауту замість rlimit).
3. У stdin передається JSON: `{code, hook, args}`, де
   `args = {event, payload, params, settings, storage, args_text}`.
4. Виконується **≤ 2 секунди** — далі процес kill'ється. Лог пишеться в `PluginRun`.
5. stdout мусить містити `===PLUGIN_RESULT===\n{json}`.
6. Сервер застосовує результат: `notify` → у чергу Telegram (з лiмітами),
   `text` → відповідь у чат, `storage` → персист (перевірка ліміту),
   `data` → у вкладку на сайті (для on_ui).

Плагін бачить **тільки** `ctx` — жодного доступу до файлів, мережі, БД,
основного застосунку чи Telegram API напряму.

## 2. Файли плагіна

```
my-plugin/
  manifest.json   — обов'язковий
  plugin.py       — логіка (не обов'язковий: плагін може бути чисто UI)
  index.html      — кастомна вкладка (ОДИН файл, inline CSS+JS, vanilla JS)
  icon.png        — опційно (base64-зберігається)
```

Аплоад: **zip** або **окремими файлами**. Обмеження: 512 КБ сумарно, ≤ 20
файлів, без підпапок. Розширення: `.py .html .json .md .png .txt`.
Видимість у маркетплейсі при аплоаді: `public` (усім) / `link` (лише за
share-посиланням) / `private` (лише автор і адмін).

## 3. manifest.json

```json
{
  "id": "my-plugin",                 // slug [a-z0-9-], 2-48, унікальний
  "name": "Мій плагін",              // ≤96
  "version": "1.0.0",                // semver; при повторному аплоаді ЗРОСТАЄ
  "author": "Хтось",
  "description": "Що робить (≤200 символів)",
  "permissions": ["homework:read", "notify:telegram", "storage"],
  "tg_commands": [                   // ≤5, глобально унікальні
    { "command": "mynote", "description": "Що робить (≤64)" }
  ],
  "tg_buttons": [                    // ≤8: callback plg:<id>:<button>
    { "id": "refresh", "label": "Оновити" }
  ],
  "hooks": { "on_event": true, "on_ui": true, "on_command": true, "on_daily": true },
  "entry": "plugin.py",
  "ui": { "tab": true, "widget": "stat", "entry": "index.html" },
  "storage_limit_kb": 16,            // 1..256
  "settings_schema": [
    { "key": "hours_before", "type": "number", "default": 24, "label": "За N годин" }
  ]
}
```

Типи `settings_schema`: `text | number | boolean | select (options: [...]) |
textarea`. Максимум 20 полів. Зарезервовані TG-команди (зайняті ядром):
`start, help, settings, homework, marks, schedule, leaderboard`.

## 4. Дозволи → що приходить у payload

| Дозвіл | payload |
|---|---|
| `homework:read` | `{homework: {items: [{id, name_spec, theme, status, overdue_time, due}]}}` |
| `marks:read` | `{stat_marks_year: {...}}` |
| `schedule:read` | `{schedule_week@<monday>: {...}}` |
| `leaderboard:read` | `{leader_points, leader_table}` — **імена ПУБЛІЧНІ** |
| `balances:read` | `{balances: {...}}` |
| `shop:read` | `{shop_products: {...}}` |
| `news:read` | `{news: {...}}` |
| `payments:read` | `{payment_next, payment_info}` |
| `clubs:read` | `{clubs, club_abonements}` |
| `progress:read` | `{stat_progress: {...}}` |
| `notify:telegram` | дії `notify` у результаті хука |
| `storage` | `ctx.storage` — ключ-значення per-user (≤ storage_limit_kb) |

**Сліпий API**: поля `fio, teacher_fio, email, phone, mystat_login, username`
у payload підмінені псевдонімами `#T1, #T2…` (детерміновано — той самий юзер
отримує той самий псевдонім). Email/телефони у вільному тексті теж вирізані.
**На виході** з плагіна (у `text`/`notify`) сервер сам відновлює реальні
дані — плагіну вони ніколи не доступні. У `data` (вкладка) залишаються
псевдоніми, крім публічних секцій (leader_points, leader_table).

## 5. Хуки (функції у plugin.py)

```python
import json  # дозволені модулі: json, math, random, re, datetime,
             # textwrap, statistics, string, itertools, collections, functools

def on_install(ctx):          # після встановлення
    return {"notify": [{"text": "Плагін встановлено! /mynote — допомога"}]}

def on_uninstall(ctx):        # перед видаленням (прибрати нотифікації тощо)
    return {}

def on_daily(ctx):            # раз на добу; ctx.payload — дані за дозволами
    n = len(ctx.payload.get("homework", {}).get("items", []))
    return {"notify": [{"text": f"Сьогодні {n} ДЗ"}]}

def on_event(ctx):            # події: data.fresh, homework.deadline_soon
    # ctx.event, ctx.payload, ctx.settings, ctx.storage
    if ctx.event == "homework.deadline_soon":
        items = ctx.payload.get("items") or []
        if items:
            i = items[0]
            return {"notify": [{"text": f"⏰ Дедлайн: {i['name_spec']}",
                                "priority": "critical"}],
                    "storage": {"warned": True}}
    return {}

def on_command_mynote(ctx):       # TG-команда /mynote <аргументи>
    # ctx.args_text — усе після команди
    notes = ctx.storage if isinstance(ctx.storage, dict) else {}
    lst = notes.get("items") or []
    lst.append((ctx.args_text or "").strip() or "порожньо")
    lst = lst[-50:]
    return {"text": f"Записав. Усього: {len(lst)}", "storage": {"items": lst}}

def on_button_refresh(ctx):       # кнопка tg_buttons: callback plg:<id>:refresh
    return {"text": "Оновлено ✅"}

def on_ui(ctx):                   # юзер відкрив вкладку плагіна
    # ctx.params — параметри з сайту
    items = (ctx.payload.get("homework") or {}).get("items") or []
    pending = len([i for i in items if i.get("status") == 3])
    return {"data": {"type": "stat", "label": "Нездало", "value": pending}}
```

`ctx` — об'єкт з атрибутами: `event`, `payload`, `params`, `settings`
(персональні, зі settings_schema), `storage` (dict; у worker може прийти
str — обробляй обидва випадки), `args_text`.

**Результат хука** — `dict`, усі поля опційні:
- `data` — JSON для вкладки. Без index.html — або `{"type": "stat", "label",
  "value"}`, або `{"type": "list", "label", "items"}`, або довільний JSON
  (покажеться документом).
- `text` — HTML-відповідь у TG-чат (Telegram-теги: b/i/a/code/pre).
- `notify` — список `[{text, priority}]`, `priority: "info" | "critical"`.
- `storage` — оновлений JSON-стан (перевищення `storage_limit_kb` → помилка
  запуску `storage_limit_exceeded`).

**Події**:
- `data.fresh` — `payload = {sections: [...], data: {...}}`, свіжі секції даних
- Події летять ДВАМА шляхами: 1) TG-полер/сокет (миттєво при зміні) та
  2) **плагін-полер** — незалежний цикл (~2 хв), який працює навіть коли
  Telegram-сповіщення вимкнені або бот не налаштований: якщо плагін з
  `on_event` просить дані за дозволами, ядро саме оновлює їх (з повагою
  до TTL кешу) і шле `data.fresh`. Дублі подій не страшні: cooldown
  60с на (плагін, подія, юзер)
- `homework.deadline_soon` — `payload = {items: [{...ДЗ, remaining_h}]}`

Cooldown: одна подія не спамить плагін частіше ніж раз на 60с
(на `(plugin, event, user)`).

## 6. index.html (кастомна вкладка)

Один файл, vanilla JS, без build/CDN. Рендериться у
`<iframe sandbox="allow-scripts">` **без allow-same-origin** — opaque origin:
localStorage, document.cookie, доступ до батьківського вікна/токенів —
НЕДОСТУПНІ. Дані — тільки через postMessage:

```html
<div id="out">…</div>
<script>
  document.addEventListener('plugin-data', (e) => {
    const payload = e.detail.data.payload;  // те, що on_ui повернув у data
    document.getElementById('out').textContent = JSON.stringify(payload, null, 2);
  });
</script>
```

Хост надсилає `{type: 'plugin:data', payload}` після load (~300 мс). Без
`index.html` — `data` рендериться вбудованим віджетом (stat/list/JSON).

## 7. Telegram-повідомлення і ліміти

- Квоти: **60 повідомлень/год на юзера** (усі плагіни разом),
  **30/год плагін-юзер**. При вичерпанні — `RateLimitExceeded` (запуск
  фейлиться з логом).
- Telegram `RetryAfter` (флуд-контроль) поважається автоматично: повідомлення
  йдуть через outbox-чергу з retry.
- Тихі години юзера й пріоритети — керує ядро, плагін лише просить.

## 8. ЖОРСТКІ ЗАБОРОНИ (відхиляється AST-аналізатором на аплоаді І перед кожним запуском)

- `import` будь-чого, крім білого списку (п. 5). Ні os, sys, socket, subprocess, urllib.
- `eval, exec, compile, __import__, globals(), locals(), vars(), open(),
  input(), breakpoint()`
- dunder-атрибут (`x.__class__`, `__subclasses__`, `__globals__`…) та
  dunder-рядки (`"__globals__"`, обхід через getattr-конкатенацію)
- доступ до `__builtins__`
- сирі персональні дані: не розраховуй на ПІБ/пошту/телефони — бачиш лише `#T…`
- розмір коду ≤ 64 КБ, глибина AST ≤ 50, вузлів ≤ 50 000
- `while True` без умови виходу — вб'ється таймаутом (2 с) і лог буде «timeout»

**Runtime-оточення (worker)**: урізані builtins (без open/eval/compile),
власний `__import__` з білим списком, доступні: винятки
(`Exception, ValueError, TypeError, KeyError, IndexError, AttributeError,
RuntimeError, ZeroDivisionError, StopIteration, ArithmeticError, LookupError,
OverflowError, RecursionError`), `isinstance, issubclass, getattr, hasattr,
hash, id`. `print` — заглушка (нікуди не пише).

## 9. Чекліст перед віддачею коду

1. manifest.json проходить схему (id/version/permissions — зі списку п. 4).
2. plugin.py: тільки білі імпорти, без eval/exec/dunder/`__builtins__`.
3. Хуки повертають `dict` (мінімум `return {}`), серіалізовний у JSON.
4. storage: обробка і `str`, і `dict` на вході; не перевищуй storage_limit_kb.
5. TG-команда не конфліктує з зарезервованими (п. 3).
6. index.html самодостатній: без CDN/зовнішніх скриптів, JS у try/catch.
7. Тексти UI/повідомлень — українською, короткі, без PII (у тебе тільки #T…).
8. Жодних звернень до мережі/файлів/БД — плагін живе тільки на ctx.