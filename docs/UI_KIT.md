# UI_KIT — правила UI-кіту `$lib/ui` (дизайн-система v2 «Clean»)

> Контракт для всіх, хто пише компоненти в `frontend/src/lib/ui/`. Токени — у `src/lib/design/tokens.css`.

## Загальні правила

- Svelte 5 runes: `$props()`, `$state`, `$derived`, snippets (`children`, іменовані snippet-пропси). Без `export let`, без slot-ів.
- TypeScript: `<script lang="ts">`, типізовані props (`interface Props`), `...rest` прокидається на кореневий елемент (`HTMLButtonAttributes` тощо з `svelte/elements`).
- **Тільки токени**: кольори — `var(--color-*)`, відступи — `var(--space-*)`, шрифти — `var(--text-*)`/`var(--weight-*)`, радіуси — `var(--radius-*)`, z-index — `var(--z-*)`, тривалості — `var(--dur-*)`/`var(--ease-*)`. **Жодних hex/rgba** у компонентах (виняток: `transparent`, `currentColor`, `color-mix()` над токенами).
- Стилі — scoped `<style>` всередині компонента; класи з префіксом немає потреби (scoped). Глобальних стилів кіт не додає.
- Іконки — лише `@lucide/svelte` (компонент передається пропсом `icon` типу `Component` або snippet). Без емодзі та текстових гліфів (✕ ← →).
- Доступність: правильні ролі/ARIA, клавіатура (Enter/Space/Esc/стрілки там, де очікується), видимий `:focus-visible`, мінімальна зона тапу 40px на мобільному, `aria-label` для icon-only.
- Мобільний: брейкпойнти лише `640px` (sm), `900px` (md), `1200px` (lg).
- Усі тексти за замовчуванням — українською, звертання на «ти».
- Коментарі — українською (див. `AGENTS.md`), стисло.
- Нових npm-залежностей не додавати.
- Експорт усього через `src/lib/ui/index.ts` (кожен автор додає свої рядки у свій блок).

## Склад кіту

| Група | Компоненти |
|---|---|
| Базові | `Button`, `IconButton`, `Card`, `PageHeader`, `Badge`, `GradeBadge`, `Spinner`, `Skeleton`, `EmptyState`, `ErrorState`, `Avatar`, `Divider` |
| Оверлеї | `Dialog` (desktop — центр, mobile ≤640 — bottom sheet), `ConfirmHost` + `confirm()` з `confirm.svelte.ts`, `Popover`, `Tooltip`, `ToastHost` |
| Форми | `Field`, `Input`, `Textarea`, `Select`, `Switch`, `Checkbox`, `SettingRow`, `Segmented`, `Tabs`, `SearchField`, `CopyButton`, `Stepper` |

### Ключові API (скорочено)

- `Button`: `variant: 'primary'|'secondary'|'ghost'|'danger'|'soft'`, `size: 'sm'|'md'|'lg'`, `icon?`, `iconRight?`, `loading?`, `block?`, `href?` (тоді `<a>`), решта атрибутів.
- `IconButton`: `icon`, `label` (обов'язково → `aria-label` + `title`), `variant: 'ghost'|'secondary'|'primary'|'danger'`, `size`.
- `Card`: `padding: 'none'|'sm'|'md'|'lg'`, `interactive?` (hover/focus, тоді `<button>`/`<a>` якщо задано `onclick`/`href`), `header?` snippet, `title?`, `subtitle?`, `actions?` snippet, `children`.
- `PageHeader`: `title`, `subtitle?`, `icon?`, `actions?` snippet, `children?` (рядок під заголовком: таби/фільтри).
- `Badge`: `tone: 'neutral'|'accent'|'success'|'warning'|'danger'|'info'`, `variant: 'soft'|'solid'|'outline'`, `icon?`, `size`.
- `GradeBadge`: `value: number|string|null`, `scale = 12`, `size`; колір за якістю (`--grade-high` ≥10, `--grade-mid` ≥7, `--grade-low` інакше; для шкали 5 — ≥4.5/≥3.5).
- `EmptyState` / `ErrorState`: `icon?`, `title`, `description?`, `action?` snippet; `ErrorState` має `onretry?` → кнопка «Спробувати ще».
- `Dialog`: `open` (bindable), `title?`, `description?`, `size: 'sm'|'md'|'lg'|'full'`, `onclose?`, `footer?` snippet, `children`, `dismissible = true`; портал у `body`, focus trap (`$lib/actions/focusTrap`), Esc, клік по overlay, блокування скролу, на мобільному — sheet знизу з «ручкою» і safe-area.
- `confirm({ title, message?, confirmText?, cancelText?, danger? }): Promise<boolean>` — один `ConfirmHost` змонтований у шеллі.
- `toast` — існуючий `$lib/stores/toast.svelte.ts` (`showToast`); `ToastHost` рендерить стек.
- `Switch`: `checked` (bindable), `disabled?`, `label?` (для `aria-label`), `onchange?`. `SettingRow`: `icon?`, `title`, `description?`, `control` snippet (праворуч), клікабельний рядок перемикає switch.
- `Segmented` / `Tabs`: `items: {value, label, icon?, badge?}[]`, `value` (bindable), `size`; `Tabs` — підкреслення, `Segmented` — «пігулка».
- `Field`: `label`, `hint?`, `error?`, `required?`, `children` (контрол), пов'язує `for`/`id`/`aria-describedby`.
