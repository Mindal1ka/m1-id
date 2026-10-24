<script lang="ts">
	import { tick } from 'svelte';
	import { AnimatedNumber, stagger, pressable } from '$lib/motion';
	import { ArrowUpDown, BookOpen, Link2, Shapes, UserRound } from '@lucide/svelte';
	import { Dropdown } from '$lib/ui';
	import type { HomeworkView as HwView, HwItem } from '$lib/api/client';
	import { MONTHS_UK } from '$lib/sections';
	import { fmtDate, mkCls, cleanTeacher, hwKindLabel, hwKindTag } from '$lib/app/helpers';

	interface Props {
		hw: HwView | null;
		/** Вкладка зараз вантажиться (скелет/«Завантаження…»). */
		busy: boolean;
		/** 'all' або ключ типу (essay, test, practice_work, …) */
		hwType: string;
		hwSubject: string;
		hwStatus: 'all' | '3' | '2' | '1';
		hwSort: 'deadline_asc' | 'deadline_desc' | 'new' | 'old';
		onopen: (h: HwItem) => void;
		onm1: () => void;
	}
	// фільтри живуть у батьківській сторінці (переживають перемикання вкладок)
	let {
		hw,
		busy,
		hwType = $bindable(),
		hwSubject = $bindable(),
		hwStatus = $bindable(),
		hwSort = $bindable(),
		onopen,
		onm1
	}: Props = $props();

	/* ── ковзний індикатор вкладок статусу (translate + scaleX) ── */
	let tabsEl = $state<HTMLDivElement>();
	let ix = $state({ x: 0, y: 0, w: 0, h: 0, ready: false });
	let ixFirst = $state(true);

	function measureTab() {
		const el = tabsEl?.querySelector<HTMLElement>('.f-active[data-st]');
		if (!el) return;
		const next = { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight, ready: true };
		const wasReady = ix.ready;
		ix = next;
		// перший замір — без пружини, щоб індикатор не «летів» з нуля
		ixFirst = !wasReady;
	}

	$effect(() => {
		hwStatus;
		tick().then(measureTab);
	});
	$effect(() => {
		if (!tabsEl) return;
		const ro = new ResizeObserver(() => measureTab());
		ro.observe(tabsEl);
		return () => ro.disconnect();
	});

	/** Ключ «справжньої» зміни вигляду (фільтри/сортування). Оновлення даних
	 *  (revalidate) його не міняє → вхідна хореографія не програється вдруге. */
	const viewKey = $derived(`${hwType}|${hwSubject}|${hwStatus}|${hwSort}`);

	const SORTS = [
		{ value: 'deadline_asc', label: 'Дедлайн', hint: 'спочатку ближчі' },
		{ value: 'deadline_desc', label: 'Дедлайн', hint: 'спочатку далекі' },
		{ value: 'new', label: 'Створення', hint: 'спочатку нові' },
		{ value: 'old', label: 'Створення', hint: 'спочатку старі' }
	];

	/** Типи, що реально є в даних (порядок появи): фільтр будується з них,
	 *  тож новий тип від MyStat з'являється сам. */
	const kinds = $derived.by(() => {
		const seen: string[] = [];
		for (const h of hw?.items ?? []) {
			const k = h.kind ?? 'independent_work';
			if (!seen.includes(k)) seen.push(k);
		}
		return seen;
	});

	/** Число завдань у фільтрі (для AnimatedNumber). */
	const shownCount = $derived(visibleHw().length);

	function visibleHw() {
		let list = hw?.items ?? [];
		if (hwType !== 'all') list = list.filter((h) => (h.kind ?? 'independent_work') === hwType);
		if (hwSubject !== 'all') list = list.filter((h) => h.subject === hwSubject);
		if (hwStatus !== 'all') list = list.filter((h) => String(h.status) === hwStatus);
		if (hwSort === 'deadline_desc') {
			list = [...list].sort((a, b) => (b.due ?? '').localeCompare(a.due ?? ''));
		} else if (hwSort === 'new') {
			list = [...list].sort((a, b) =>
				(b.assigned ?? '').localeCompare(a.assigned ?? ''));
		} else if (hwSort === 'old') {
			list = [...list].sort((a, b) =>
				(a.assigned ?? '').localeCompare(b.assigned ?? ''));
		}
		// deadline_asc — бекенд уже віддає в такому порядку
		return list;
	}

	/** Групування за місяцями (як у MyStat): ключ — місяць дедлайну,
	 *  або місяця видачі для сортувань «нові/старі». */
	function hwGroups() {
		const byAssigned = hwSort === 'new' || hwSort === 'old';
		const curYear = new Date().getFullYear();
		const groups: { key: string; label: string; items: HwItem[] }[] = [];
		const idx = new Map<string, number>();
		for (const h of visibleHw()) {
			const iso = (byAssigned ? h.assigned : h.due) ?? h.due ?? h.assigned ?? '';
			const key = iso.slice(0, 7) || '--';
			let gi = idx.get(key);
			if (gi === undefined) {
				const y = Number(key.slice(0, 4));
				const m = MONTHS_UK[Number(key.slice(5, 7)) - 1] ?? '';
				const label =
					key === '--' ? 'Без дати' : y === curYear || !y ? m : `${m} ${y}`;
				gi = groups.length;
				idx.set(key, gi);
				groups.push({ key, label, items: [] });
			}
			groups[gi]!.items.push(h);
		}
		return groups;
	}
</script>

					<div class="hw-tabs" class:ix-on={ix.ready} bind:this={tabsEl}>
						<span class="hw-ix" aria-hidden="true" class:no-anim={ixFirst}
							style="--ix-x:{ix.x}px; --ix-y:{ix.y}px; --ix-sx:{ix.w / 100}; --ix-h:{ix.h}px"></span>
						<button class="btn f" data-st="all" use:pressable class:f-active={hwStatus === 'all'}
							onclick={() => (hwStatus = 'all')}>Усі</button>
						<button class="btn f" data-st="3" use:pressable class:f-active={hwStatus === '3'}
							onclick={() => (hwStatus = '3')}>До виконання</button>
						<button class="btn f" data-st="2" use:pressable class:f-active={hwStatus === '2'}
							onclick={() => (hwStatus = '2')}>На перевірці</button>
						<button class="btn f" data-st="1" use:pressable class:f-active={hwStatus === '1'}
							onclick={() => (hwStatus = '1')}>Виконані</button>
						<button class="btn f m1-btn" title="M1 Provider — усі посилання"
							onclick={() => onm1()}>
							<Link2 size={13} /> M1
						</button>
					</div>
					<div class="hw-toolbar">
						<Dropdown
							label="Тип"
							icon={Shapes}
							value={hwType}
							resetValue="all"
							options={[
								{ value: 'all', label: 'Всі типи', short: 'Всі' },
								...kinds.map((k) => ({ value: k, label: hwKindLabel(k) }))
							]}
							onchange={(v) => (hwType = v)}
						/>
						<Dropdown
							label="Предмет"
							icon={BookOpen}
							value={hwSubject}
							resetValue="all"
							options={[
								{ value: 'all', label: 'Всі предмети', short: 'Всі' },
								...(hw?.subjects ?? []).map((s) => ({ value: s, label: s }))
							]}
							onchange={(v) => (hwSubject = v)}
						/>
						<Dropdown
							label="Сортування"
							icon={ArrowUpDown}
							value={hwSort}
							resetValue="deadline_asc"
							searchable={false}
							options={SORTS}
							onchange={(v) => (hwSort = v as typeof hwSort)}
						/>
						<span class="hw-total text-faint small">
							Завдань: <AnimatedNumber value={shownCount} duration={500} />{#if hw && shownCount !== hw.total}
								{' / '}<AnimatedNumber value={hw.total} duration={500} />{/if}</span>
					</div>
					{#if hw && visibleHw().length}
						{#key viewKey}
						<div class="hw-list" use:stagger={{ selector: '.hw-m-title, .hw-tile', step: 26, max: 12, y: 8 }}>
						{#each hwGroups() as g (g.key)}
							<section class="hw-month">
								<h3 class="hw-m-title">{g.label}</h3>
								<div class="hw-grid">
								{#each g.items as h, i (h.id + '-' + i)}
								{@const cls = { 3: 'c-accent', 2: 'c-cyan', 1: 'c-success', 5: 'c-danger' }[h.status] ?? ''}
								<div class="glass card hw-tile lift {cls} clickable"
									use:pressable={{ scale: 0.985 }}
									role="button"
									tabindex="0"
									title="Деталі завдання"
									onclick={() => onopen(h)}
									onkeydown={(e) => {
										if (e.key === 'Enter' || e.key === ' ') {
											e.preventDefault();
											onopen(h);
										}
									}}>
									<div class="hw-t-top">
										<b>{h.title}</b>
										{#if h.mark}
											<span class="mark-chip {mkCls(h.mark)}">{h.mark}</span>
										{/if}
									</div>
									<span class="hw-t-subj text-dim small">
										{h.subject}{#if hwKindTag(h.kind)} · {hwKindTag(h.kind).toLowerCase()}{/if}{#if h.is_retake} · ретейк{/if}</span>
									<div class="hw-t-foot">
										{#if h.overdue_days}
											<span class="due-chip late pulse">Прострочено: {h.overdue_days} дн.</span>
										{:else if h.due}
											<span class="due-chip">{fmtDate(h.due)}</span>
										{:else}
											<span class="due-chip text-faint">без дедлайну</span>
										{/if}
										{#if h.teacher}
											<span class="hw-t-teach" title={cleanTeacher(h.teacher)}>
												<UserRound size={11} /> {cleanTeacher(h.teacher)}
											</span>
										{/if}
										<span class="text-faint small hw-t-status">{h.status_label}</span>
									</div>
								</div>
								{/each}
								</div>
							</section>
						{/each}
						</div>
						{/key}
					{:else}
						<p class="text-faint empty">
							{#if busy}Завантаження…{:else if hw && hw.total}
								Нічого не знайдено за фільтром{:else}Тут порожньо{/if}
						</p>
{/if}

<style>

	/* ── меню профілю: поповер над кнопкою ── */

	/* ================= сітка дашборду ================= */

	.card {
		padding: 18px;
		border-radius: var(--radius-lg);
		display: flex;
		flex-direction: column;
		gap: 12px;
		min-width: 0;
	}

	.span-5 { grid-column: span 5; }
	.span-7 { grid-column: span 7; }
	.span-12 { grid-column: span 12; }

	/* довга назва не виштовхує чипи */

	.due-chip {
		background: var(--surface-2);
		border-radius: 999px;
		padding: 4px 10px;
		font-size: 12px;
		font-weight: 700;
		white-space: nowrap;
	}

	/* База — нейтральна; колір задає mkCls (hi/mid/low), як у віджетах */
	.mark-chip {
		background: var(--surface-2);
		color: var(--text-dim);
		font-weight: 800;
		border-radius: 999px;
		padding: 3px 10px;
		font-size: 13px;
	}

	.small {
		font-size: 11.5px;
	}

	/* ================= розклад ================= */

	.btn.f {
		font-size: 13px;
		padding: 7px 12px;
	}

	.f-active {
		background: var(--accent);
		color: #fff;
		border-color: transparent;
	}

	/* коли індикатор виміряно, фон активної вкладки малює він */
	.hw-tabs {
		position: relative;
	}
	.hw-tabs > .btn {
		position: relative;
		z-index: 1;
	}
	.hw-tabs.ix-on > .f-active[data-st] {
		background: transparent;
	}
	.hw-ix {
		position: absolute;
		left: 0;
		top: 0;
		width: 100px;
		height: var(--ix-h);
		border-radius: var(--radius-sm);
		background: var(--accent);
		pointer-events: none;
		z-index: 0;
		transform-origin: 0 0;
		transform: translate(var(--ix-x), var(--ix-y)) scaleX(var(--ix-sx));
		transition: transform 480ms var(--ease-spring);
		will-change: transform;
	}
	.hw-ix.no-anim {
		transition: none;
	}
	:global(html[data-anim='off']) .hw-ix {
		transition: none;
	}

	/* Рядок уроку = стиль віджета «Сьогодні»: прозорий рядок з м'яким
	   hover замість плаского сірого бокса; час — жирний праворуч. */
	.lesson {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 9px 10px;
		background: transparent;
		border-radius: var(--radius-sm);
		transition: background 0.14s ease;
	}

	/* ── оцінки та екзамени ── */

	.mark-chip.hi {
		background: var(--success);
		color: #fff;
	}

	.mark-chip.mid {
		background: var(--amber);
		color: #fff;
	}

	.mark-chip.low {
		background: var(--danger);
		color: #fff;
	}

	/* «Не був» — помітний мінус-чип (стилів не було взагалі) */

	.hw-tabs {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
		margin-bottom: 12px;
	}

	.hw-toolbar {
		display: flex;
		align-items: center;
		gap: 10px;
		flex-wrap: wrap;
		margin-bottom: 14px;
	}

	/* Dropdown (UI-кіт) живе в обгортці Popover `.trigger` — розтягуємо її, не кнопку */
	.hw-toolbar :global(.trigger) {
		min-width: 0;
	}
	.hw-toolbar :global(.dd-btn) {
		width: 100%;
	}

	.hw-total {
		margin-left: auto;
		white-space: nowrap;
	}

	/* сітка плиток: 1 колонка на телефоні → 3-4 на широкому ПК */
	.hw-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(min(100%, 330px), 1fr));
		gap: 10px;
	}

	.hw-month {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	/* довгі списки: поза екраном не рахуємо layout/paint */
	.hw-month {
		content-visibility: auto;
		contain-intrinsic-size: auto 360px;
	}

	.hw-month + .hw-month {
		margin-top: 18px;
	}

	/* заголовок місяця «прилипає» при скролі */
	.hw-m-title {
		position: sticky;
		top: 0;
		z-index: 2;
		padding: 6px 2px;
		-webkit-backdrop-filter: blur(calc(10px + 0px));
		backdrop-filter: blur(10px);
		background: linear-gradient(var(--bg-a85, rgba(11, 12, 15, 0.85)), transparent);
		margin: 2px 0 0;
		font-size: 13px;
		font-weight: 700;
		color: var(--text);
	}

	.hw-tile {
		display: flex;
		flex-direction: column;
		gap: 5px;
		padding: 12px 14px;
		border-left: 3px solid var(--text-faint);
		/* щільне скло 65% прозорості */
		background: var(--surface-a65, rgba(16,19,27,0.65));
	}

	.c-accent.hw-tile { border-left-color: var(--accent); }
	.c-cyan.hw-tile { border-left-color: var(--cyan); }
	.c-success.hw-tile { border-left-color: var(--success); }
	.c-danger.hw-tile { border-left-color: var(--danger); }

	/* підйом на hover дає .lift (motion.css) — тут лише рамка й тінь */
	.hw-tile.clickable {
		cursor: pointer;
	}

	.hw-tile.clickable:hover {
		border-color: var(--accent);
		box-shadow: 0 10px 26px rgba(108, 124, 255, 0.14);
	}

	.hw-tile.clickable:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}

	.hw-t-top {
		display: flex;
		align-items: center;
		gap: 8px;
		min-width: 0;
	}

	.hw-t-top b {
		flex: 1;
		font-size: 14px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.hw-t-subj {
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.hw-t-foot {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		margin-top: 3px;
	}

	.hw-t-teach {
		flex: 1 1 auto;
		min-width: 0;
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-size: 12px;
		color: var(--text-faint);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.hw-t-teach :global(svg) {
		flex-shrink: 0;
	}

	.hw-t-status {
		white-space: nowrap;
	}

	.due-chip.late {
		color: var(--danger);
		border-color: rgba(248, 113, 113, 0.35);
		background: rgba(248, 113, 113, 0.08);
	}

	/* прострочено: ледь помітний пульс (opacity/transform) */
	.due-chip.pulse {
		animation: hw-late-pulse 2.6s ease-in-out infinite;
	}
	@keyframes hw-late-pulse {
		0%, 100% { opacity: 1; transform: scale(1); }
		50% { opacity: 0.72; transform: scale(0.97); }
	}
	:global(html[data-anim='off']) .due-chip.pulse {
		animation: none;
	}

	@media (max-width: 900px) {
		/* на телефоні: два фільтри в рядок, сортування — на всю ширину */
		.hw-toolbar :global(.trigger) {
			flex: 1 1 calc(50% - 5px);
		}
		.hw-toolbar :global(.trigger:last-of-type) {
			flex-basis: 100%;
		}
		.hw-toolbar :global(.dd-val) {
			max-width: none;
		}

		.hw-total {
			margin-left: 0;
			width: 100%;
		}

		.hw-tile {
			padding: 10px 12px;
		}
	}

	/* ── захист плиток від «мімо-кліків» під час скрола ──
	   1) cooldown: 160мс після останньої scroll-події клік/hover
	      по картках не проходить (pointer-events: none);
	   2) tapGuard (use: на .grid) гасить кліки зі зсувом >8px
	      від точки натискання;
	   3) touch-action: pan-y — вертикальний жест завжди віддається
	      скролу; драг/резайз у режимі редагування живуть на грипі
	      та ресайзерах із touch-action: none. */

	@media (max-width: 900px) {

		/* будь-яка ширина віджета -> на всю колонку телефону */
		.span-4, .span-5, .span-6, .span-7, .span-8 {
			grid-column: span 12;
		}

		/* віджети на телефоні: компактніше, щільніше, живіше */

		.card {
			padding: 14px;
			border-radius: 18px;
		}

	}

	@media (min-width: 901px) and (max-width: 1180px) {
		.span-5 {
			grid-column: span 12;
		}

		.span-7 {
			grid-column: span 12;
		}
	}

	.empty {
		padding: 28px 4px;
	}

	/* додаткові ширини віджетів */
	.span-4 {
		grid-column: span 4;
	}
	.span-6 {
		grid-column: span 6;
	}
	.span-8 {
		grid-column: span 8;
	}
	.span-9 {
		grid-column: span 9;
	}
	.span-10 {
		grid-column: span 10;
	}
	.span-11 {
		grid-column: span 11;
	}

</style>

