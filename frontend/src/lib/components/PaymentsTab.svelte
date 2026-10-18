<script lang="ts">
	import { Wallet, ExternalLink, RefreshCw, CreditCard } from '@lucide/svelte';
	import { api, type PaymentsView } from '$lib/api/client';
	import { friendlyError, isNetworkError, OFFLINE_EMPTY } from '$lib/errors';
	// F8: URL з API не кладемо в href напряму — javascript:/data: проходили
	// як є; safeUrl() повертає '#' для небезпечних схем.
	import { safeUrl } from '$lib/sanitize';
	import { AnimatedNumber, blurFade, springIn, stagger } from '$lib/motion';

	let {
		account_id,
		/** Тик «Оновити» з +page: змінився → перечитуємо з force=true. */
		refreshTick = 0
	}: {
		account_id: number;
		refreshTick?: number;
	} = $props();

	let data = $state<PaymentsView | null>(null);
	let err = $state('');
	let busy = $state(false);

	async function load(force = false): Promise<void> {
		busy = true;
		err = '';
		try {
			data = await api.payments(account_id, force);
		} catch (e) {
			err = isNetworkError(e) ? OFFLINE_EMPTY : friendlyError(e);
		} finally {
			busy = false;
		}
	}

	void load();

	// «Оновити» в топбарі: тик змінився → форс-перечитування (мимо кеша).
	$effect(() => {
		if (refreshTick > 0) void load(true);
	});

	const money = new Intl.NumberFormat('uk-UA', {
		style: 'currency',
		currency: 'UAH',
		maximumFractionDigits: 0
	});

	function fmtDate(d: string | null): string {
		if (!d) return '—';
		const dt = new Date(d);
		return Number.isNaN(dt.getTime())
			? d
			: dt.toLocaleDateString('uk-UA', { day: 'numeric', month: 'long', year: 'numeric' });
	}
</script>

{#if err}
	<p class="empty">{err}</p>
{:else if !data}
	<p class="empty">Завантажую…</p>
{:else}
	<div class="pay-top" in:blurFade={{ duration: 320, amount: 6 }}>
		<div class="pay-status glass-tile" class:bad={data.debtor_status > 0}
			in:springIn={{ duration: 480, start: 0.94, y: 10 }}>
			<div class="ps-ico"><CreditCard size={20} strokeWidth={2} /></div>
			<div>
				<div class="ps-label">
					{data.debtor_status > 0 ? 'Є заборгованість' : 'Заборгованості немає'}
				</div>
				<div class="ps-value">
					{#if data.debt_amount > 0}
						<AnimatedNumber value={data.debt_amount} format={(n) => money.format(n)} />
					{:else}
						Все сплачено
					{/if}
				</div>
				{#if data.next_date}
					<div class="ps-hint">Наступна дата оплати: {fmtDate(data.next_date)}</div>
				{/if}
			</div>
		</div>

		<div class="pay-side">
			{#if data.student_cost}
				<div class="pay-row"><span>Вартість навчання</span><b><AnimatedNumber value={data.student_cost} format={(n) => money.format(n)} /></b></div>
			{/if}
			{#if data.one_c_code}
				<div class="pay-row"><span>Код платника (1С)</span><b class="mono">{data.one_c_code}</b></div>
			{/if}
			{#if data.online_link}
				<a class="btn f" href={safeUrl(data.online_link)} target="_blank" rel="noopener noreferrer">
					<Wallet size={14} strokeWidth={2} /> Оплатити онлайн</a>
			{/if}
			{#if data.instruction_link}
				<a class="btn link" href={safeUrl(data.instruction_link)} target="_blank" rel="noopener noreferrer">
					<ExternalLink size={13} strokeWidth={2} /> Інструкція щодо оплати</a>
			{/if}
		</div>
	</div>

	<div class="pay-head">
		<h2>Історія платежів</h2>
		<button class="btn icon" onclick={() => load(true)} disabled={busy} title="Оновити">
			<RefreshCw size={15} strokeWidth={2} class={busy ? 'spin' : ''} />
		</button>
	</div>

	{#if data.history.length === 0}
		<p class="empty">Платежів поки немає</p>
	{:else}
		<ul class="rows-list" use:stagger={{ step: 35, max: 12 }}>
			{#each data.history as h, i (h.date + '-' + i)}
				<li>
					<div class="l-info">
						<b>{fmtDate(h.date)}</b>
						<span class="text-dim small">{h.description}</span>
					</div>
					<span class="pay-amount">{money.format(h.amount ?? 0)}</span>
				</li>
			{/each}
		</ul>
	{/if}
{/if}

<style>
	.pay-top {
		display: flex;
		gap: 12px;
		flex-wrap: wrap;
		margin-bottom: 16px;
	}

	.pay-status {
		flex: 1 1 260px;
		display: flex;
		gap: 12px;
		align-items: center;
		padding: 14px 16px;
		border-radius: var(--radius-md);
		background: var(--glass-bg-hover);
		border: 1px solid var(--glass-border);
	}

	.pay-status.bad {
		border-color: color-mix(in srgb, var(--danger) 45%, transparent);
	}

	.ps-ico {
		width: 42px;
		height: 42px;
		border-radius: 12px;
		display: grid;
		place-items: center;
		background: var(--accent-soft);
		color: var(--accent);
		flex-shrink: 0;
	}

	.pay-status.bad .ps-ico {
		background: color-mix(in srgb, var(--danger) 13%, transparent);
		color: var(--danger);
	}

	.ps-label {
		font-size: 12px;
		color: var(--text-dim);
		font-weight: 600;
	}

	.ps-value {
		font-size: 20px;
		font-weight: 800;
		color: var(--text);
	}

	.pay-status.bad .ps-value {
		color: var(--danger);
	}

	.ps-hint {
		font-size: 12px;
		color: var(--text-faint);
	}

	.pay-side {
		display: flex;
		flex-direction: column;
		gap: 8px;
		justify-content: center;
		min-width: 220px;
	}

	.pay-row {
		display: flex;
		justify-content: space-between;
		gap: 14px;
		font-size: 13px;
		color: var(--text-dim);
	}

	.pay-row b {
		color: var(--text);
	}

	.pay-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		margin-bottom: 8px;
	}

	/* довга історія: рядки поза екраном не рендеряться */
	.rows-list li {
		content-visibility: auto;
		contain-intrinsic-size: auto 56px;
	}

	.pay-amount {
		font-weight: 800;
		color: var(--success);
		white-space: nowrap;
	}
</style>
