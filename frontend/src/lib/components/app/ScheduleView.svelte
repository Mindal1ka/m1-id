<script lang="ts">
	import { tick, onMount } from 'svelte';
	import { cubicOut } from 'svelte/easing';
	import type { TransitionConfig } from 'svelte/transition';
	import { stagger, motionOK } from '$lib/motion';
	import { GraduationCap } from '@lucide/svelte';
	import type { ScheduleView as SchedData } from '$lib/api/client';
	import { toIsoLocal as iso, weekMonday } from '$lib/stores/appStore.svelte';
	import { MONTHS_UK } from '$lib/sections';
	import {
		WD_UK,
		fmtDate,
		mkCls,
		mondayOf,
		type SchedDay,
		type SchedLesson,
		cleanTeacher
	} from '$lib/app/helpers';

	interface Props {
		sched: SchedData | null;
		schedKind: 'week' | 'month';
		schedLoading: boolean;
		/** Вкладка зараз вантажиться (скелет). */
		busy: boolean;
		weekAnchor: Date;
		monthAnchor: Date;
		/** Обраний день мобільного режиму «один день». */
		schedSel: string;
		shiftWeek: (delta: number) => void;
		shiftMonth: (delta: number) => void;
		schedToday: () => void;
		onDatePick: (e: Event) => void;
		ontogglekind: () => void;
		jumpTo: (dateIso: string) => void;
		cellEnter: (e: MouseEvent, l: SchedLesson) => void;
		cellLeave: () => void;
	}
	let {
		sched,
		schedKind,
		schedLoading,
		busy,
		weekAnchor,
		monthAnchor,
		schedSel = $bindable(),
		shiftWeek,
		shiftMonth,
		schedToday,
		onDatePick,
		ontogglekind,
		jumpTo,
		cellEnter,
		cellLeave
	}: Props = $props();

	/* ── рух: напрям навігації періоду ── */
	const periodKey = $derived(
		schedKind === 'month' ? 'm' + iso(monthAnchor).slice(0, 7) : 'w' + weekMonday(weekAnchor)
	);
	let prevKey = '';
	// svelte-ignore non_reactive_update
	let navDir: 1 | -1 = 1;
	// до оновлення DOM: порівнюємо нову дату початку зі старою → напрям слайду
	$effect.pre(() => {
		const k = periodKey;
		if (prevKey && k !== prevKey) {
			navDir = prevKey[0] === k[0] ? (k > prevKey ? 1 : -1) : 1;
		}
		prevKey = k;
	});

	/** Швидкий слайд у напрямку навігації (лише opacity/transform, без blur на великих блоках). */
	function periodIn(
		_node: Element,
		{ dir = 1, distance = 26, duration = 300 }: { dir?: 1 | -1; distance?: number; duration?: number } = {}
	): TransitionConfig {
		if (!motionOK()) return { duration: 0 };
		return {
			duration,
			easing: cubicOut,
			css: (t, u) => `opacity:${t};transform:translateX(${u * distance * dir}px)`
		};
	}

	/** Напрям зміни дня (мобільний режим) за індексом у списку. */
	let prevSelIdx = -1;
	// svelte-ignore non_reactive_update
	let dayDir: 1 | -1 = 1;
	$effect.pre(() => {
		const idx = (sched?.days ?? []).findIndex((d) => d.date === schedSel);
		if (prevSelIdx >= 0 && idx >= 0 && idx !== prevSelIdx) dayDir = idx > prevSelIdx ? 1 : -1;
		if (idx >= 0) prevSelIdx = idx;
	});

	/* Скелет лише коли вміст цього періоду ще не показувався: фонове
	   оновлення (stale-while-revalidate) не підміняє вміст скелетом і не
	   перезапускає анімацію появи. */
	let renderedKey = $state('');
	$effect(() => {
		if (!(schedLoading || busy) && sched?.days.length) renderedKey = periodKey;
	});
	const showSkel = $derived(
		(schedLoading || busy) && !(sched?.days.length && renderedKey === periodKey)
	);

	/* ── «зараз іде пара»: живий індикатор ── */
	function hm(d: Date): string {
		return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
	}
	let nowHM = $state(hm(new Date()));
	onMount(() => {
		const t = setInterval(() => (nowHM = hm(new Date())), 30_000);
		return () => clearInterval(t);
	});
	function isLive(dateIso: string | undefined, l: SchedLesson): boolean {
		if (!dateIso || dateIso !== iso(new Date())) return false;
		return !!l.start && !!l.end && l.start <= nowHM && nowHM < l.end;
	}

	/* ── ковзний індикатор мобільних пілюль (пружина по translateX) ── */
	let pillsEl = $state<HTMLDivElement>();
	let pix = $state({ x: 0, w: 0, h: 0, ready: false });
	let pixFirst = $state(true);
	function measurePill() {
		const el = pillsEl?.querySelector<HTMLElement>('.pill.on');
		if (!el) return;
		pixFirst = !pix.ready;
		pix = { x: el.offsetLeft, w: el.offsetWidth, h: el.offsetHeight, ready: true };
	}
	$effect(() => {
		void schedSel;
		void sched;
		if (!pillsEl) return;
		tick().then(measurePill);
	});

	function schedLabel(): string {
		if (schedKind === 'month') {
			return `${MONTHS_UK[monthAnchor.getMonth()]} ${monthAnchor.getFullYear()}`;
		}
		if (sched?.range.start_day && sched?.range.end_date) {
			const f = (iso: string) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}`;
			return `${f(sched.range.start_day)} – ${f(sched.range.end_date)}`;
		}
		const m = weekMonday(weekAnchor);
		return `тиждень ${m.slice(8, 10)}.${m.slice(5, 7)}`;
	}

	/** Період порожній → пропонуємо стрибнути туди, де заняття були/будуть. */
	function studyJumpTarget(): string | null {
		const r = sched?.range;
		if (!r?.start_day) return null;
		if (r.last_visit_day && r.start_day > r.last_visit_day) {
			return r.last_visit_day; // період після кінця навчання
		}
		if (r.first_visit_day && r.start_day < r.first_visit_day) {
			return r.first_visit_day; // період до початку навчання
		}
		return null;
	}

	function weekDate(i: number): string {
		// колонки сітки = ПОНЕДІЛОК якоря + i (подвійна страховка: навіть
		// якщо десь у weekAnchor прослизне непонеділкова дата, заголовки
		// залишаться Пн…Нд, а не з'їдуть на (день_тижня − 1) днів)
		const d = mondayOf(new Date(weekAnchor));
		d.setDate(d.getDate() + i);
		return iso(d);
	}

	function schedGrid(): {
		cols: (SchedDay | null)[];
		rows: number;
		today: string;
	} {
		const today = iso(new Date());
		const cols: (SchedDay | null)[] =
			Array.from({ length: 7 }, () => null);
		let rows = 6;
		for (const d of sched?.days ?? []) {
			const g = new Date(d.date + 'T00:00:00').getDay();
			const idx = (g + 6) % 7; // Пн=0 … Нд=6
			cols[idx] = d;
			rows = Math.max(rows, d.lessons.length);
		}
		return { cols, rows, today };
	}

	function selDay(): SchedDay | null {
		const days = sched?.days ?? [];
		return days.find((d) => d.date === schedSel) ?? days[0] ?? null;
	}
</script>

					<div class="toolbar">
						<button class="btn nav" onclick={() => schedKind === 'week' ? shiftWeek(-1) : shiftMonth(-1)}>‹</button>
						<span class="period">{schedLabel()}</span>
						<button class="btn nav" onclick={() => schedKind === 'week' ? shiftWeek(1) : shiftMonth(1)}>›</button>
						<div class="flex-sp"></div>
						{#if schedKind === 'week'}
							<input
								class="datepick"
								type="date"
								value={iso(weekAnchor)}
								onchange={onDatePick}
							/>
						{:else}
							<input
								class="datepick"
								type="month"
								value={iso(monthAnchor).slice(0, 7)}
								onchange={onDatePick}
							/>
						{/if}
						<button class="btn" onclick={ontogglekind}>
							{schedKind === 'week' ? 'Місяць' : 'Тиждень'}
						</button>
						<button class="btn" onclick={schedToday}>Сьогодні</button>
					</div>

					{#if showSkel}
						<div class="skeleton sk-block"></div>
					{:else if sched?.days.length}
						{#key periodKey}
						{#if schedKind === 'month'}
							<div class="sched-days" in:periodIn={{ dir: navDir }}
								use:stagger={{ selector: ':scope > .day', step: 24, max: 8, y: 10 }}>
								{#each sched.days as day (day.date)}
									<article class="glass card day" class:today={day.date === iso(new Date())}>
										<h3>
											<span class="chip">{day.weekday ?? ''}</span>
											{fmtDate(day.date)}
										</h3>
										{#each day.lessons as l, i (l.lesson_no + '-' + i)}
											<div class="lesson" class:live={isLive(day.date, l)}
												onclick={(e) => cellEnter(e, l)}
												role="button" tabindex="0"
												onkeydown={(e) => {
													if (e.key === 'Enter' || e.key === ' ') {
														e.preventDefault();
														cellEnter(e as unknown as MouseEvent, l);
													}
												}}>
												<div class="l-info">
													<b>{#if isLive(day.date, l)}<i class="live-dot breathe" title="Зараз іде"></i>{/if}{l.subject}</b>
													<span class="text-dim small">{l.theme || cleanTeacher(l.teacher)}</span>
												</div>
												<span class="text-faint small">{l.room}</span>
												<span class="les-time"><b>{l.start}</b><i>&ndash;{l.end}</i></span>
												{#if l.mark != null}
													<span class="mk2 {mkCls(l.mark)}"
														class:ex={!!l.exam}>{l.mark}</span>
												{:else if l.not_allowed}
													<span class="nk" title="Не допущено">н/д</span>
												{/if}
											</div>
										{/each}
									</article>
								{/each}
							</div>
						{:else}
							{@const g = schedGrid()}
							<!-- ДЕСКТОП: уся тижнева сітка на 7 колонок -->
							<div class="week-grid" in:periodIn={{ dir: navDir }}>
								{#each g.cols as col, ci (ci)}
									<div class="wg-h wave" class:today={weekDate(ci) === g.today} style:--ci={ci} style:--r={0}>
										<b>{WD_UK[ci]}</b>
										<span>{fmtDate(weekDate(ci))}</span>
									</div>
								{/each}
								{#each Array(g.rows) as _, r (r)}
									{#each g.cols as col, ci (ci + '-' + r)}
										{@const l = col?.lessons[r]}
										<div class="wg-cell" class:wave={!!l} style:--ci={ci} style:--r={r + 1} class:filled={!!l}
											class:exam={!!l?.exam}
											onmouseenter={(e) => l && cellEnter(e, l)}
											onmouseleave={cellLeave}
											onclick={(e) => l && cellEnter(e, l)}>
											{#if l}
												<div class="wg-top">
													{#if isLive(col?.date, l)}<i class="live-dot breathe" title="Зараз іде"></i>{/if}
													<span class="mono">{l.start}</span>
													{#if l.exam}
														<span class="ex-tag">Екзамен</span>
													{/if}
												</div>
												{#if l.mark != null || l.was === 0 || l.not_allowed}
													<div class="wbadges">
														{#if l.not_allowed}
															<span class="nk pop-badge" style:--ci={ci} title="Не допущено">н/д</span>
														{:else if l.was === 0}
															<span class="nk pop-badge" style:--ci={ci} title="Не був">Н</span>
														{/if}
														{#if l.mark != null}
															<span class="mk pop-badge {mkCls(l.mark)}" style:--ci={ci}
																class:ex={!!l.exam}>{l.mark}</span>
														{/if}
													</div>
												{/if}
												<b class="subj">{l.subject}</b>
												<span class="meta text-faint">{l.room}{#if l.teacher}
													· {cleanTeacher(l.teacher)}{/if}</span>
											{/if}
										</div>
									{/each}
								{/each}
							</div>
						{/if}

	<!-- МОБІЛЬНИЙ: один день з перемиканням -->
						<div class="m-week" in:periodIn={{ dir: navDir }}>
							<div class="m-pills" bind:this={pillsEl} class:ix-on={pix.ready}>
								<span class="pill-ix" aria-hidden="true" class:no-anim={pixFirst}
									style="--px:{pix.x}px; --pw:{pix.w}px; --ph:{pix.h}px"></span>
								{#each sched.days as day (day.date)}
									<button class="pill" class:on={day.date === schedSel}
										onclick={() => (schedSel = day.date)}>
										<b>{day.weekday}</b>
										<span>{fmtDate(day.date)}</span>
									</button>
								{/each}
							</div>
							{#each [selDay()] as d (d?.date)}
							{#if d}
								<article class="glass card day m-day"
									in:periodIn={{ dir: dayDir, distance: 20, duration: 280 }}
									use:stagger={{ selector: ':scope > .lesson, :scope > p', step: 24, max: 8, y: 6 }}
									class:today={d.date === iso(new Date())}>
									<h3>
										<span class="chip">{d.weekday ?? ''}</span>
										{fmtDate(d.date)}
									</h3>
									{#each d.lessons as l, i (l.lesson_no + '-' + i)}
										<div class="lesson" class:exam={!!l.exam} class:live={isLive(d.date, l)}
											onclick={(e) => cellEnter(e, l)}
											role="button" tabindex="0"
											onkeydown={(e) => {
												if (e.key === 'Enter' || e.key === ' ') {
													e.preventDefault();
													cellEnter(e as unknown as MouseEvent, l);
												}
											}}>
											<div class="l-info">
												<b>{#if isLive(d.date, l)}<i class="live-dot breathe" title="Зараз іде"></i>{/if}{l.subject}</b>
												<span class="text-dim small">{l.theme || cleanTeacher(l.teacher)}</span>
											</div>
											{#if l.exam}
												<span class="ex-tag"><GraduationCap size={11} strokeWidth={2.4} /> Екзамен</span>
											{/if}
											<span class="text-faint small">{l.room}</span>
											<span class="les-time"><b>{l.start}</b><i>&ndash;{l.end}</i></span>
											{#if l.not_allowed}
												<span class="nk" title="Не допущено">н/д</span>
											{:else if l.was === 0}
												<span class="nk" title="Не був">Н</span>
											{/if}
											{#if l.mark != null}
												<span class="mark-chip pop-badge {mkCls(l.mark)}">{l.mark}</span>
											{/if}
										</div>
									{:else}
										<p class="text-faint">Немає пар 🎧</p>
									{/each}
								</article>
							{/if}
							{/each}
						</div>
						{/key}
					{:else}
						<p class="text-faint empty">Немає занять у періоді {schedLabel()} 🏖</p>
					{/if}

<style>

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

	/* плитка — ледь помітний шар: пів кроку світла між карткою
	 (glass-bg) і ховером, рамка ледве-ледве. Помітно, тільки
	 якщо придивитись — у будь-якій темі */

	.l-info {
		display: flex;
		flex-direction: column;
		gap: 1px;
		flex: 1;
		min-width: 100px;
		font-size: 13.5px;
	}

	/* довга назва не виштовхує чипи */
	.l-info b,
	.l-info > span {
		overflow: hidden;
		text-overflow: ellipsis;
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

	.mono {
		font-family: ui-monospace, Consolas, monospace;
		font-size: 11.5px;
	}

	/* ================= розклад ================= */

	.toolbar {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-bottom: 16px;
		flex-wrap: wrap;
	}

	.flex-sp {
		flex: 1;
	}

	.btn.nav {
		font-size: 18px;
		min-width: 42px;
	}

	.period {
		font-family: var(--font-display);
		font-weight: 700;
		font-size: 15px;
		min-width: 150px;
		text-align: center;
	}

	.sched-days {
		display: flex;
		flex-direction: column;
		gap: 14px;
		max-width: 980px;
	}

	.day h3 {
		font-size: 15px;
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.day.today {
		border-color: transparent;
		box-shadow:
			0 0 0 1.5px var(--accent),
			0 0 26px color-mix(in srgb, var(--accent) 22%, transparent);
	}

	/* День: чіп дня тижня — м'яка акцентна «пігулка» (як у віджеті) */
	.day h3 .chip {
		font-size: 11px;
		font-weight: 700;
		color: var(--accent);
		background: var(--accent-soft);
		border: none;
		padding: 3px 9px;
		border-radius: 999px;
	}

	.day.today h3 .chip {
		background: var(--accent);
		color: #fff;
	}

	.datepick {
		font: inherit;
		font-size: 13.5px;
		color: var(--text);
		background: var(--surface);
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-sm);
		padding: 7px 10px;
		color-scheme: dark;
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

	.day .lesson:hover {
		background: var(--glass-bg);
	}

	/* ── тижнева сітка (десктоп): усі дні на одному екрані ── */

	.week-grid {
		display: grid;
		grid-template-columns: repeat(7, minmax(0, 1fr));
		gap: 6px;
		max-width: 1500px;
	}

	.wg-h {
		padding: 6px 9px 7px;
		border-radius: var(--radius-sm);
		/* акцент замість захардкоденого індиго — слідує за темою */
		background: color-mix(in srgb, var(--accent) 10%, transparent);
		display: flex;
		flex-direction: column;
		gap: 1px;
	}

	.wg-h b {
		font-size: 13px;
	}

	.wg-h span {
		color: var(--text-dim);
		font-size: 11px;
	}

	.wg-h {
		position: relative;
	}

	.wg-h.today {
		background: var(--accent);
		color: #fff;
		box-shadow: 0 0 20px color-mix(in srgb, var(--accent) 35%, transparent);
	}

	/* м'яке світіння сьогоднішньої колонки (пульс лише opacity) */
	.wg-h.today::after {
		content: '';
		position: absolute;
		inset: 0;
		border-radius: inherit;
		pointer-events: none;
		box-shadow: 0 0 28px 4px color-mix(in srgb, var(--accent) 55%, transparent);
		opacity: 0.25;
		animation: wg-glow 3.2s ease-in-out infinite;
	}
	@keyframes wg-glow {
		0%, 100% { opacity: 0.2; }
		50% { opacity: 0.85; }
	}

	/* Поява комірок — двигун появи ($lib/motion, autoEnter): діагональна хвиля
	   за рангом «колонка + рядок». Власної CSS-хвилі тут більше немає. */

	/* оцінки/«Н» вискакують після своєї комірки */
	.pop-badge {
		animation: badge-pop 320ms var(--ease-spring) backwards;
		/* ранг двигуна появи = колонка + рядок (крок 40мс) */
		animation-delay: calc(min(var(--ci, 0) + var(--r, 0), 10) * 40ms + 260ms);
	}
	@keyframes badge-pop {
		from { opacity: 0; transform: scale(0.3); }
	}

	/* крапка «зараз іде пара» (.breathe із motion.css) */
	.live-dot {
		display: inline-block;
		width: 7px;
		height: 7px;
		border-radius: 50%;
		margin-right: 6px;
		vertical-align: middle;
		background: var(--success);
		box-shadow: 0 0 8px var(--success);
		flex-shrink: 0;
	}

	:global(html[data-anim='off']) :is(.pop-badge, .wg-h.today::after) {
		animation: none;
	}

	.wg-h.today span {
		color: rgba(255, 255, 255, 0.75);
	}

	.wg-cell {
		min-height: 56px;
		position: relative;
		border-radius: var(--radius-sm);
		border: 1px solid transparent;
		padding: 6px 8px;
		display: flex;
		flex-direction: column;
		gap: 2px;
		/* порожні клітинки прозорі — у темній темі «сірі плями» читались
		   як бруд; структуру тримає лише filled */
		background: transparent;
	}

	.wg-cell.filled {
		background: var(--surface-2);
		border-color: color-mix(in srgb, var(--accent) 16%, var(--glass-border));
	}

	/* Світла тема: замість сіро-фіолетових плашок — чисті білі картки з м'якою
	   тінню і тонкою акцентною смужкою зліва; заголовки днів — нейтральні. */
	:global(html[data-scheme='light']) .wg-cell.filled {
		background: #fff;
		border-color: color-mix(in srgb, var(--text) 8%, transparent);
		box-shadow:
			inset 3px 0 0 color-mix(in srgb, var(--accent) 55%, transparent),
			0 1px 2px rgba(15, 23, 42, 0.05),
			0 4px 14px -6px rgba(15, 23, 42, 0.12);
	}
	:global(html[data-scheme='light']) .wg-cell.filled.exam {
		box-shadow:
			inset 3px 0 0 var(--amber),
			0 1px 2px rgba(15, 23, 42, 0.05),
			0 4px 14px -6px rgba(15, 23, 42, 0.12);
		border-left-color: color-mix(in srgb, var(--text) 8%, transparent);
	}
	:global(html[data-scheme='light']) .wg-h:not(.today) {
		background: color-mix(in srgb, var(--text) 4.5%, transparent);
	}
	:global(html[data-scheme='light']) .day.glass {
		background: #fff;
	}
	:global(html[data-scheme='light']) .day .lesson:hover {
		background: color-mix(in srgb, var(--accent) 6%, transparent);
	}
	:global(html[data-scheme='light']) .pill:not(.on) {
		background: #fff;
	}
	:global(html[data-scheme='light']) .datepick {
		color-scheme: light;
	}

	.wg-top {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 6px;
	}

	.wg-top .mono {
		color: var(--text);
		font-size: 12px;
		font-weight: 800;
		white-space: nowrap;
		font-feature-settings: 'tnum';
	}

	.wg-cell .subj {
		font-size: 13px;
		font-weight: 600;
		line-height: 1.3;
		display: -webkit-box;
		-webkit-line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	.wg-cell .meta {
		font-size: 11px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	/* ── оцінки та екзамени ── */

	.mk {
		position: absolute;
		top: -6px;
		right: -5px;
		min-width: 21px;
		height: 21px;
		padding: 0 5px;
		border-radius: 11px;
		/* Фікс: цифра була не по центру кола. display:grid +
		 * place-items:center центрує РЯДКОВИЙ БОКС тексту, а не гліф:
		 * успадкований line-height (≈1.5) зсував гліф угору.
		 * flex + явний line-height:1 центрує саму цифру. */
		display: flex;
		align-items: center;
		justify-content: center;
		line-height: 1;
		font-size: 11.5px;
		font-weight: 800;
		color: #fff;
		box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
		z-index: 1;
	}

	.mk.hi {
		background: var(--success);
	}

	.mk.mid {
		background: var(--amber);
	}

	.mk.low {
		background: var(--danger);
	}

	.mk.ex {
		box-shadow: 0 0 0 2px var(--amber), 0 2px 8px rgba(0, 0, 0, 0.35);
	}

	.wg-cell.exam,
	.lesson.exam {
		border-left: 3px solid var(--amber);
	}

	.ex-tag {
		flex-shrink: 0;
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 4px 9px;
		border-radius: 999px;
		font-size: 10px;
		font-weight: 800;
		color: var(--amber);
		background: color-mix(in srgb, var(--amber) 13%, transparent);
		border: 1px solid color-mix(in srgb, var(--amber) 34%, transparent);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

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

	/* ── Поповер деталей (урок / оцінка) ── */

	.mk2 {
		min-width: 26px;
		height: 26px;
		padding: 0 6px;
		border-radius: 9px;
		display: grid;
		place-items: center;
		font-size: 0.85rem;
		font-weight: 800;
		color: #fff;
		box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
	}

	.mk2.hi {
		background: var(--success);
	}

	.mk2.mid {
		background: var(--amber);
	}

	.mk2.low {
		background: var(--danger);
	}

	.mk2.ex {
		box-shadow: 0 0 0 2px var(--amber), 0 2px 8px rgba(0, 0, 0, 0.35);
	}

	/* ── Оцінки: стрічка ── */

	.m-day .lesson {
		padding: 13px 14px;
	}

	/* ── мобільний режим: один день ── */

	.m-week {
		display: none;
	}

	.m-pills {
		display: flex;
		gap: 6px;
		overflow-x: auto;
		padding-bottom: 4px;
		margin-bottom: 10px;
		scrollbar-width: none;
	}

	.m-pills::-webkit-scrollbar {
		display: none;
	}

	.pill {
		flex-shrink: 0;
		font: inherit;
		font-size: 11.5px;
		color: var(--text-dim);
		background: var(--surface);
		border: 1px solid var(--glass-border);
		border-radius: 12px;
		padding: 5px 11px;
		text-align: center;
		line-height: 1.25;
		cursor: pointer;
	}

	.pill b {
		display: block;
		font-size: 12px;
		color: var(--text);
	}

	.pill span {
		white-space: nowrap;
	}

	.pill.on {
		background: var(--accent);
		border-color: transparent;
		color: rgba(255, 255, 255, 0.8);
	}

	/* ковзний фон активної пілюлі */
	.m-pills {
		position: relative;
	}
	.pill {
		position: relative;
		z-index: 1;
	}
	.m-pills.ix-on .pill.on {
		background: transparent;
	}
	.pill-ix {
		position: absolute;
		left: 0;
		top: 0;
		width: var(--pw);
		height: var(--ph);
		border-radius: 12px;
		background: var(--accent);
		pointer-events: none;
		z-index: 0;
		transform: translateX(var(--px));
		transition: transform 460ms var(--ease-spring);
		will-change: transform;
	}
	.pill-ix.no-anim,
	:global(html[data-anim='off']) .pill-ix {
		transition: none;
	}

	.pill.on b {
		color: #fff;
	}

	@media (max-width: 860px) {
		.week-grid {
			display: none;
		}

		.m-week {
			display: block;
		}
	}

/* «Не був» — помітний мінус-чип (стилів не було взагалі) */
	.nk {
		flex-shrink: 0;
		display: inline-flex;
		align-items: baseline;
		gap: 3px;
		white-space: nowrap;
		font-feature-settings: 'tnum';
	}

	.les-time b {
		font-size: 13.5px;
		font-weight: 800;
		color: var(--text);
	}

	.les-time i {
		font-style: normal;
		font-size: 12px;
		font-weight: 600;
		color: var(--text-faint);
	}

	/* «Не був» — помітний мінус-чип (стилів не було взагалі) */
	.nk {
		flex-shrink: 0;
		min-width: 22px;
		height: 22px;
		padding: 0 6px;
		border-radius: 8px;
		display: inline-grid;
		place-items: center;
		font-size: 12px;
		font-weight: 800;
		color: var(--danger);
		background: color-mix(in srgb, var(--danger) 13%, transparent);
		border: 1px solid color-mix(in srgb, var(--danger) 32%, transparent);
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

	/* плоский список як в оригіналі: ①②③, ⋯, моє ім'я акцентом */

	.sk-block {
		height: 300px;
		border-radius: var(--radius-lg);
	}

</style>

