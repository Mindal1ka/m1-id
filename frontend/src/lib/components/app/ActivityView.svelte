<script lang="ts">
	import { AnimatedNumber, stagger } from '$lib/motion';
	import { Segmented } from '$lib/ui';
	import { Coins, Gem, Medal, ArrowDownRight, ArrowUpRight, Inbox } from '@lucide/svelte';
	import type { Dashboard, ActivityItem } from '$lib/api/client';
	import { store } from '$lib/stores/appStore.svelte';
	import { BALANCE_ICONS, feedIcon, fmtDay, activityLabel } from '$lib/app/helpers';

	interface Props {
		activeId: number | null;
		balances: Dashboard['balances']['items'];
		activity: ReturnType<typeof store.activity>;
		/** Вкладка зараз вантажиться (скелет). */
		busy: boolean;
	}
	let { activeId, balances, activity, busy }: Props = $props();

	const fmt = (n: number): string => n.toLocaleString('uk-UA');
	const fmtSigned = (n: number): string => (n > 0 ? '+' : n < 0 ? '−' : '') + fmt(Math.abs(n));

	const CUR_LABEL: Record<string, string> = {
		cristals: 'Кристали',
		coins: 'Монети',
		achivements: 'Досягнення'
	};
	const curIcon = (alias: string) => BALANCE_ICONS[alias] ?? Coins;

	/* ── фільтри (на клієнті, по вже завантажених записах) ── */
	let kind = $state('all'); // all | in | out
	let cur = $state('all'); // all | alias

	const kindItems = [
		{ value: 'all', label: 'Усі' },
		{ value: 'in', label: 'Нараховано', icon: ArrowDownRight },
		{ value: 'out', label: 'Витрачено', icon: ArrowUpRight }
	];
	const curItems = $derived([
		{ value: 'all', label: 'Усі валюти' },
		...balances.map((b) => ({ value: b.key, label: CUR_LABEL[b.key] ?? b.key, icon: curIcon(b.key) }))
	]);

	const all = $derived<ActivityItem[]>(activity?.items ?? []);

	const shown = $derived(
		all.filter((it) => {
			const aw = cur === 'all' ? it.awards : it.awards.filter((a) => a.alias === cur);
			if (!aw.length) return false;
			if (kind === 'in') return aw.some((a) => a.value > 0);
			if (kind === 'out') return aw.some((a) => a.value < 0);
			return true;
		})
	);

	/** Зміна за завантажений період: сума нарахувань і списань по валютах. */
	const delta = $derived.by(() => {
		const m: Record<string, { in: number; out: number }> = {};
		for (const it of all)
			for (const a of it.awards) {
				const d = (m[a.alias] ??= { in: 0, out: 0 });
				if (a.value > 0) d.in += a.value;
				else d.out += -a.value;
			}
		return m;
	});
	const since = $derived(all.length ? fmtDay(all[all.length - 1].date) : '');

	/** «Сьогодні / Вчора / 12 жовтня» для заголовка дня. */
	function dayLabel(iso: string): string {
		const d = iso.slice(0, 10);
		const t = new Date();
		const pad = (n: number) => String(n).padStart(2, '0');
		const ymd = (x: Date) => `${x.getFullYear()}-${pad(x.getMonth() + 1)}-${pad(x.getDate())}`;
		if (d === ymd(t)) return 'Сьогодні';
		t.setDate(t.getDate() - 1);
		if (d === ymd(t)) return 'Вчора';
		return fmtDay(d);
	}

	/** Підсумок дня по валютах (для заголовка). */
	function dayNet(date: string): { alias: string; value: number }[] {
		const m = new Map<string, number>();
		for (const it of shown) {
			if (it.date !== date) continue;
			for (const a of it.awards) {
				if (cur !== 'all' && a.alias !== cur) continue;
				m.set(a.alias, (m.get(a.alias) ?? 0) + a.value);
			}
		}
		return [...m].map(([alias, value]) => ({ alias, value })).filter((x) => x.value !== 0);
	}
</script>

<div class="tab-head">
	<h2>Нарахування</h2>
</div>

<div class="bal-grid" use:stagger={{ selector: '.bal-tile', step: 50, scale: true, y: 8 }}>
	{#each balances as b (b.key)}
		{@const BIcon = curIcon(b.key)}
		{@const d = delta[b.key]}
		<div class="glass bal-tile {b.key}">
			<div class="bal-top">
				<span class="bal-ico"><BIcon size={16} strokeWidth={2.2} /></span>
				<span class="bal-name">{CUR_LABEL[b.key] ?? b.key}</span>
			</div>
			<div class="bal-val"><AnimatedNumber value={b.value} format={fmt} /></div>
			<div class="bal-delta text-faint">
				{#if d && (d.in || d.out)}
					{#if d.in}<span class="up">+{fmt(d.in)}</span>{/if}
					{#if d.out}<span class="down">−{fmt(d.out)}</span>{/if}
					<span>з {since}</span>
				{:else}
					<span>без змін</span>
				{/if}
			</div>
		</div>
	{/each}
</div>

{#if all.length}
	<div class="filters">
		<Segmented items={kindItems} bind:value={kind} size="sm" aria-label="Тип нарахування" />
		{#if balances.length > 1}
			<Segmented items={curItems} bind:value={cur} size="sm" aria-label="Валюта" />
		{/if}
	</div>
{/if}

{#if activity && all.length}
	{#if shown.length}
		<div class="feed"
			use:stagger={{ selector: ':scope > .feed-date, :scope > .feed-item', step: 26, max: 12, y: 10 }}>
			{#each shown as it, idx (it.id)}
				{@const showDate = idx === 0 || shown[idx - 1].date !== it.date}
				{#if showDate}
					<h3 class="feed-date">
						<span>{dayLabel(it.date)}</span>
						<span class="day-net">
							{#each dayNet(it.date) as n (n.alias)}
								{@const NI = curIcon(n.alias)}
								<span class="net {n.value > 0 ? 'pos' : 'neg'}">
									{fmtSigned(n.value)}<NI size={12} strokeWidth={2.4} />
								</span>
							{/each}
						</span>
					</h3>
				{/if}
				{@const [FIcon, FCls] = feedIcon(it)}
				<div class="glass card feed-item">
					<div class="feed-icon {FCls}" class:marked={it.mark != null}>
						{#if it.mark != null}
							<span class="mark-num">{it.mark}</span>
						{:else}
							<FIcon size={17} strokeWidth={2} />
							{#if !FCls && it.icon}
								<img
									class="feed-img"
									src={it.icon}
									alt=""
									loading="lazy"
									referrerpolicy="no-referrer"
									onerror={(e) => e.currentTarget.remove()}
								/>
							{/if}
						{/if}
					</div>
					<div class="l-info">
						<b>{activityLabel(it.title)}</b>
						{#if it.subtitle}
							<span class="text-dim small">{activityLabel(it.subtitle)}</span>
						{/if}
					</div>
					<div class="feed-awards">
						{#each it.awards.filter((a) => cur === 'all' || a.alias === cur) as aw (aw.alias)}
							{@const AIcon = curIcon(aw.alias)}
							<span class="award {aw.alias} {aw.value < 0 ? 'neg' : 'pos'}">
								<span class="aw-num">{fmtSigned(aw.value)}</span>
								<AIcon size={13} strokeWidth={2.4} />
							</span>
						{/each}
					</div>
				</div>
			{/each}

			{#if activity.loading}
				<div class="feed-more">
					<span class="mini-spin"></span>
				</div>
			{:else if activity.has_more}
				<button class="btn more-btn"
					onclick={() => activeId && store.activityNext(activeId)}>
					Показати ще</button>
			{:else}
				<p class="text-faint feed-end">Це всі нарахування · {all.length}</p>
			{/if}
		</div>
	{:else}
		<div class="empty-box">
			<Inbox size={28} strokeWidth={1.6} />
			<p class="text-faint">Нічого не знайдено за цим фільтром</p>
			{#if activity.has_more && !activity.loading}
				<button class="btn" onclick={() => activeId && store.activityNext(activeId)}>
					Шукати глибше</button>
			{/if}
		</div>
	{/if}
{:else if busy}
	<div class="sk-list">
		{#each Array(6) as _, i (i)}
			<div class="skeleton sk-row"></div>
		{/each}
	</div>
{:else}
	<div class="empty-box">
		<Inbox size={28} strokeWidth={1.6} />
		<p class="text-faint">Нарахувань поки немає</p>
	</div>
{/if}

<style>
	h2 {
		font-size: 15px;
	}

	.tab-head {
		display: flex;
		align-items: center;
		margin-bottom: 14px;
	}

	/* ── зведення балансів ── */
	.bal-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
		gap: 10px;
		max-width: 720px;
		margin-bottom: 16px;
	}

	.bal-tile {
		padding: 14px 16px;
		border-radius: var(--radius-lg);
		display: flex;
		flex-direction: column;
		gap: 6px;
		min-width: 0;
		animation: none !important;
		--c: var(--accent);
	}
	.bal-tile.coins { --c: var(--amber); }
	.bal-tile.achivements { --c: var(--cyan); }

	.bal-top {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 12px;
		color: var(--text-dim);
	}

	.bal-ico {
		width: 26px;
		height: 26px;
		border-radius: 8px;
		display: grid;
		place-items: center;
		color: var(--c);
		background: color-mix(in srgb, var(--c) 15%, transparent);
	}

	.bal-val {
		font-family: var(--font-display);
		font-size: 28px;
		font-weight: 800;
		line-height: 1.1;
		letter-spacing: -0.01em;
	}

	.bal-delta {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 8px;
		font-size: 11.5px;
		font-weight: 600;
	}

	.up, .net.pos, .award.pos .aw-num { color: var(--success); }
	.down, .net.neg, .award.neg .aw-num { color: var(--danger); }

	/* ── фільтри ── */
	.filters {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin-bottom: 8px;
		max-width: 720px;
	}

	/* ── стрічка ── */
	.feed {
		display: flex;
		flex-direction: column;
		gap: 8px;
		max-width: 720px;
	}

	/* липкий заголовок дня: суцільний фон, щоб рядки не просвічували */
	.feed-date {
		position: sticky;
		top: 0;
		z-index: 2;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
		font-size: 13px;
		font-weight: 800;
		color: var(--text);
		text-transform: capitalize;
		margin: 8px 0 0;
		padding: 8px 2px 6px;
		background: color-mix(in srgb, var(--bg) 94%, transparent);
		-webkit-backdrop-filter: blur(calc(8px + 0px));
		backdrop-filter: blur(calc(8px + 0px));
	}

	.day-net {
		display: inline-flex;
		gap: 10px;
		font-size: 12px;
		font-weight: 700;
		text-transform: none;
	}

	.net {
		display: inline-flex;
		align-items: center;
		gap: 3px;
	}

	.card {
		padding: 12px 14px;
		border-radius: var(--radius-lg);
		display: flex;
		min-width: 0;
	}

	.feed-item {
		flex-direction: row;
		align-items: center;
		gap: 12px;
		/* глобальна поява .glass.card вимкнена: рядки веде use:stagger */
		animation: none !important;
		/* довга стрічка: поза екраном не рахуємо layout/paint */
		content-visibility: auto;
		contain-intrinsic-size: auto 66px;
	}

	.l-info {
		display: flex;
		flex-direction: column;
		gap: 1px;
		flex: 1;
		min-width: 0;
		font-size: 13.5px;
	}

	.l-info b,
	.l-info > span {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.small {
		font-size: 11.5px;
	}

	.feed-icon {
		width: 38px;
		height: 38px;
		border-radius: 10px;
		flex-shrink: 0;
		display: grid;
		place-items: center;
		background: var(--surface-2);
		color: var(--text-faint);
		position: relative;
		overflow: hidden;
	}

	/* іконка події з MyStat — лише для нерозпізнаних подій */
	.feed-img {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		object-fit: cover;
	}

	.feed-icon.marked {
		background: var(--accent-soft);
		color: var(--accent);
	}
	.feed-icon.ok {
		color: var(--success);
		background: color-mix(in srgb, var(--success) 13%, transparent);
	}
	.feed-icon.shop,
	.feed-icon.coin {
		color: var(--amber);
		background: color-mix(in srgb, var(--amber) 14%, transparent);
	}
	.feed-icon.ach {
		color: var(--cyan);
		background: color-mix(in srgb, var(--cyan) 13%, transparent);
	}
	.feed-icon.gem,
	.feed-icon.lesson {
		color: var(--accent);
		background: var(--accent-soft);
	}

	.mark-num {
		font-family: var(--font-display);
		font-weight: 800;
		font-size: 15px;
	}

	.feed-awards {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 3px;
		flex-shrink: 0;
	}

	/* знак задає колір числа, валюту — іконка */
	.award {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-weight: 800;
		font-size: 13.5px;
		font-variant-numeric: tabular-nums;
	}
	.award.cristals :global(svg) { color: var(--accent); }
	.award.coins :global(svg) { color: var(--amber); }
	.award.achivements :global(svg) { color: var(--cyan); }

	.feed-more {
		display: grid;
		place-items: center;
		padding: 14px;
	}

	.more-btn {
		align-self: center;
		margin: 8px auto 4px;
	}

	.feed-end {
		text-align: center;
		padding: 12px;
	}

	/* ── порожній стан і скелет ── */
	.empty-box {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 10px;
		padding: 36px 8px;
		color: var(--text-faint);
		text-align: center;
	}

	.sk-list {
		display: flex;
		flex-direction: column;
		gap: 8px;
		max-width: 720px;
	}

	.sk-row {
		height: 64px;
		border-radius: var(--radius-lg);
	}

	@media (max-width: 480px) {
		.bal-grid {
			grid-template-columns: 1fr 1fr 1fr;
			gap: 8px;
		}
		.bal-tile {
			padding: 12px;
		}
		.bal-val {
			font-size: 20px;
		}
		.bal-name {
			display: none;
		}
	}
</style>
