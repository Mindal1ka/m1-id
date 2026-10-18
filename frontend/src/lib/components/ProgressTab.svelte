<script lang="ts">
	import { TrendingUp, RefreshCw, ArrowUp, ArrowDown } from '@lucide/svelte';
	import { AnimatedNumber, motionOK, ease, pressable } from '$lib/motion';
	import { api, type ProgressView } from '$lib/api/client';
	import { friendlyError, isNetworkError, OFFLINE_EMPTY } from '$lib/errors';

	let {
		account_id,
		refreshTick = 0
	}: {
		account_id: number;
		refreshTick?: number;
	} = $props();

	let data = $state<ProgressView | null>(null);
	let err = $state('');
	let busy = $state(false);

	async function load(force = false): Promise<void> {
		busy = true;
		err = '';
		try {
			data = await api.progress(account_id, force);
		} catch (e) {
			err = isNetworkError(e) ? OFFLINE_EMPTY : friendlyError(e);
		} finally {
			busy = false;
		}
	}

	void load();

	$effect(() => {
		if (refreshTick > 0) void load(true);
	});

	/** Висота стовпчика 0..1 відносно максимуму шкали (12 балів). */
	const SCALE_MAX = 12;

	function barH(v: number | null): string {
		if (v === null || v === undefined) return '0%';
		const p = Math.max(0, Math.min(1, v / SCALE_MAX));
		return `${Math.max(p * 100, v > 0 ? 4 : 0)}%`;
	}

	function fmtMonth(m: string): string {
		// '2026-05' → '05.26'
		const [y, mo] = m.split('-');
		return mo && y ? `${mo}.${y.slice(2)}` : m;
	}

	/** Різниця зі знаком (null — без змін/немає даних). */
	function diff(cur: number | null, prev: number | null): number | null {
		if (cur === null || prev === null) return null;
		const d = Math.round((cur - prev) * 100) / 100;
		return d === 0 ? null : d;
	}

	const fmtDiff = (n: number): string => `${n > 0 ? '+' : ''}${n}`;

	/** Стовпчик «виростає» з нуля (scaleY, origin bottom), коли потрапляє у в'юпорт. */
	function barGrow(node: HTMLElement, opts: { delay?: number } = {}) {
		if (!motionOK() || typeof IntersectionObserver === 'undefined') return;
		node.style.transform = 'scaleY(0)';
		node.style.transformOrigin = 'bottom center';
		const io = new IntersectionObserver((entries) => {
			if (!entries.some((e) => e.isIntersecting)) return;
			io.disconnect();
			node.style.transform = '';
			node.animate([{ transform: 'scaleY(0)' }, { transform: 'scaleY(1)' }], {
				duration: 460,
				delay: opts.delay ?? 0,
				easing: ease('spring'),
				fill: 'backwards'
			});
		});
		io.observe(node);
		return { destroy: () => io.disconnect() };
	}

	function fmtVal(v: number | null): string {
		return v === null ? '—' : String(Math.round(v * 100) / 100);
	}
</script>

{#if err && !data}
	<p class="empty">{err}</p>
{:else if !data}
	<p class="empty">Завантажую…</p>
{:else}
	<div class="pr-top">
		<div class="pr-total glass-tile">
			<div class="pt-ico"><TrendingUp size={20} strokeWidth={2} /></div>
			<div>
				<div class="pt-label">Середній бал за весь час</div>
				<div class="pt-value">
					{#if data.total_average !== null}
						<AnimatedNumber value={data.total_average} decimals={2} />
					{:else}—{/if}
					{#if data.total_average !== null && data.prev_total_average !== null}
						{@const d = diff(data.total_average, data.prev_total_average)}
						{#if d !== null}
							<span class="pt-diff" class:up={d > 0}>
								<span class="pt-arrow">{#if d > 0}<ArrowUp size={12} strokeWidth={2.8} />{:else}<ArrowDown size={12} strokeWidth={2.8} />{/if}</span>
								<AnimatedNumber value={d} decimals={2} format={fmtDiff} />
							</span>
						{/if}
					{/if}
				</div>
			</div>
		</div>
		<button class="btn icon" use:pressable onclick={() => load(true)} disabled={busy} title="Оновити">
			<span class="spinwrap" class:spin={busy}>
				<RefreshCw size={15} strokeWidth={2} />
			</span>
		</button>
	</div>

	{#if data.charts.length === 0}
		<p class="empty">Даних прогресу поки немає</p>
	{:else}
		{#each data.charts as ch, ci (ci)}
			<div class="pr-chart glass-tile">
				<div class="prc-head">
					<span class="prc-title">Динаміка середнього балу</span>
					{#if data.charts.length > 1}
						<span class="prc-type">тип {ch.chart_type ?? '—'}</span>
					{/if}
					<span class="prc-avg">сер. <b>{#if ch.average !== null}<AnimatedNumber value={ch.average} decimals={2} />{:else}—{/if}</b>
						{#if ch.average !== null && ch.prev_average !== null}
							{@const d = diff(ch.average, ch.prev_average)}
							{#if d !== null}
								<span class="pt-diff" class:up={d > 0}>
									<span class="pt-arrow">{#if d > 0}<ArrowUp size={11} strokeWidth={2.8} />{:else}<ArrowDown size={11} strokeWidth={2.8} />{/if}</span>
									<AnimatedNumber value={d} decimals={2} format={fmtDiff} />
								</span>
							{/if}
						{/if}
					</span>
				</div>
				<div class="bars" role="img"
					aria-label="Графік середнього балу по місяцях">
					{#each ch.points as p, pi (pi)}
						{@const has = p.points !== null && p.points !== undefined}
						<div class="bar-col" title="{p.month}: {fmtVal(p.points)}">
							<div class="bar-track">
								<div class="bar" style:height={barH(p.points)}
									use:barGrow={{ delay: Math.min(pi, 8) * 20 }}
									class:ghost={!has}></div>
								{#if p.prev !== null && p.prev !== undefined}
									<div class="bar prev" style:height={barH(p.prev)}
										use:barGrow={{ delay: Math.min(pi, 8) * 20 + 30 }}></div>
								{/if}
							</div>
							<span class="bar-x">{fmtMonth(p.month)}</span>
						</div>
					{/each}
				</div>
			</div>
		{/each}
	{/if}
{/if}

<style>
	.pr-top {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-bottom: 12px;
	}
	.pr-total {
		flex: 1;
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 12px 14px;
		border-radius: 14px;
	}
	.pt-ico {
		width: 38px;
		height: 38px;
		border-radius: 12px;
		display: grid;
		place-items: center;
		background: color-mix(in srgb, var(--accent, #7aa2f7) 18%, transparent);
		color: var(--accent, #7aa2f7);
	}
	.pt-label {
		font-size: 12px;
		opacity: 0.65;
	}
	.pt-value {
		font-size: 20px;
		font-weight: 700;
		line-height: 1.1;
		display: flex;
		align-items: baseline;
		gap: 7px;
	}
	.pt-diff {
		font-size: 12px;
		font-weight: 600;
		color: #ff7b72;
	}
	.pt-diff.up {
		color: #7ee787;
	}
	.pt-diff {
		display: inline-flex;
		align-items: center;
		gap: 2px;
	}
	/* стрілка вискакує пружиною після докручування числа */
	.pt-arrow {
		display: inline-flex;
		animation: pt-arrow-pop 380ms var(--ease-spring) 160ms backwards;
	}
	@keyframes pt-arrow-pop {
		from { opacity: 0; transform: translateY(6px) scale(0.3); }
	}
	:global(html[data-anim='off']) .pt-arrow {
		animation: none;
	}
	.pr-chart {
		padding: 14px;
		border-radius: 14px;
		margin-bottom: 10px;
	}
	.prc-head {
		display: flex;
		align-items: baseline;
		gap: 10px;
		margin-bottom: 10px;
	}
	.prc-title {
		font-weight: 600;
		font-size: 14px;
	}
	.prc-type {
		font-size: 11px;
		opacity: 0.5;
	}
	.prc-avg {
		margin-left: auto;
		font-size: 12px;
		opacity: 0.75;
	}
	.bars {
		display: flex;
		align-items: flex-end;
		gap: 6px;
		overflow-x: auto;
		padding-bottom: 2px;
	}
	.bar-col {
		flex: 1 0 34px;
		min-width: 34px;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 4px;
	}
	.bar-track {
		position: relative;
		width: 100%;
		height: 110px;
		display: flex;
		align-items: flex-end;
		justify-content: center;
		gap: 2px;
	}
	.bar {
		width: 46%;
		max-width: 20px;
		border-radius: 5px 5px 2px 2px;
		background: linear-gradient(
			180deg,
			var(--accent, #7aa2f7),
			color-mix(in srgb, var(--accent, #7aa2f7) 55%, transparent)
		);
	}
	.bar.prev {
		width: 22%;
		max-width: 10px;
		opacity: 0.35;
		background: var(--text-dim, #9aa4b2);
	}
	.bar.ghost {
		background: rgba(128, 128, 128, 0.18);
		height: 3px !important;
	}
	.bar-x {
		font-size: 10px;
		opacity: 0.55;
		white-space: nowrap;
	}
	.btn {
		cursor: pointer;
	}
	.btn:disabled {
		opacity: 0.5;
	}
	.spinwrap {
		display: inline-flex;
	}
	.spin {
		animation: spin 0.9s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
</style>
