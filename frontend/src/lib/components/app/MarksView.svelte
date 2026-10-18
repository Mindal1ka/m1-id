<script lang="ts">
	import { fade } from 'svelte/transition';
	import { AnimatedNumber, stagger, pressable } from '$lib/motion';
	import { Dialog, Segmented, GradeBadge, EmptyState } from '$lib/ui';
	import type { MarkItem, MarksView as MarksData, MarksSubject } from '$lib/api/client';
	import MarksChipsCard from '$lib/components/MarksChipsCard.svelte';
	import { cleanTeacher } from '$lib/app/helpers';

	let { marksData }: { marksData: MarksData | null } = $props();

	// Типи робіт за бандлом MyStat (type_work): 5 класна · 3 домашня ·
	// 6 контрольна · 7 тематична. Решта (null, тестування, екзамен…) — «Інше».
	type Kind = 'class' | 'home' | 'control' | 'theme' | 'other';
	const KINDS: { key: Kind; label: string; short: string }[] = [
		{ key: 'class', label: 'Класна', short: 'Класна робота' },
		{ key: 'home', label: 'Домашня', short: 'Домашня робота' },
		{ key: 'control', label: 'Контрольна', short: 'Контрольна робота' },
		{ key: 'theme', label: 'Тематична', short: 'Тематична робота' },
		{ key: 'other', label: 'Інше', short: 'Інше' }
	];

	function kindOf(tw: string | number | null | undefined): Kind {
		switch (Number(tw)) {
			case 5: return 'class';
			case 3: return 'home';
			case 6: return 'control';
			case 7: return 'theme';
			default: return 'other';
		}
	}

	// старий кеш міг не мати items — працюємо лише з перевіреними масивами
	const items = $derived<MarkItem[]>(Array.isArray(marksData?.items) ? marksData!.items : []);
	const subjects = $derived<MarksSubject[]>(
		Array.isArray(marksData?.subjects) ? marksData!.subjects : []
	);

	const bySubject = $derived.by(() => {
		const map = new Map<string, MarkItem[]>();
		for (const m of items) {
			const arr = map.get(m.subject) ?? [];
			arr.push(m);
			map.set(m.subject, arr);
		}
		return map;
	});

	const avgOf = (arr: MarkItem[]): number =>
		arr.length ? arr.reduce((n, m) => n + Number(m.mark), 0) / arr.length : 0;

	function fmtDate(d: string): string {
		const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(d ?? ''));
		return m ? `${m[3]}.${m[2]}.${m[1]}` : '';
	}

	// ── діалог предмета ──
	let open = $state(false);
	let current = $state<MarksSubject | null>(null);
	let tab = $state<string>('all');

	function openSubject(s: MarksSubject): void {
		current = s;
		tab = 'all';
		open = true;
	}

	const subjItems = $derived(current ? (bySubject.get(current.subject) ?? []) : []);

	const kindStats = $derived(
		KINDS.map((k) => {
			const arr = subjItems.filter((m) => kindOf(m.type_work) === k.key);
			return { ...k, count: arr.length, avg: avgOf(arr) };
		}).filter((k) => k.count > 0)
	);

	const tabItems = $derived([
		{ value: 'all', label: 'Усі', badge: subjItems.length },
		...kindStats.map((k) => ({ value: k.key as string, label: k.label, badge: k.count }))
	]);

	const shown = $derived(
		tab === 'all' ? subjItems : subjItems.filter((m) => kindOf(m.type_work) === tab)
	);
	const shownAvg = $derived(avgOf(shown));
	const kindLabel = (m: MarkItem): string =>
		KINDS.find((k) => k.key === kindOf(m.type_work))?.short ?? '';
</script>

<div class="grid" in:fade={{ duration: 150 }}>
	<article class="glass card span-12">
		<MarksChipsCard marks={marksData} />
	</article>

	{#if subjects.length}
		<article class="glass card span-12">
			<h2>Предмети <span class="hint">натисни, щоб побачити деталі</span></h2>
			<div class="subj-grid" use:stagger={{ step: 28, max: 12, y: 10, scale: true }}>
				{#each subjects as s, i (s.subject)}
					<button type="button" class="mini" use:pressable onclick={() => openSubject(s)}
						aria-label={`${s.subject}: середній бал ${s.avg}`}>
						<b class="accent-text">{s.avg}</b>
						<span class="name">{s.subject}</span>
						<div class="bar">
							<div class="bar-fill" style:--i={i}
								style={`width:${Math.min(100, (s.count / (subjects[0].count || 1)) * 100)}%`}></div>
						</div>
						<span class="text-faint small">{s.count} оцінок · сер. {s.avg}</span>
					</button>
				{/each}
			</div>
		</article>
	{/if}
</div>

<Dialog bind:open title={current?.subject ?? ''} description="Середній бал і оцінки за типами робіт" size="md">
	{#if current}
		<div class="sd">
			<div class="sd-hero">
				<div class="sd-big">
					<span class="sd-label">{tab === 'all' ? 'Середній бал' : 'Середній за тип'}</span>
					<AnimatedNumber class="sd-num accent-text" value={tab === 'all' ? current.avg : shownAvg} decimals={1} duration={600} />
				</div>
				<div class="sd-meta">
					<span>Оцінок <b>{current.count}</b></span>
					<span>Найкраща <b>{current.best}</b></span>
					<span>Найнижча <b>{current.worst}</b></span>
				</div>
			</div>

			{#if kindStats.length}
				<div class="kinds" use:stagger={{ step: 30, max: 8, y: 8 }}>
					{#each kindStats as k (k.key)}
						<button type="button" class="kind" class:on={tab === k.key} use:pressable
							onclick={() => (tab = tab === k.key ? 'all' : k.key)}>
							<span class="k-name">{k.short}</span>
							<span class="k-avg">{k.avg.toFixed(1)}</span>
							<span class="k-cnt">{k.count} оцінок</span>
						</button>
					{/each}
				</div>
			{/if}

			<div class="tabs-scroll">
				<Segmented items={tabItems} bind:value={tab} size="sm" aria-label="Тип роботи" />
			</div>

			{#key `${current.subject}|${tab}`}
				{#if shown.length}
					<ul class="rows" use:stagger={{ step: 22, max: 14, y: 8 }}>
						{#each shown as m, i (m.date + i)}
							<li class="row">
								<GradeBadge value={m.mark} size="md" />
								<div class="r-body">
									<span class="r-theme">{m.theme || kindLabel(m)}</span>
									<span class="r-sub">{kindLabel(m)}{m.teacher ? ` · ${cleanTeacher(m.teacher)}` : ''}</span>
								</div>
								<time class="r-date">{fmtDate(m.date)}</time>
							</li>
						{/each}
					</ul>
				{:else}
					<EmptyState title="Немає оцінок" description="За цим типом роботи оцінок поки немає." />
				{/if}
			{/key}
		</div>
	{/if}
</Dialog>

<style>

	/* ================= сітка дашборду ================= */

	.grid {
		display: grid;
		grid-template-columns: repeat(12, 1fr);
		/* dense: пізніші менші бокси затягуються в дірки вище —
		 * «швидка стиковка» без ручного вирівнювання */
		grid-auto-flow: row dense;
		gap: 14px;
		align-content: start;
	}

	.card {
		padding: 18px;
		border-radius: var(--radius-lg);
		display: flex;
		flex-direction: column;
		gap: 12px;
		min-width: 0;
	}

	.span-12 { grid-column: span 12; }

	h2 {
		font-size: 15px;
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}

	.small {
		font-size: 11.5px;
	}

	.hint {
		font-size: 11.5px;
		font-weight: 400;
		color: var(--color-text-subtle, var(--text-faint));
	}

	.mini {
		background: var(--surface);
		border-radius: var(--radius-sm);
		padding: 12px;
		display: flex;
		flex-direction: column;
		gap: 3px;
		font-size: 13px;
		min-width: 0;
	}

	button.mini {
		all: unset;
		box-sizing: border-box;
		background: var(--surface);
		border-radius: var(--radius-sm);
		padding: 12px;
		display: flex;
		flex-direction: column;
		gap: 3px;
		font-size: 13px;
		min-width: 0;
		cursor: pointer;
		transition: background 160ms ease;
	}
	button.mini:hover { background: var(--surface-2); }
	button.mini:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
	.mini .name { overflow-wrap: anywhere; }

	.mini b {
		font-family: var(--font-display);
		font-size: 21px;
	}

	.bar {
		height: 6px;
		border-radius: 999px;
		background: var(--surface-2);
		overflow: hidden;
		margin-top: 4px;
	}

	/* ширина — статична; заповнення анімуємо через scaleX (пружина) */
	.bar-fill {
		height: 100%;
		background: var(--accent);
		border-radius: inherit;
		transform-origin: left center;
		animation: bar-grow 480ms var(--ease-out) backwards;
		animation-delay: calc(80ms + min(var(--i, 0), 8) * 24ms);
	}
	@keyframes bar-grow {
		from { transform: scaleX(0); }
	}
	:global(html[data-anim='off']) .bar-fill { animation: none; }
	@media (prefers-reduced-motion: reduce) {
		.bar-fill { animation: none; }
	}

	/* сітка плиток: 1 колонка на телефоні → 3-4 на широкому ПК */

	.subj-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
		gap: 10px;
	}

	/* ── діалог предмета ── */
	.sd { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
	.sd-hero {
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		gap: 12px 20px;
		flex-wrap: wrap;
		padding: 14px 16px;
		border-radius: var(--radius-md, 14px);
		background: var(--surface);
	}
	.sd-big { display: flex; flex-direction: column; gap: 2px; }
	.sd-label { font-size: 12px; color: var(--color-text-subtle, var(--text-faint)); }
	.sd-big :global(.sd-num) {
		font-family: var(--font-display);
		font-size: 44px;
		line-height: 1;
		font-weight: 700;
	}
	.sd-meta { display: flex; gap: 14px; font-size: 12px; flex-wrap: wrap; }
	.sd-meta span { display: flex; flex-direction: column; gap: 1px; color: var(--color-text-subtle, var(--text-faint)); }
	.sd-meta b { font-size: 16px; color: var(--color-text, inherit); font-family: var(--font-display); }

	.kinds {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
		gap: 8px;
	}
	.kind {
		all: unset;
		box-sizing: border-box;
		cursor: pointer;
		display: flex;
		flex-direction: column;
		gap: 1px;
		padding: 10px 12px;
		border-radius: var(--radius-sm);
		background: var(--surface);
		border: 1px solid transparent;
		min-width: 0;
		transition: background 160ms ease, border-color 160ms ease;
	}
	.kind:hover { background: var(--surface-2); }
	.kind.on { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 10%, var(--surface)); }
	.kind:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
	.k-name { font-size: 11.5px; color: var(--color-text-subtle, var(--text-faint)); }
	.k-avg { font-family: var(--font-display); font-size: 20px; font-weight: 600; font-variant-numeric: tabular-nums; }
	.k-cnt { font-size: 11px; color: var(--color-text-subtle, var(--text-faint)); }

	.tabs-scroll { overflow-x: auto; max-width: 100%; scrollbar-width: none; }
	.tabs-scroll::-webkit-scrollbar { display: none; }

	.rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
	.row {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 8px 10px;
		border-radius: var(--radius-sm);
		background: var(--surface);
		min-width: 0;
	}
	.r-body { display: flex; flex-direction: column; min-width: 0; flex: 1; }
	.r-theme { font-size: 13px; overflow-wrap: anywhere; }
	.r-sub { font-size: 11.5px; color: var(--color-text-subtle, var(--text-faint)); overflow-wrap: anywhere; }
	.r-date { font-size: 11.5px; color: var(--color-text-subtle, var(--text-faint)); white-space: nowrap; font-variant-numeric: tabular-nums; }

	@media (max-width: 900px) {

		.grid {
			gap: 10px;
		}

		.card {
			padding: 14px;
			border-radius: 18px;
		}

	}

	@media (max-width: 480px) {
		.sd-big :global(.sd-num) { font-size: 38px; }
		.kinds { grid-template-columns: repeat(2, 1fr); }
	}

</style>
