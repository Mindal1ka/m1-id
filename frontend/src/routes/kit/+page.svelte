<script lang="ts">
	import {
		Plus,
		Trash2,
		Settings,
		Search,
		Mail,
		Bell,
		User,
		Info,
		Check,
		Inbox,
		Download,
		ChevronRight
	} from '@lucide/svelte';
	import {
		Button,
		IconButton,
		Card,
		PageHeader,
		Badge,
		GradeBadge,
		Avatar,
		Skeleton,
		EmptyState,
		ErrorState,
		Divider,
		Field,
		Input,
		Textarea,
		Select,
		Switch,
		Checkbox,
		SettingRow,
		Segmented,
		Tabs,
		SearchField,
		CopyButton,
		Stepper,
		Dialog,
		Popover,
		Tooltip,
		confirm
	} from '$lib/ui';
	import { theme } from '$lib/theme.svelte';
	import { showToast } from '$lib/stores/toast.svelte';

	const variants = ['primary', 'secondary', 'ghost', 'danger', 'soft'] as const;
	const sizes = ['sm', 'md', 'lg'] as const;
	const iconVariants = ['ghost', 'secondary', 'primary', 'danger'] as const;
	const tones = ['neutral', 'accent', 'success', 'warning', 'danger', 'info'] as const;
	const badgeVariants = ['soft', 'solid', 'outline'] as const;
	const grades: (number | null)[] = [12, 10, 8, 6, 3, null];

	// Форми
	let text = $state('');
	let invalidText = $state('ab');
	let pass = $state('secret123');
	let bio = $state('');
	let auto = $state('');
	let sel = $state('b');
	let sw = $state(true);
	let cbA = $state(true);
	let cbB = $state(false);
	let cbInd = $state(false);
	let rowA = $state(true);
	let seg = $state('week');
	let tab = $state('one');
	let query = $state('');
	let qty = $state(3);

	// Оверлеї
	let dlgSm = $state(false);
	let dlgMd = $state(false);
	let dlgLg = $state(false);
	let popOpen = $state(false);
	let popAnchor = $state<HTMLElement | null>(null);

	const segItems = [
		{ value: 'day', label: 'День' },
		{ value: 'week', label: 'Тиждень' },
		{ value: 'month', label: 'Місяць', badge: 3 }
	];
	const tabItems = [
		{ value: 'one', label: 'Огляд', icon: Info },
		{ value: 'two', label: 'Повідомлення', badge: 5 },
		{ value: 'three', label: 'Налаштування', icon: Settings },
		{ value: 'four', label: 'Вимкнено', disabled: true }
	];
	const options = [
		{ value: 'a', label: 'Варіант A' },
		{ value: 'b', label: 'Варіант B' },
		{ value: 'c', label: 'Недоступний', disabled: true }
	];

	async function ask(danger: boolean) {
		const ok = await confirm(
			danger
				? {
						title: 'Видалити запис?',
						message: 'Дію неможливо скасувати.',
						confirmText: 'Видалити',
						danger: true
					}
				: { title: 'Зберегти зміни?', message: 'Зміни буде застосовано одразу.' }
		);
		showToast(ok ? 'Підтверджено' : 'Скасовано');
	}

	function retry() {
		showToast('Повторна спроба');
	}
</script>

<svelte:head>
	<title>UI kit · M1 ID</title>
	<meta name="robots" content="noindex" />
</svelte:head>

<div class="topbar">
	<div class="topbar-in">
		<strong class="brand">UI kit · M1 ID</strong>
		<div class="controls">
			<Segmented
				size="sm"
				aria-label="Режим оформлення"
				value={theme.mode}
				items={theme.modes.map((m) => ({ value: m.key, label: m.name, icon: m.icon }))}
				onchange={(v) => theme.setMode(v as 'dark' | 'light' | 'neon')}
			/>
			<div class="accents" role="group" aria-label="Акцент">
				{#each theme.accents as a (a.key)}
					<Tooltip label={a.name}>
						<button
							type="button"
							class="swatch"
							class:active={theme.accent === a.key}
							style:background={a.accent}
							aria-label={a.name}
							aria-pressed={theme.accent === a.key}
							onclick={() => theme.setAccent(a.key)}
						></button>
					</Tooltip>
				{/each}
			</div>
		</div>
	</div>
</div>

<div class="wrap">
	<div class="grid">
		<!-- Базові -->
		<Card title="Buttons" subtitle="variant × size" class="wide">
			<div class="stack">
				{#each variants as v (v)}
					<div class="row">
						<span class="lbl">{v}</span>
						{#each sizes as s (s)}
							<Button variant={v} size={s}>Кнопка {s}</Button>
						{/each}
					</div>
				{/each}
				<Divider />
				<div class="row">
					<span class="lbl">icon</span>
					<Button icon={Plus}>Додати</Button>
					<Button iconRight={ChevronRight} variant="secondary">Далі</Button>
					<Button icon={Download} iconRight={ChevronRight} variant="soft">Обидві</Button>
					<Button href="#top" variant="ghost">Як посилання</Button>
				</div>
				<div class="row">
					<span class="lbl">loading</span>
					{#each variants as v (v)}
						<Button variant={v} loading>Завантаження</Button>
					{/each}
				</div>
				<div class="row">
					<span class="lbl">disabled</span>
					{#each variants as v (v)}
						<Button variant={v} disabled>Вимкнено</Button>
					{/each}
				</div>
				<div class="col">
					<span class="lbl">block</span>
					<Button block>На всю ширину</Button>
					<Button block variant="secondary" icon={Mail}>Block secondary</Button>
				</div>
			</div>
		</Card>

		<Card title="IconButton" subtitle="variant × size">
			<div class="stack">
				{#each iconVariants as v (v)}
					<div class="row">
						<span class="lbl">{v}</span>
						{#each sizes as s (s)}
							<IconButton icon={Settings} label="Налаштування" variant={v} size={s} />
						{/each}
						<IconButton icon={Trash2} label="Видалити" variant={v} disabled />
					</div>
				{/each}
			</div>
		</Card>

		<Card title="Badges" subtitle="tone × variant">
			<div class="stack">
				{#each badgeVariants as bv (bv)}
					<div class="row">
						<span class="lbl">{bv}</span>
						{#each tones as t (t)}
							<Badge tone={t} variant={bv}>{t}</Badge>
						{/each}
					</div>
				{/each}
				<div class="row">
					<span class="lbl">icon / sm</span>
					<Badge icon={Check} tone="success">Готово</Badge>
					<Badge icon={Bell} tone="warning" size="sm">Увага</Badge>
					<Badge tone="accent" variant="solid" size="sm">sm</Badge>
				</div>
			</div>
		</Card>

		<Card title="GradeBadge" subtitle="шкала 12 і 5">
			<div class="stack">
				{#each sizes as s (s)}
					<div class="row">
						<span class="lbl">{s}</span>
						{#each grades as g (g)}
							<GradeBadge value={g} size={s} />
						{/each}
					</div>
				{/each}
				<div class="row">
					<span class="lbl">scale 5</span>
					{#each [5, 4.5, 4, 3, 2, null] as g (g)}
						<GradeBadge value={g} scale={5} />
					{/each}
				</div>
			</div>
		</Card>

		<Card title="Avatar">
			<div class="stack">
				<div class="row">
					<span class="lbl">без src</span>
					<Avatar size="xs" name="Іван Петренко" />
					<Avatar size="sm" name="Іван Петренко" />
					<Avatar size="md" name="Іван Петренко" />
					<Avatar size="lg" name="Іван Петренко" />
					<Avatar size="xl" name="Іван Петренко" />
					<Avatar />
				</div>
				<div class="row">
					<span class="lbl">з src</span>
					<Avatar size="md" name="Оля" src="/favicon.svg" />
					<Avatar size="lg" name="Оля" src="/favicon.svg" />
					<Avatar size="lg" name="Помилка" src="/nope-404.png" />
					<Avatar size={64} name="Число" />
				</div>
			</div>
		</Card>

		<Card title="Skeleton">
			<div class="stack">
				<Skeleton height={20} width="60%" />
				<Skeleton lines={3} />
				<div class="row">
					<Skeleton width={48} height={48} radius="var(--radius-full)" />
					<div class="grow"><Skeleton lines={2} /></div>
				</div>
			</div>
		</Card>

		<Card title="EmptyState">
			<EmptyState title="Поки порожньо" description="Тут з'являться твої дані.">
				{#snippet action()}
					<Button icon={Plus} size="sm">Додати</Button>
				{/snippet}
			</EmptyState>
			<Divider />
			<EmptyState icon={Search} title="Нічого не знайдено" />
		</Card>

		<Card title="ErrorState">
			<ErrorState description="Не вдалося завантажити дані." onretry={retry} />
			<Divider />
			<ErrorState title="Немає доступу" description="Без кнопки повтору." />
		</Card>

		<Card title="PageHeader" subtitle="приклад" class="wide">
			<PageHeader title="Журнал" subtitle="Оцінки за поточний семестр" icon={Inbox}>
				{#snippet actions()}
					<Button size="sm" variant="secondary" icon={Download}>Експорт</Button>
					<Button size="sm" icon={Plus}>Додати</Button>
				{/snippet}
				<Tabs items={tabItems.slice(0, 3)} bind:value={tab} aria-label="Розділи" />
			</PageHeader>
		</Card>

		<Card title="Divider">
			<p class="muted">Горизонтальні відступи</p>
			{#each ['none', 'sm', 'md', 'lg'] as const as sp (sp)}
				<Divider spacing={sp} />
				<span class="muted">spacing: {sp}</span>
			{/each}
			<Divider />
			<div class="row vdiv">
				<span>Ліворуч</span>
				<Divider vertical />
				<span>Праворуч</span>
			</div>
		</Card>

		<!-- Форми -->
		<Card title="Field + Input">
			<div class="stack">
				<Field label="Звичайне" hint="Підказка під полем">
					{#snippet children({ id, describedBy, invalid })}
						<Input {id} bind:value={text} placeholder="Введи текст" aria-describedby={describedBy} {invalid} />
					{/snippet}
				</Field>
				<Field label="З іконкою" required>
					{#snippet children({ id, describedBy, invalid })}
						<Input {id} icon={Mail} placeholder="email@example.com" aria-describedby={describedBy} {invalid} />
					{/snippet}
				</Field>
				<Field label="З помилкою" error="Мінімум 6 символів">
					{#snippet children({ id, describedBy, invalid })}
						<Input {id} bind:value={invalidText} aria-describedby={describedBy} {invalid} />
					{/snippet}
				</Field>
				<Field label="Пароль">
					{#snippet children({ id, describedBy, invalid })}
						<Input {id} type="password" bind:value={pass} aria-describedby={describedBy} {invalid} />
					{/snippet}
				</Field>
				<Field label="Вимкнене">
					{#snippet children({ id })}
						<Input {id} value="Недоступно" disabled />
					{/snippet}
				</Field>
				<div class="row">
					<Input size="sm" placeholder="sm" />
					<Input size="lg" placeholder="lg" />
				</div>
			</div>
		</Card>

		<Card title="Textarea">
			<div class="stack">
				<Field label="З лічильником" hint="До 120 символів">
					{#snippet children({ id, describedBy, invalid })}
						<Textarea {id} bind:value={bio} showCount maxlength={120} aria-describedby={describedBy} {invalid} />
					{/snippet}
				</Field>
				<Field label="Autoresize (до 6 рядків)">
					{#snippet children({ id })}
						<Textarea {id} bind:value={auto} autoresize rows={2} maxRows={6} placeholder="Пиши кілька рядків..." />
					{/snippet}
				</Field>
				<Textarea invalid value="Невалідне" />
			</div>
		</Card>

		<Card title="Select · Switch · Checkbox">
			<div class="stack">
				<Field label="Select (options)">
					{#snippet children({ id })}
						<Select {id} bind:value={sel} {options} />
					{/snippet}
				</Field>
				<Select value="x" invalid>
					<option value="x">Select invalid (children)</option>
					<option value="y">Інший</option>
				</Select>
				<Select value="a" {options} disabled />
				<Divider />
				<div class="row">
					<Switch bind:checked={sw} label="Перемикач" />
					<span>{sw ? 'Увімкнено' : 'Вимкнено'}</span>
					<Switch checked disabled label="Вимкнений" />
				</div>
				<Divider />
				<Checkbox bind:checked={cbA} label="Вибрано" description="З описом" />
				<Checkbox bind:checked={cbB} label="Не вибрано" />
				<Checkbox bind:checked={cbInd} indeterminate label="Невизначений" />
				<Checkbox checked disabled label="Вимкнений" />
			</div>
		</Card>

		<Card title="SettingRow" padding="none">
			<SettingRow
				icon={Bell}
				title="Сповіщення"
				description="Клік по рядку перемикає"
				bind:checked={rowA}
				onchange={(c) => showToast(c ? 'Увімкнено' : 'Вимкнено')}
			/>
			<SettingRow icon={User} title="Профіль" description="Посилання" href="#top" />
			<SettingRow
				icon={Settings}
				title="Дія"
				description="onclick"
				onclick={() => showToast('Клік по рядку')}
			/>
			<SettingRow title="Власний control" description="snippet праворуч">
				{#snippet control()}
					<Badge tone="success">OK</Badge>
				{/snippet}
			</SettingRow>
			<SettingRow icon={Settings} title="Вимкнений" checked={false} disabled />
		</Card>

		<Card title="Segmented · Tabs">
			<div class="stack">
				<Segmented items={segItems} bind:value={seg} aria-label="Період" />
				<Segmented items={segItems} bind:value={seg} size="sm" block aria-label="Період (block)" />
				<Divider />
				<Tabs items={tabItems} bind:value={tab} aria-label="Таби" />
				<Tabs items={tabItems.slice(0, 3)} bind:value={tab} size="sm" block aria-label="Таби (block)" />
				<span class="muted">seg: {seg} · tab: {tab}</span>
			</div>
		</Card>

		<Card title="SearchField · CopyButton · Stepper">
			<div class="stack">
				<SearchField bind:value={query} debounce={200} />
				<SearchField size="sm" placeholder="sm" />
				<span class="muted">Запит: {query || '—'}</span>
				<Divider />
				<div class="row">
					<CopyButton text="m1-id-demo" />
					<CopyButton text="m1-id-demo" size="sm" toast />
					<CopyButton text="m1-id-demo" variant="button" label="Копіювати код" toast />
				</div>
				<Divider />
				<div class="row">
					<Stepper bind:value={qty} min={0} max={10} />
					<span>{qty}</span>
					<Stepper value={1} disabled />
				</div>
			</div>
		</Card>

		<!-- Оверлеї -->
		<Card title="Dialog" subtitle="sm / md / lg">
			<div class="row">
				<Button variant="secondary" onclick={() => (dlgSm = true)}>sm</Button>
				<Button variant="secondary" onclick={() => (dlgMd = true)}>md + footer</Button>
				<Button variant="secondary" onclick={() => (dlgLg = true)}>lg + footer</Button>
			</div>
		</Card>

		<Card title="confirm() + toast">
			<div class="row">
				<Button onclick={() => ask(false)}>Підтвердити</Button>
				<Button variant="danger" onclick={() => ask(true)}>Небезпечно</Button>
				<Button variant="ghost" onclick={() => showToast('Просто тост')}>Тост</Button>
			</div>
		</Card>

		<Card title="Popover · Tooltip">
			<div class="row">
				<span bind:this={popAnchor} class="anchor">
					<Button variant="secondary" onclick={() => (popOpen = !popOpen)}>Popover</Button>
				</span>
				<Popover bind:open={popOpen} anchor={popAnchor} label="Приклад поповера" sheetOnMobile>
					<div class="pop">
						<strong>Поповер</strong>
						<p class="muted">Прив'язаний до кнопки. Esc або клік поза ним закриває.</p>
						<Button size="sm" onclick={() => (popOpen = false)}>Закрити</Button>
					</div>
				</Popover>

				<Popover placement="bottom-end" label="Через trigger">
					{#snippet trigger({ toggle })}
						<Button variant="soft" onclick={toggle}>Через trigger</Button>
					{/snippet}
					<div class="pop">Вміст поповера через snippet trigger.</div>
				</Popover>

				<Tooltip label="Підказка зверху">
					<Button variant="ghost" icon={Info}>Tooltip</Button>
				</Tooltip>
				<Tooltip label="Підказка знизу" placement="bottom">
					<IconButton icon={Bell} label="Сповіщення" />
				</Tooltip>
			</div>
		</Card>
	</div>
</div>

<Dialog bind:open={dlgSm} size="sm" title="Малий діалог" description="Опис діалогу">
	<p>Вміст малого діалогу.</p>
</Dialog>

<Dialog bind:open={dlgMd} size="md" title="Середній діалог" description="З футером">
	<div class="stack">
		<Field label="Назва">
			{#snippet children({ id })}
				<Input {id} placeholder="Введи назву" />
			{/snippet}
		</Field>
		<p class="muted">Esc, клік по overlay та кнопка закриття працюють.</p>
	</div>
	{#snippet footer()}
		<Button variant="ghost" onclick={() => (dlgMd = false)}>Скасувати</Button>
		<Button
			onclick={() => {
				dlgMd = false;
				showToast('Збережено');
			}}>Зберегти</Button
		>
	{/snippet}
</Dialog>

<Dialog bind:open={dlgLg} size="lg" title="Великий діалог">
	<div class="stack">
		{#each Array(12) as _, i (i)}
			<p>Рядок {i + 1}. Довгий вміст для перевірки прокручування всередині діалогу.</p>
		{/each}
	</div>
	{#snippet footer()}
		<Button variant="secondary" onclick={() => (dlgLg = false)}>Закрити</Button>
	{/snippet}
</Dialog>

<style>
	.topbar {
		position: sticky;
		top: 0;
		z-index: var(--z-sticky);
		background: color-mix(in srgb, var(--color-bg) 85%, transparent);
		backdrop-filter: blur(8px);
		border-bottom: 1px solid var(--color-border);
	}
	.topbar-in {
		max-width: 1100px;
		margin: 0 auto;
		padding: var(--space-3) var(--space-4);
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3);
	}
	.brand {
		font-size: var(--text-lg);
		font-weight: var(--weight-bold);
		color: var(--color-text);
	}
	.controls {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-3);
	}
	.accents {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}
	.swatch {
		width: 22px;
		height: 22px;
		border-radius: var(--radius-full);
		border: 2px solid var(--color-bg);
		outline: 1px solid var(--color-border-strong);
		cursor: pointer;
		padding: 0;
	}
	.swatch.active {
		outline: 2px solid var(--color-text);
	}
	.swatch:focus-visible {
		outline: 2px solid var(--color-accent);
		outline-offset: 2px;
	}
	.wrap {
		max-width: 1100px;
		margin: 0 auto;
		padding: var(--space-4);
	}
	.grid {
		display: grid;
		grid-template-columns: 1fr;
		gap: var(--space-4);
		align-items: start;
	}
	.grid > :global(.wide) {
		grid-column: 1 / -1;
	}
	@media (min-width: 900px) {
		.wrap {
			padding: var(--space-6);
		}
		.grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
			gap: var(--space-6);
		}
	}
	.stack {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.col {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
	}
	.vdiv {
		height: 32px;
		gap: var(--space-3);
	}
	.grow {
		flex: 1;
		min-width: 0;
	}
	.lbl {
		min-width: 72px;
		font-size: var(--text-xs);
		color: var(--color-text-subtle);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.muted {
		margin: 0;
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}
	.pop {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--space-2);
		padding: var(--space-3);
		max-width: 260px;
		color: var(--color-text);
		font-size: var(--text-sm);
	}
	.pop p {
		margin: 0;
	}
	.anchor {
		display: inline-flex;
	}
</style>
