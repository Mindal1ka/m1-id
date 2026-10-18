<script lang="ts">
	import { LayoutGrid, List } from '@lucide/svelte';
	import { stagger, pressable, canHover } from '$lib/motion';
	import { hoverCard } from '$lib/app/hovercards.svelte';
	import { MONTHS_UK } from '$lib/sections';
	import type { MarkItem, MarksView } from '$lib/api/client';

	let {
		marks = null,
		/** Скільки місяців показати у сітці (0 — усі). Решта — кнопка «Усі оцінки». */
		limitMonths = 0,
		/** Зафіксувати вигляд і сховати перемикач (віджет на Головній). */
		fixedView = null as 'grid' | 'list' | null,
		onshowall
	}: {
		marks?: MarksView | null;
		limitMonths?: number;
		fixedView?: 'grid' | 'list' | null;
		onshowall?: () => void;
	} = $props();

	// Джерело правди — бандл MyStat (chunk-DUWT0k1i.js):
	// testing=0 · coursework=1 · exam=2 · home_work=3 · practice=4 ·
	// classwork=5 · control_work=6 · thematic_work=7
	// кольори оригінала: 5 violet · 0 green · 7 rose · 6 yellow · 3 blue ·
	// 2 orange · 4 salad (клас rate__*-mark)
	type MarkTypeCfg = { id: number; label: string; cls: string };

	const MARK_TYPES: MarkTypeCfg[] = [
		{ id: 5, label: 'Класна робота', cls: 'tw-violet' },
		{ id: 3, label: 'Самостійна робота', cls: 'tw-blue' },
		{ id: 6, label: 'Контрольні', cls: 'tw-yellow' },
		{ id: 2, label: 'Екзамен', cls: 'tw-orange' },
		{ id: 7, label: 'Тематична', cls: 'tw-rose' },
		{ id: 0, label: 'Тестування', cls: 'tw-green' },
		{ id: 4, label: 'Практична', cls: 'tw-salad' }
	];
	// дефолтні увімкнені фільтри — як в оригінальному клієнті
	const MK_DEFAULT_ON = [5, 3, 0, 6, 2, 7, 4];

	// фіксуємось на початковому значенні навмисно (віджет без перемикача)
	// svelte-ignore state_referenced_locally
	let view = $state<'grid' | 'list'>(fixedView ?? 'grid');
	const mkInit: Record<number, boolean> = {};
	for (const t of MARK_TYPES) mkInit[t.id] = MK_DEFAULT_ON.includes(t.id);
	let filters = $state<Record<number, boolean>>(mkInit);

	type MkItem = MarkItem & { tw: number };

	function twOf(tw: string | number | null | undefined): number {
		const v = Number(tw);
		return Number.isFinite(v) ? v : 5;
	}

	function twCls(tw: number): string {
		return MARK_TYPES.find((t) => t.id === tw)?.cls ?? 'tw-violet';
	}

	function twLabel(tw: number): string {
		return MARK_TYPES.find((t) => t.id === tw)?.label ?? 'Оцінка';
	}

	function toggleFilter(id: number): void {
		filters = { ...filters, [id]: !filters[id] };
		hoverCard.close();
	}

	// ⚠️ старий кеш localStorage міг зберегти MarksView без items/subjects —
	// ітеруємо тільки перевірені масиви (TypeError: not iterable)
	const items = $derived<MarkItem[]>(Array.isArray(marks?.items) ? marks!.items! : []);

	/** Місяці з оцінками: новіші зверху, всередині — новіші перші. */
	const allMonths = $derived.by(() => {
		const byMonth = new Map<string, MkItem[]>();
		for (const m of items) {
			if (filters[twOf(m.type_work)] === false) continue;
			const key = String(m.date ?? '').slice(0, 7);
			if (!key) continue;
			const arr = byMonth.get(key) ?? [];
			arr.push({ ...m, tw: twOf(m.type_work) });
			byMonth.set(key, arr);
		}
		const all = [...byMonth.entries()]
			.sort((a, b) => b[0].localeCompare(a[0]))
			.map(([key, arr]) => ({
				key,
				label: monthLabel(key),
				items: arr.sort((a, b) => String(b.date).localeCompare(String(a.date)))
			}));
		return all;
	});

	/** Списковий вигляд: ті самі оцінки, згруповані за предметом. */
	const bySubject = $derived.by(() => {
		const map = new Map<
			string,
			{ subject: string; avg?: number; items: MkItem[] }
		>();
		if (Array.isArray(marks?.subjects)) {
			for (const s of marks!.subjects!) {
				map.set(s.subject, { subject: s.subject, avg: s.avg, items: [] });
			}
		}
		for (const m of items) {
			if (filters[twOf(m.type_work)] === false) continue;
			const row =
				map.get(m.subject) ?? { subject: m.subject, items: [] as MkItem[] };
			row.items.push({ ...m, tw: twOf(m.type_work) });
			map.set(m.subject, row);
		}
		return [...map.values()]
			.filter((r) => r.items.length > 0)
			.sort((a, b) => b.items.length - a.items.length);
	});

	// ── безкінечне листання ──
	// Спочатку PAGE груп, далі авто-дозавантаження при скролі (sentinel)
	// + кнопка-фолбек. На Головній (limitMonths>0) листання вимкнене.
	const PAGE = 8;
	let shown = $state(PAGE);

	// зміна виду або фільтрів → скидаємо сторінку
	$effect(() => {
		void view;
		void filters;
		shown = PAGE;
	});

	const visibleMonths = $derived(
		limitMonths > 0
			? allMonths.slice(0, limitMonths)
			: allMonths.slice(0, shown)
	);
	const visibleSubjects = $derived(
		limitMonths > 0 ? bySubject : bySubject.slice(0, shown)
	);
	const hiddenCount = $derived(
		limitMonths > 0
			? items.length - visibleMonths.reduce((n, mo) => n + mo.items.length, 0)
			: 0
	);
	/** Скільки груп ще сховано (0 → sentinel не рендериться). */
	const moreCount = $derived(
		limitMonths > 0 ? 0 : allMonths.length - visibleMonths.length
	);

	// авто-дозавантаження: sentinel біля низу скрол-бокса → ще сторінка груп.
	// root — сам бокс (скрол всередині картки, а не сторінки). Після кожного
	// shown += PAGE змінюється moreCount → ефект перезапускається, обсервер
	// стартує заново: якщо sentinel досі у зоні — додається ще сторінка,
	// поки бокс не заповниться або групи не скінченяться.
	let scroller = $state<HTMLElement | null>(null);
	let sentinel = $state<HTMLElement | null>(null);
	$effect(() => {
		const root = scroller;
		const el = sentinel;
		if (!root || !el || limitMonths > 0 || moreCount <= 0) return;
		const obs = new IntersectionObserver(
			(entries) => {
				if (entries.some((e) => e.isIntersecting)) shown += PAGE;
			},
			{ root, rootMargin: '600px 0px' }
		);
		obs.observe(el);
		return () => obs.disconnect();
	});

	/** Ключ «справжньої» зміни вигляду (режим + набір фільтрів). Оновлення даних
	 *  (revalidate) і «Показати ще» його не міняють → вхід не програється вдруге. */
	const viewKey = $derived(
		view + '|' + MARK_TYPES.map((t) => (filters[t.id] ? 1 : 0)).join('')
	);

	function monthLabel(key: string): string {
		const [y, mm] = key.split('-').map(Number);
		const name = MONTHS_UK[mm - 1] ?? key;
		return y === new Date().getFullYear() ? name : `${name} ${y}`;
	}

	// Спливне вікно оцінки — спільний HoverCard (hovercards.svelte.ts):
	// hover на десктопі, тап на сенсорних, переїзд між оцінками — плавний.
	function markKey(m: MkItem): string {
		return `mark|${m.date}|${m.subject}|${m.mark}|${m.theme ?? ''}`;
	}

	function markPayload(m: MkItem) {
		return { kind: 'mark' as const, m, cls: twCls(m.tw), label: twLabel(m.tw) };
	}

	function chipEnter(e: MouseEvent, m: MkItem): void {
		if (!canHover()) return; // на дотик mouseenter приходить разом із тапом
		hoverCard.hover(e.currentTarget as HTMLElement, markKey(m), markPayload(m));
	}

	function chipLeave(): void {
		hoverCard.unhover();
	}

	function chipClick(e: MouseEvent, m: MkItem): void {
		const a = e.currentTarget as HTMLElement;
		if (canHover()) hoverCard.show(a, markKey(m), markPayload(m));
		else hoverCard.toggle(a, markKey(m), markPayload(m));
	}
</script>

<div class="mk">
	<div class="mk-head">
		<h2>
			Оцінки{#if marks?.overall_avg}<span class="mk-avg">
					· середня <b class="accent-text">{marks.overall_avg}</b></span>
			{/if}
		</h2>
		<div class="mk-sp"></div>
		{#if !fixedView}
		<div class="mk-toggle" role="group" aria-label="Вигляд">
			<button
				use:pressable
				class:active={view === 'grid'}
				onclick={() => (view = 'grid')}
				aria-label="По місяцях"
				title="По місяцях">
				<LayoutGrid size={15} strokeWidth={2.2} />
			</button>
			<button
				use:pressable
				class:active={view === 'list'}
				onclick={() => (view = 'list')}
				aria-label="За предметами"
				title="За предметами">
				<List size={15} strokeWidth={2.2} />
			</button>
		</div>
		{/if}
	</div>

	<!-- фільтри типів робіт (порядок і дефолти — з бандла MyStat) -->
	<div class="mk-filters" role="group" aria-label="Типи робіт">
		{#each MARK_TYPES as t (t.id)}
			<button
				class="mk-fchip"
				class:off={!filters[t.id]}
				onclick={() => toggleFilter(t.id)}>
				<span class="mk-box {t.cls}" class:on={filters[t.id]}>
					{#if filters[t.id]}✓{/if}
				</span>
				{t.label}
			</button>
		{/each}
	</div>

	{#if !marks}
		<div class="mk-skel"></div>
	{:else}
		<div
			class="mk-scroll"
			class:scrollable={limitMonths === 0}
			bind:this={scroller}>
		{#key viewKey}
		<!-- анімуються групи (місяць/предмет), а не сотні чипів: ≤12 елементів -->
		<div class="mk-view"
			use:stagger={{ selector: ':scope > .mk-month, :scope > .mk-chips, :scope > .mk-srow', step: 26, max: 12, y: 8 }}>
		{#if view === 'grid'}
		{#if visibleMonths.length}
			{#each visibleMonths as mo (mo.key)}
				<h3 class="mk-month">{mo.label}</h3>
				<div class="mk-chips">
					{#each mo.items as it, i (String(it.date) + '-' + it.subject + '-' + i)}
						<button
							class="mk-chip {twCls(it.tw)}"
							onclick={(e) => chipClick(e, it)}
							onmouseenter={(e) => chipEnter(e, it)}
							onmouseleave={chipLeave}>
							{it.mark}
						</button>
					{/each}
				</div>
			{/each}
		{:else}
			<p class="mk-empty">
				{items.length ? 'Немає оцінок за вибраними типами робіт' : 'Оцінок поки немає'}
			</p>
		{/if}
	{:else}
		{#if visibleSubjects.length}
			{#each visibleSubjects as row (row.subject)}
				<div class="mk-srow">
					<div class="mk-shead">
						<b>{row.subject}</b>
						{#if row.avg != null}
							<span class="accent-text mono">{row.avg}</span>
						{/if}
					</div>
					<div class="mk-chips">
						{#each row.items as it, i (String(it.date) + '-' + i)}
							<button
								class="mk-chip {twCls(it.tw)}"
								onclick={(e) => chipClick(e, it)}
								onmouseenter={(e) => chipEnter(e, it)}
								onmouseleave={chipLeave}>
								{it.mark}
							</button>
						{/each}
					</div>
				</div>
			{/each}
		{:else}
			<p class="mk-empty">
				{items.length ? 'Немає оцінок за вибраними типами робіт' : 'Оцінок поки немає'}
			</p>
		{/if}
	{/if}
		</div>
		{/key}

		{#if moreCount > 0}
			<div class="mk-sentinel" bind:this={sentinel}>
				<button class="btn mk-all" onclick={() => (shown += PAGE)}>
					Показати ще<span class="mk-all-n">+{moreCount}</span>
				</button>
			</div>
		{/if}
		</div>
	{/if}

	{#if hiddenCount > 0}
		<button class="btn mk-all" onclick={() => onshowall?.()}>
			Усі оцінки →<span class="mk-all-n">+{hiddenCount}</span>
		</button>
	{/if}
</div>

<style>
	.mk {
		display: block;
	}

	.mk-sp {
		flex: 1;
	}

	.mk-head {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-bottom: 12px;
	}

	.mk-head h2 {
		font-size: 1.15rem;
	}

	.mk-avg {
		font-family: var(--font-body);
		font-size: 0.9rem;
		font-weight: 500;
		color: var(--text-dim);
	}

	.mk-toggle {
		display: flex;
		gap: 4px;
		padding: 3px;
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: 10px;
	}

	.mk-toggle button {
		width: 32px;
		height: 26px;
		display: grid;
		place-items: center;
		border: 0;
		border-radius: 8px;
		background: transparent;
		color: var(--text-faint);
		cursor: pointer;
		transition: all 0.15s var(--ease-spring);
	}

	.mk-toggle button.active {
		background: var(--accent);
		color: #fff;
	}

	.mk-filters {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 18px;
		margin-bottom: 16px;
	}

	.mk-fchip {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 4px 2px;
		border: 0;
		background: transparent;
		color: var(--text-dim);
		font: inherit;
		font-size: 0.84rem;
		cursor: pointer;
		transition: color 0.15s;
	}

	.mk-fchip:hover {
		color: var(--text);
	}

	.mk-fchip.off {
		opacity: 0.4;
	}

	.mk-box {
		width: 18px;
		height: 18px;
		display: grid;
		place-items: center;
		border-radius: 6px;
		border: 1px solid var(--glass-border);
		background: var(--surface-2);
		color: transparent;
		font-size: 11px;
		font-weight: 800;
		transition: all 0.15s var(--ease-spring);
	}

	.mk-box.on {
		border-color: transparent;
	}

	.mk-box.on.tw-violet {
		background: var(--accent);
		color: #fff;
	}
	.mk-box.on.tw-blue {
		background: var(--cyan);
		color: #0b0e14;
	}
	.mk-box.on.tw-yellow {
		background: var(--amber);
		color: #0b0e14;
	}
	.mk-box.on.tw-orange {
		background: #ff8a4c;
		color: #fff;
	}
	.mk-box.on.tw-rose {
		background: #f472b6;
		color: #fff;
	}
	.mk-box.on.tw-salad {
		background: #a3e635;
		color: #0b0e14;
	}
	.mk-box.on.tw-green {
		background: var(--success);
		color: #0b0e14;
	}

	.mk-month {
		margin: 14px 2px 8px;
		font-family: var(--font-body);
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--text-dim);
	}

	.mk-chips {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		/* довгі списки: поза екраном не рахуємо layout/paint;
		   padding/margin лишають місце для тіней чипів під clip */
		content-visibility: auto;
		contain-intrinsic-size: auto 92px;
		padding: 4px;
		margin: -4px;
	}

	.mk-chip {
		min-width: 46px;
		height: 38px;
		padding: 0 10px;
		border-radius: 12px;
		border: 1px solid transparent;
		font: inherit;
		font-size: 0.95rem;
		font-weight: 700;
		cursor: pointer;
		transition: transform 0.12s var(--ease-spring);
	}

	.mk-chip:hover {
		transform: translateY(-2px);
	}

	/* типи робіт — кольори оригінала; global, бо ними фарбується й спільне вікно (HoverCards) */
	:global(.tw-violet) {
		color: var(--mk-violet, #aab4ff);
		background: rgba(108, 124, 255, 0.16);
		border-color: rgba(108, 124, 255, 0.35);
	}
	:global(.tw-blue) {
		color: var(--mk-blue, #7ce4f4);
		background: rgba(34, 211, 238, 0.13);
		border-color: rgba(34, 211, 238, 0.32);
	}
	:global(.tw-yellow) {
		color: var(--mk-yellow, #ffd27a);
		background: rgba(255, 180, 84, 0.14);
		border-color: rgba(255, 180, 84, 0.32);
	}
	:global(.tw-orange) {
		color: var(--mk-orange, #ffab80);
		background: rgba(255, 138, 76, 0.14);
		border-color: rgba(255, 138, 76, 0.33);
	}
	:global(.tw-rose) {
		color: var(--mk-rose, #f9a8d4);
		background: rgba(244, 114, 182, 0.13);
		border-color: rgba(244, 114, 182, 0.32);
	}
	:global(.tw-salad) {
		color: var(--mk-salad, #c9ef85);
		background: rgba(163, 230, 53, 0.12);
		border-color: rgba(163, 230, 53, 0.3);
	}
	:global(.tw-green) {
		color: var(--mk-green, #7cebc0);
		background: rgba(52, 211, 153, 0.13);
		border-color: rgba(52, 211, 153, 0.32);
	}

	.mk-srow {
		margin-bottom: 6px;
	}

	.mk-shead {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 10px;
		margin: 12px 2px 6px;
		font-size: 0.92rem;
	}

	.mk-shead .mono {
		font-family: ui-monospace, Consolas, monospace;
		font-size: 0.85rem;
	}

	/* кнопки «Усі оцінки / Показати ще» — той самий глобальний .btn,
	що й «Усі нарахування →», на всю ширину картки */
	.mk-all {
		width: 100%;
		margin-top: 14px;
	}

	.mk-all-n {
		color: var(--text-faint);
		font-weight: 500;
	}

	.mk-sentinel {
		display: block;
	}

	/* внутрішній скрол: гортаємо бокс, а не сторінку */
	.mk-scroll.scrollable {
		overflow-y: auto;
		max-height: min(58vh, 540px);
		padding-right: 6px;
		margin-right: -6px;
		scrollbar-width: thin;
		scrollbar-color: var(--surface-2) transparent;
		overscroll-behavior: contain; /* не прокидаємо скрол на сторінку */
	}

	.mk-empty {
		padding: 26px 4px;
		color: var(--text-faint);
	}

	.mk-skel {
		height: 130px;
		border-radius: var(--radius-md);
		background:
			linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.05), transparent),
			var(--surface-2);
		background-size: 200% 100%;
		animation: mk-shimmer 1.3s infinite linear;
	}

	@keyframes mk-shimmer {
		from {
			background-position: 200% 0;
		}
		to {
			background-position: -200% 0;
		}
	}

</style>
