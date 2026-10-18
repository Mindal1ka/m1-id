<script lang="ts">
	/** Власний календар: навігація по місяцях, мультивибір дат.
	 *  Маркування: ✅ замовлено (журнал), 🛌 вихідний, ⚠️ ризик (сьогодні після 9:00). */
	import { ChevronLeft, ChevronRight } from '@lucide/svelte';
	import { blurFade, slideX } from '$lib/motion';

	let {
		selectedDates = [],      // string[] ISO дат
		ordered = {},            // Record<iso, {total, supplier}>
		cancelled = {},          // Record<iso, {total, supplier}> — скасовані
		allow_weekends = false,
		onToggle // (iso: string) => void
	}: {
		selectedDates?: string[];
		ordered?: Record<string, { total: number; supplier: string }>;
		cancelled?: Record<string, { total: number; supplier: string }>;
		allow_weekends?: boolean;
		onToggle: (iso: string) => void;
	} = $props();

	const MONTHS = ['Січень', 'Лютий', 'Березень', 'Квітень', 'Травень',
		'Червень', 'Липень', 'Серпень', 'Вересень', 'Жовтень',
		'Листопад', 'Грудень'];
	const WD = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Нд'];

	const now = new Date();
	const todayIso = isoOf(now);

	function isoOf(d: Date): string {
		return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
	}

	// навігація місяців: один $state-об'єкт, який ПОВНІСТЮ замінюється —
	// це найнадійніший патерн для Svelte 5 runes (присвоєння нового об'єкта
	// завжди тригерить $derived, на відміну від мутацій полів Date)
	let view = $state({ y: now.getFullYear(), m: now.getMonth() });

	/** Напрям перелистування місяця (для slideX). */
	let dir = $state<1 | -1>(1);

	function prev(): void {
		dir = -1;
		view = view.m === 0
			? { y: view.y - 1, m: 11 }
			: { y: view.y, m: view.m - 1 };
	}
	function next(): void {
		dir = 1;
		view = view.m === 11
			? { y: view.y + 1, m: 0 }
			: { y: view.y, m: view.m + 1 };
	}

	const cells = $derived.by(() => {
		const { y, m } = view;
		const startWd = (new Date(y, m, 1).getDay() + 6) % 7;
		const days = new Date(y, m + 1, 0).getDate();
		const out: (string | null)[] = [];
		for (let i = 0; i < startWd; i++) out.push(null);
		for (let d = 1; d <= days; d++) {
			out.push(`${y}-${String(m + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`);
		}
		return out;
	});

	function isPast(iso: string): boolean {
		return iso < todayIso;
	}
	function isWeekend(iso: string): boolean {
		const d = new Date(iso + 'T00:00:00');
		return d.getDay() === 0 || d.getDay() === 6;
	}
	function risky(iso: string): boolean {
		// свіжа дата/година при кожному виклику (вкладка може бути
		// відкрита через 9:00); вже замовлене сьогодні — не «ризикове»
		const n = new Date();
		return iso === isoOf(n) && n.getHours() >= 9 && !ordered[iso];
	}

	function click(iso: string | null): void {
		if (!iso || isPast(iso)) return;
		if (isWeekend(iso) && !allow_weekends) return;
		onToggle(iso);
	}

	// свайп ліворуч/праворуч = наступний/попередній місяць
	let swX = 0;
	let swY0 = 0;
	let swSeen = false;
</script>

<div class="fscal">
	<div class="fscal-head">
		<button class="fscal-nav" type="button" onclick={prev} aria-label="Попередній місяць">
			<ChevronLeft size={16} />
		</button>
		{#key view.y * 12 + view.m}
			<span class="fscal-month" in:blurFade={{ duration: 260, amount: 4 }}>{MONTHS[view.m]} {view.y}</span>
		{/key}
		<button class="fscal-nav" type="button" onclick={next} aria-label="Наступний місяць">
			<ChevronRight size={16} />
		</button>
	</div>
	{#key view.y * 12 + view.m}
	<div class="fscal-grid"
		in:slideX={{ dir, distance: 22, duration: 340 }}
		onpointerdown={(e) => { swX = e.clientX; swY0 = e.clientY; swSeen = true; }}
		onpointerup={(e) => {
			if (!swSeen) return;
			swSeen = false;
			const dx = e.clientX - swX;
			if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(e.clientY - swY0))
				(dx < 0 ? next : prev)();
		}}
		onpointercancel={() => { swSeen = false; }}>
		{#each WD as w, wi (wi)}
			<span class="fscal-wd">{w}</span>
		{/each}
		{#each cells as iso, ci (ci)}
			{#if iso}
				<button
					type="button"
					class="fscal-cell"
					class:past={isPast(iso)}
					class:sel={selectedDates.includes(iso)}
					class:done={!!ordered[iso]}
					class:cancel={!!cancelled[iso]}
					class:weekend={isWeekend(iso) && !allow_weekends && !isPast(iso)}
					class:risky={risky(iso)}
					disabled={isPast(iso) || (isWeekend(iso) && !allow_weekends)}
					onclick={() => click(iso)}>
					<span class="d">{Number(iso.slice(8, 10))}</span>
					{#if cancelled[iso]}<i class="dot c"></i>{:else if ordered[iso]}<i class="dot"></i>{/if}
					{#if risky(iso)}<i class="warn">⚠</i>{/if}
				</button>
			{:else}
				<span class="fscal-cell empty"></span>
			{/if}
		{/each}
	</div>
	{/key}
	<div class="fscal-legend">
		<span><i class="dot"></i> замовлено</span>
		<span><i class="dot c"></i> скасовано</span>
		<span class="swatch"></span> вибрано
		<span>⚠ — після 9:00 (ризик)</span>
	</div>
</div>

<style>
	.fscal { user-select: none; }
	.fscal-head {
		display: flex; align-items: center; justify-content: space-between;
		margin-bottom: 6px; gap: 8px;
	}
	.fscal-month { font-weight: 700; text-align: center; flex: 1; }
	.fscal-nav {
		border: 1px solid var(--line, rgba(128,128,128,.3));
		background: transparent; border-radius: 8px;
		padding: 3px; cursor: pointer; color: inherit;
		display: inline-flex; align-items: center;
	}
	.fscal-nav:hover { background: rgba(128,128,128,.12); }
	.fscal-grid {
		display: grid;
		grid-template-columns: repeat(7, 1fr);
		gap: 3px;
	}
	.fscal-wd {
		text-align: center; font-size: 10px; opacity: .5; padding: 2px 0;
	}
	.fscal-cell {
		position: relative;
		border: none; background: transparent;
		border-radius: 9px;
		padding: 0; height: 32px;
		font: inherit; font-size: 13px; color: inherit;
		cursor: pointer;
		display: inline-flex; align-items: center; justify-content: center;
		transition: background .15s, transform .1s;
	}
	.fscal-cell:hover:not(:disabled):not(.sel) { background: rgba(128,128,128,.14); }
	.fscal-cell:active:not(:disabled) { transform: scale(.92); }
	.fscal-cell.empty { cursor: default; }
	.fscal-cell.past { opacity: .25; cursor: not-allowed; }
	.fscal-cell.weekend { opacity: .35; cursor: not-allowed; }
	.fscal-cell.done { font-weight: 700; }
	/* пружинний вибір дня */
	@keyframes cal-sel {
		0% { transform: scale(0.78); }
		55% { transform: scale(1.1); }
		100% { transform: scale(1); }
	}
	@keyframes cal-dot {
		0% { transform: translateX(-50%) scale(0); }
		60% { transform: translateX(-50%) scale(1.8); }
		100% { transform: translateX(-50%) scale(1); }
	}
	.fscal-cell.sel {
		animation: cal-sel 380ms var(--ease-spring, cubic-bezier(0.34, 1.56, 0.64, 1));
		background: var(--accent, #4f8cff);
		color: #fff;
		font-weight: 700;
		box-shadow: 0 2px 8px rgba(79, 140, 255, .4);
	}
	.fscal-cell.risky { box-shadow: inset 0 0 0 1.5px #e6a23c; }
	.dot {
		position: absolute; bottom: 3px; left: 50%; transform: translateX(-50%);
		width: 4px; height: 4px; border-radius: 50%;
		background: #34c759;
		pointer-events: none;
		animation: cal-dot 420ms var(--ease-spring, cubic-bezier(0.34, 1.56, 0.64, 1)) 120ms backwards;
	}
	.fscal-legend .dot { animation: none; }
	:global(html[data-anim='off']) .fscal-cell.sel,
	:global(html[data-anim='off']) .dot {
		animation: none;
	}
	.dot.c { background: #98989d; }
	.warn {
		position: absolute; top: 1px; right: 2px; font-size: 8px;
		font-style: normal;
		pointer-events: none;
	}
	.fscal-legend {
		display: flex; gap: 10px; flex-wrap: wrap;
		font-size: 10px; opacity: .55; margin-top: 6px; align-items: center;
	}
	.fscal-legend .dot { position: static; transform: none; display: inline-block; }
	.swatch {
		display: inline-block; width: 10px; height: 10px;
		border-radius: 3px; background: var(--accent, #4f8cff);
	}
</style>