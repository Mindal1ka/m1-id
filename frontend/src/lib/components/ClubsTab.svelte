<script lang="ts">
	import { Dumbbell, MapPin, RefreshCw, Search, Users } from '@lucide/svelte';
	import { api, type ClubsView } from '$lib/api/client';
	import { friendlyError, isNetworkError, OFFLINE_EMPTY } from '$lib/errors';
	import { fx } from '$lib/fx.svelte';
	import { tick } from 'svelte';
	import type { Action } from 'svelte/action';
	import { flip } from 'svelte/animate';
	import { AnimatedNumber, blurFade, pop, pressable, spotlight, springIn, stagger } from '$lib/motion';

	let { account_id, refreshTick = 0, dataTick = 0 }: {
		account_id: number;
		/** Тик авто/ручного оновлення з +page: змінився → перечитуємо. */
		refreshTick?: number;
		/** Тик фонового оновлення (5 хв): тихо перечитуємо за TTL бекенда. */
		dataTick?: number;
	} = $props();

	let data = $state<ClubsView | null>(null);
	let err = $state('');
	let busy = $state(false);
	let q = $state('');
	/** Відкладений запит (~150мс): фільтр не біжить на кожну літеру. */
	let qd = $state('');
	$effect(() => {
		const v = q;
		const t = setTimeout(() => (qd = v), 150);
		return () => clearTimeout(t);
	});

	/** Прожектор лише на коротких сітках (до ~20 карток). */
	const spotShort: Action<HTMLElement> = (node) =>
		clubs.length <= 20 ? spotlight(node) : undefined;

	/** Плавна поява картинки після завантаження (лише opacity). */
	const fadeImg: Action<HTMLImageElement> = (node) => {
		if (node.complete) return;
		node.style.opacity = '0';
		const done = () => {
			node.style.transition = 'opacity .3s ease';
			node.style.opacity = '';
		};
		node.addEventListener('load', done, { once: true });
		node.addEventListener('error', done, { once: true });
	};
	let openId = $state<number | null>(null);
	let buyingId = $state<number | null>(null);
	let okMsg = $state('');

	async function load(force = false): Promise<void> {
		busy = true;
		err = '';
		try {
			data = await api.clubs(account_id, force);
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
	// Фонове оновлення за TTL бекенда (тик +page кожні 5 хв): без скелета,
	// бекенд сам вирішує, чи ходити в mapi. Помилка — мовчки, лишаються старі дані.
	$effect(() => {
		if (dataTick > 0) {
			void api.clubs(account_id, false).then((v) => (data = v)).catch(() => {});
		}
	});

	/** Придбати абонемент клуба (money-операція!). */
	async function buy(clubId: number, abonementId: number): Promise<void> {
		if (buyingId !== null) return;
		buyingId = clubId;
		okMsg = '';
		err = '';
		try {
			const res = await api.clubBuy(account_id, clubId, abonementId);
			if (res.status === 200 || res.status === 201) {
				okMsg = 'Абонемент придбано ✅';
				fx.celebrate('order');
				await load(true);
				await tick();
				const card = document.querySelector<HTMLElement>(`.cl-grid [data-cid="${clubId}"]`);
				if (card) pop(card, 1.03);
			} else {
				const d = res.data as { error?: { message?: string } } | null;
				err = d?.error?.message ?? 'Не вдалося придбати абонемент';
			}
		} catch (e) {
			err = friendlyError(e);
		} finally {
			buyingId = null;
		}
	}

	const money = new Intl.NumberFormat('uk-UA', {
		style: 'currency',
		currency: 'UAH',
		maximumFractionDigits: 0
	});

	const clubs = $derived.by(() => {
		const arr = data?.clubs ?? [];
		const needle = qd.trim().toLowerCase();
		return needle
			? arr.filter((c) => (c.name ?? '').toLowerCase().includes(needle))
			: arr;
	});
</script>

<div class="cl-top">
	<h2>Клуби філії</h2>
	<div class="flex-sp"></div>
	{#if data}
		<span class="cl-bal">Баланс: <b><AnimatedNumber value={data.balance} format={(n) => money.format(n)} /></b></span>
	{/if}
	<label class="cl-search">
		<Search size={14} strokeWidth={2} />
		<input placeholder="Пошук клубу…" bind:value={q} />
	</label>
	<button class="btn icon" onclick={() => load(true)} disabled={busy} title="Оновити">
		<RefreshCw size={15} strokeWidth={2} class={busy ? 'spin' : ''} />
	</button>
</div>

{#if err}
	<p class="empty">{err}</p>
{:else if !data}
	<p class="empty">Завантажую…</p>
{:else if clubs.length === 0}
	<p class="empty">Нічого не знайдено</p>
{:else}
	<div class="cl-grid" use:stagger={{ step: 45, max: 12, scale: true }}>
		{#each clubs as c (c.id)}
			<article class="cl-card" data-cid={c.id} use:spotShort
				animate:flip={{ duration: 360 }}
				in:springIn={{ duration: 320, start: 0.95, y: 10 }}>
				{#if c.image}
					<img class="cl-img" src={c.image} alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" use:fadeImg />
				{/if}
				<div class="cl-body">
					<div class="cl-title">
						<h3>{c.name}</h3>
						{#if c.debt > 0}
							<span class="cl-debt">борг {money.format(c.debt)}</span>
						{/if}
					</div>
					<div class="cl-meta">
						<span class="cl-cost">{c.cost != null ? money.format(c.cost) : '—'}</span>
						{#if c.address}
							<span class="cl-addr"><MapPin size={12} strokeWidth={2} /> {c.address}</span>
						{/if}
					</div>
					{#if c.schedules.length}
						<div class="cl-sched">
							{c.schedules.map((x) => `${x.day} ${x.from}–${x.to}`).join(' · ')}
						</div>
					{/if}
					{#if c.teachers.length}
						<div class="cl-teach"><Users size={12} strokeWidth={2} /> {c.teachers.join(', ')}</div>
					{/if}
					{#if c.description}
						{#if openId === c.id}
							<p class="cl-desc open" in:blurFade={{ duration: 280, amount: 4 }}>{c.description}</p>
							<button class="btn link cl-toggle" onclick={() => (openId = null)}>Згорнути</button>
						{:else}
							<p class="cl-desc">{c.description}</p>
							<button class="btn link cl-toggle" onclick={() => (openId = c.id)}>Докладніше</button>
						{/if}
					{/if}
					{#if c.abonements.length}
						<div class="cl-buy">
							<button class="btn f" use:pressable disabled={buyingId === c.id}
								onclick={() => buy(c.id, (c.abonements[0] as { id: number }).id)}>
								{buyingId === c.id ? 'Купую…' : 'Придбати абонемент'}
							</button>
						</div>
					{/if}
				</div>
			</article>
		{/each}
	</div>
{/if}

<style>
	.cl-top {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-bottom: 12px;
	}

	.cl-bal {
		font-size: 13px;
		color: var(--text-dim);
	}

	.cl-bal b {
		color: var(--text);
	}

	.cl-search {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 6px 10px;
		border-radius: 10px;
		border: 1px solid var(--glass-border);
		background: var(--glass-bg);
		color: var(--text-faint);
	}

	.cl-search input {
		border: none;
		background: none;
		color: var(--text);
		font-size: 13px;
		width: 150px;
		outline: none;
	}

	.cl-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
		gap: 10px;
	}

	.cl-card {
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-md);
		overflow: hidden;
		background: var(--glass-bg);
		display: flex;
		flex-direction: column;
		content-visibility: auto;
		contain-intrinsic-size: auto 300px;
	}

	.cl-img {
		width: 100%;
		height: 120px;
		aspect-ratio: 13 / 6;
		object-fit: cover;
		display: block;
		background: var(--glass-bg-hover);
	}

	.cl-body {
		padding: 12px 14px;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.cl-title {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 10px;
	}

	.cl-title h3 {
		margin: 0;
		font-size: 14.5px;
		color: var(--text);
	}

	.cl-debt {
		flex-shrink: 0;
		font-size: 11px;
		font-weight: 700;
		color: var(--danger);
		background: color-mix(in srgb, var(--danger) 12%, transparent);
		border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent);
		padding: 2px 8px;
		border-radius: 999px;
	}

	.cl-meta {
		display: flex;
		align-items: center;
		gap: 10px;
		flex-wrap: wrap;
	}

	.cl-cost {
		font-weight: 800;
		color: var(--accent);
	}

	.cl-addr {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-size: 12px;
		color: var(--text-dim);
	}

	.cl-sched {
		font-size: 12.5px;
		color: var(--text-dim);
	}

	.cl-teach {
		display: flex;
		align-items: center;
		gap: 5px;
		font-size: 12px;
		color: var(--text-faint);
	}

	.cl-desc {
		margin: 2px 0 0;
		font-size: 12.5px;
		color: var(--text-dim);
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	.cl-desc.open {
		display: block;
		-webkit-line-clamp: unset;
		line-clamp: unset;
	}

	/* «Докладніше» — завжди приліплена до низу картки */
	.cl-toggle {
		margin-top: auto;
		align-self: flex-start;
	}

	.cl-buy {
		display: flex;
		justify-content: flex-end;
	}
</style>
