<script lang="ts">
	import { Coins, Gem, Package, ShoppingBag, Search, X } from '@lucide/svelte';
	import {
		api,
		ApiError,
		type ShopPrice,
		type ShopProduct,
		type ShopView
	} from '$lib/api/client';
	import { store } from '$lib/stores/appStore.svelte';
	import AppModal from '$lib/components/AppModal.svelte';
	import { friendlyError, isNetworkError, OFFLINE_EMPTY } from '$lib/errors';
import { fx } from '$lib/fx.svelte';
	import { tick } from 'svelte';
	import type { Action } from 'svelte/action';
	import {
		AnimatedNumber,
		pop,
		pressable,
		slideX,
		spotlight,
		springIn,
		stagger
	} from '$lib/motion';
	import { SmartImage } from '$lib/ui';

	let {
		account_id,
		/** Тик «Оновити» з +page: змінився → перечитуємо з force=true. */
		refreshTick = 0,
		/** Тихий сигнал «слоти стора оновились у фоні»: перечитуємо з кешу
		 *  без мережі, без скелета й без скидання відкритих діалогів. */
		dataTick = 0
	}: {
		account_id: number;
		refreshTick?: number;
		dataTick?: number;
	} = $props();

	/** Прожектор лише на коротких сітках (на довгих — зайві слухачі). */
	const spotSmall: Action<HTMLElement> = (node) =>
		products.length <= 20 ? spotlight(node) : undefined;

	let data = $state<ShopView | null>(null);
	let sub = $state<'catalog' | 'orders'>('catalog');
	let q = $state('');
	/** Відкладений запит: фільтр великого каталогу не біжить на кожну літеру. */
	let qd = $state('');
	$effect(() => {
		const v = q;
		const t = setTimeout(() => (qd = v), 150);
		return () => clearTimeout(t);
	});
	let busyId = $state<number | null>(null);
	let confirmBuy = $state<ShopProduct | null>(null);
	let confirmDiscard = $state<string | null>(null); // order uuid
	/** Відкрита модалка товару (повний опис + велика картинка). */
	let detailP = $state<ShopProduct | null>(null);
	let err = $state('');
	let okMsg = $state('');
	/** Напрям перемикання підрозділів (для slideX). */
	let subDir = $state<1 | -1>(1);
	let balEl = $state<HTMLElement | null>(null);

	function setSub(next: 'catalog' | 'orders'): void {
		if (next === sub) return;
		subDir = next === 'orders' ? 1 : -1;
		sub = next;
	}

	// баланс для «вистачить / не вистачить»
	const bal = $derived.by(() => {
		const d = store.dash(account_id);
		const out: Record<string, number> = {};
		for (const b of d?.balances.items ?? []) out[b.key] = Number(b.value) || 0;
		return out;
	});

	/** Перший load завершено (успіх або помилка) — після цього скелет не показуємо. */
	let loaded = $state(false);

	async function load(force = false): Promise<void> {
		try {
			data = await store.shop(account_id, force);
			if (err === OFFLINE_EMPTY) err = '';
		} catch (e) {
			// офлайн: якщо дані вже є — лишаємо їх; без даних — спокійний порожній стан
			if (isNetworkError(e)) {
				if (!data) err = OFFLINE_EMPTY;
			} else {
				err = friendlyError(e);
			}
		} finally {
			loaded = true;
		}
	}

	void load();

	// «Оновити» в топбарі: тик змінився → форс-перечитування (мимо кеша).
	$effect(() => {
		if (refreshTick > 0) void load(true);
	});

	// Фонове оновлення: просто беремо свіжий слот стора (без мережі/скелета).
	$effect(() => {
		if (dataTick > 0) {
			const cached = store.shopCache(account_id);
			if (cached) data = cached;
		}
	});
	const products = $derived.by(() => {
		const arr = Array.isArray(data?.products) ? data!.products : [];
		const needle = qd.trim().toLowerCase();
		return needle
			? arr.filter(
					(p) =>
						p.title.toLowerCase().includes(needle) ||
						p.text.toLowerCase().includes(needle)
				)
			: arr;
	});

	const orders = $derived(
		Array.isArray(data?.orders) ? data!.orders : []
	);

	function priceNum(p: string | null): number {
		const v = Number(p);
		return Number.isFinite(v) ? v : 0;
	}

	function fmtPrice(p: string | number | null): string {
		const v = Number(p);
		return Number.isFinite(v) ? String(parseFloat(v.toFixed(2))) : '—';
	}

	function affordable(price: string | null, currency: string): boolean {
		return (bal[currency] ?? 0) >= priceNum(price);
	}

	function pricesOf(p: ShopProduct): ShopPrice[] {
		if (p.prices?.length) return p.prices;
		return [{ price: p.price, min_price: p.min_price, currency: p.currency }];
	}

	/** Товар коштує УСІ валюти одночасно (монети І кристали) —
	вистачає лише коли баланс достатній по КОЖНІЙ з цін. */
	function canAfford(p: ShopProduct): boolean {
		return pricesOf(p).every((pr) => affordable(pr.price, pr.currency));
	}

	const CUR_LABEL: Record<string, string> = {
		coins: 'монет',
		cristals: 'кристалів',
		beavers: 'бобрів'
	};

	/** «231 монет + 99 кристалів» — усі ціни товару одним рядком. */
	function priceListLabel(p: ShopProduct): string {
		return pricesOf(p)
			.map((pr) => `${fmtPrice(pr.price)} ${CUR_LABEL[pr.currency] ?? pr.currency}`)
			.join(' + ');
	}

	function shortAff(pr: ShopPrice): boolean {
		return !affordable(pr.price, pr.currency);
	}

	function openDetail(p: ShopProduct): void {
		detailP = p;
		confirmBuy = null;
	}

	function closeDetail(): void {
		detailP = null;
	}

	// portal більше не потрібен: AppModal сам рендерить у <body>

	async function buy(): Promise<void> {
		if (!confirmBuy) return;
		const p = confirmBuy;
		confirmBuy = null;
		busyId = p.id;
		err = '';
		okMsg = '';
		try {
			const res = await api.shopBuy(account_id, p.id, 1);
			if (res.status === 200 || res.status === 201) {
				okMsg = 'Замовлення створено ✅ Монети списано.';
				fx.celebrate('order');
				setSub('orders');
				detailP = null;
				data = await store.shopRefresh(account_id);
				// успіх: пульс нового замовлення й балансу
				await tick();
				const first = document.querySelector<HTMLElement>('.feed-ord .ord');
				if (first) pop(first, 1.03);
				if (balEl) pop(balEl, 1.08);
			} else {
				err =
					res.status === 400 || res.status === 422
						? 'Не вдалося оформити: можливо, недостатньо монет або товар закінчився.'
						: `Магазин відповів помилкою ${res.status}.`;
			}
		} catch (e) {
			err = friendlyError(e);
			if (e instanceof ApiError && e.code === 'account_needs_relogin') {
				err = 'Потрібне перепідключення акаунта MyStat.';
			}
		} finally {
			busyId = null;
		}
	}

	async function discard(uuid: string): Promise<void> {
		confirmDiscard = null;
		busyId = -1;
		err = '';
		okMsg = '';
		try {
			const res = await api.shopDiscard(account_id, uuid);
			if (res.status === 200 || res.status === 201) {
				okMsg = 'Замовлення скасовано, кошти повернуто.';
				data = await store.shopRefresh(account_id);
			} else {
				err = `Не вдалося скасувати (${res.status}).`;
			}
		} catch (e) {
			err = friendlyError(e);
		} finally {
			busyId = null;
		}
	}
</script>

<svelte:window
	onkeydown={(e) => {
		if (e.key === 'Escape') {
			confirmBuy = null;
			confirmDiscard = null;
			detailP = null;
		}
	}}
/>

<div class="toolbar">
	<h2 class="inline">Магазин</h2>
	<div class="flex-sp"></div>
	<div class="chips-row" bind:this={balEl}>
		<span class="chip bal">
			<Coins size={14} /> <AnimatedNumber value={bal.coins ?? 0} />
		</span>
		<span class="chip bal">
			<Gem size={14} /> <AnimatedNumber value={bal.cristals ?? 0} />
		</span>
	</div>
</div>

<div class="subtabs" role="group" aria-label="Розділ магазину">
	<button class:active={sub === 'catalog'} use:pressable onclick={() => setSub('catalog')}>
		<ShoppingBag size={15} /> Каталог
	</button>
	<button class:active={sub === 'orders'} use:pressable onclick={() => setSub('orders')}>
		<Package size={15} /> Мої замовлення
		{#if orders.length}<span class="n">{orders.length}</span>{/if}
	</button>
</div>

{#if err && err !== OFFLINE_EMPTY}<p class="msg err">⚠ {err}</p>{/if}
{#if okMsg}<p class="msg ok">✓ {okMsg}</p>{/if}

{#if !data}
	{#if loaded}
		<p class="text-faint empty">{err === OFFLINE_EMPTY ? OFFLINE_EMPTY : 'Немає даних'}</p>
	{:else}
		<div class="skel"></div>
	{/if}
{:else}
{#key sub}
<div class="pane" in:slideX={{ dir: subDir, distance: 24, duration: 340 }}>
{#if sub === 'catalog'}
	<div class="search">
		<Search size={15} />
		<input
			type="search"
			placeholder="Пошук товару…"
			bind:value={q}
		/>
		{#if q}
			<button class="clear" onclick={() => (q = '')} aria-label="Очистити">
				<X size={14} /></button>
		{/if}
	</div>

	{#if products.length}
		<div class="grid-prod" use:stagger={{ step: 40, max: 12, scale: true }}>
			{#each products as p (p.id)}
				<article class="prod glass"
					in:springIn={{ duration: 320 }}
					use:spotSmall>
					<button class="open" onclick={() => openDetail(p)}
						title="Детальніше">
						<span class="p-photo">
							{#if p.image}
								<SmartImage src={p.image} alt={p.title} fit="contain" iconSize={28} />
							{:else}
								<span class="ph" aria-hidden="true"><Package size={26} /></span>
							{/if}
						</span>
						<b class="p-title">{p.title}</b>
						{#if p.text}
							<span class="p-text text-faint small">{p.text}</span>
						{/if}
					</button>
					<div class="p-body">
						<div class="p-prices">
							{#each pricesOf(p) as pr (pr.currency)}
								<span class="price {pr.currency}"
									class:short={shortAff(pr)}
									title={pr.currency === 'cristals'
										? 'кристалів' : 'монет'}>
									{#if pr.currency === 'cristals'}
										<Gem size={13} strokeWidth={2.2} />
									{:else}
										<Coins size={13} strokeWidth={2.2} />
									{/if}
									{fmtPrice(pr.price)}
								</span>
							{/each}
						</div>
						<div class="p-foot">
							{#if p.quantity != null && p.quantity <= 0}
								<span class="q out">немає</span>
							{:else if canAfford(p)}
								<button
									class="btn f" use:pressable
									disabled={busyId === p.id}
									onclick={() => (confirmBuy = p)}>
									{busyId === p.id ? '…' : 'Придбати'}</button>
							{:else}
								<span class="q low" title="Недостатньо коштів">не вистачає</span>
							{/if}
						</div>
					</div>

					{#if confirmBuy?.id === p.id}
						<div class="confirm" in:springIn={{ duration: 260, start: 0.97, y: 0 }}>
							<b>Купити «{p.title}»?</b>
							<span class="text-dim small">
								Спишеться: {priceListLabel(p)}</span>
							<span class="c-btns">
								<button class="btn f" onclick={() => void buy()}>
									Так</button>
								<button class="btn f ghost"
									onclick={() => (confirmBuy = null)}>Ні</button>
							</span>
						</div>
					{/if}
				</article>
			{/each}
		</div>
	{:else}
		<p class="text-faint empty">
			{qd ? 'Нічого не знайдено' : 'Каталог порожній'}</p>
	{/if}
{:else}
	{#if orders.length}
		<div class="feed-ord" use:stagger={{ step: 45, max: 10 }}>
			{#each orders as o (o.id)}
				<article class="ord glass" class:dim={o.archived}>
					<header class="o-head">
						<b>№ {o.id}</b>
						<span class="st chip">{o.status_label}</span>
						<span class="text-faint small mono">{o.created_at}</span>
						<div class="flex-sp"></div>
						<span class="o-totals">
							{#each o.totals as t (t.currency)}
								<span class="price {t.currency}">
									{#if t.currency === 'cristals'}
										<Gem size={13} strokeWidth={2.2} />
									{:else}
										<Coins size={13} strokeWidth={2.2} />
									{/if}
									{fmtPrice(t.price)}
								</span>
							{/each}
						</span>
					</header>
					<div class="o-items">
						{#each o.items as it, i (String(it.product_id) + '-' + i)}
							<span class="o-item">
								{#if it.image}
									<span class="o-img"><SmartImage src={it.image} fit="contain" radius="8px" iconSize={16} /></span>
								{/if}
								<span class="t">
									<b>{it.title || `товар ${it.product_id}`}</b>
									<span class="text-faint small">× {it.quantity}</span>
								</span>
							</span>
						{/each}
					</div>
					{#if o.can_discard}
						<footer class="o-foot">
							<button class="btn f ghost warn"
								onclick={() => (confirmDiscard = o.uuid)}>
								Скасувати</button>
						</footer>
					{/if}
					{#if confirmDiscard === o.uuid}
						<div class="confirm" in:springIn={{ duration: 260, start: 0.97, y: 0 }}>
							<b>Скасувати замовлення № {o.id}?</b>
							<span class="c-btns">
								<button class="btn f warn"
									onclick={() => void discard(o.uuid)}>Так</button>
								<button class="btn f ghost"
									onclick={() => (confirmDiscard = null)}>Ні</button>
							</span>
						</div>
					{/if}
				</article>
			{/each}
		</div>
	{:else}
		<p class="text-faint empty">Замовлень ще не було</p>
	{/if}
{/if}
</div>
{/key}
{/if}

<!-- модалка товару: єдиний скелет AppModal (як у деталей домашки):
	 header з іконкою, скрол-body, footer; закриття — Esc/фон/× -->
<AppModal
	open={detailP != null}
	title={detailP?.title ?? ''}
	icon={Package}
	tone="accent"
	width={440}
	onclose={closeDetail}>
	{#if detailP}
		{#if detailP.image}
			<span class="hero"><SmartImage src={detailP.image} alt={detailP.title} fit="contain" radius="var(--radius-md)" iconSize={40} /></span>
		{:else}
			<span class="hero ph" aria-hidden="true"><Package size={40} /></span>
		{/if}
		<div class="p-prices big">
			{#each pricesOf(detailP) as pr (pr.currency)}
				<span class="price {pr.currency}" class:short={shortAff(pr)}>
					{#if pr.currency === 'cristals'}
						<Gem size={15} strokeWidth={2.2} />
					{:else}
						<Coins size={15} strokeWidth={2.2} />
					{/if}
					{fmtPrice(pr.price)}
				</span>
			{/each}
		</div>
		{#if detailP.text}
			<p class="descr">{detailP.text}</p>
		{/if}
		{#if detailP.properties.length}
			<dl class="props">
				{#each detailP.properties as prop (prop.name)}
					<div><dt>{prop.name}</dt><dd>{prop.value}</dd></div>
				{/each}
			</dl>
		{/if}
		{#if detailP.quantity != null && detailP.quantity <= 0}
			<p class="q out center">Немає в наявності</p>
		{/if}
	{/if}
	{#snippet footer()}
		{#if detailP}
			{#if detailP.quantity != null && detailP.quantity <= 0}
				<button class="btn f ghost" disabled>Немає в наявності</button>
			{:else if confirmBuy === detailP}
				<span class="text-dim small m-confirm-lbl">
					Купити за {priceListLabel(detailP)}?</span>
				<span class="c-btns">
					<button class="btn f" onclick={() => void buy()}>Так</button>
					<button class="btn f ghost" onclick={() => (confirmBuy = null)}>
						Ні</button>
				</span>
			{:else}
				<button class="btn f buy"
					onclick={() => detailP && (confirmBuy = detailP)}>
					Придбати</button>
			{/if}
		{/if}
	{/snippet}
</AppModal>


<style>	.inline {
		font-size: 16px;
	}

	.chip.bal {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}

	.subtabs {
		display: flex;
		gap: 6px;
		margin-bottom: 14px;
	}

	.subtabs button {
		display: inline-flex;
		align-items: center;
		gap: 7px;
		padding: 8px 14px;
		border: 1px solid var(--glass-border);
		border-radius: 999px;
		background: var(--surface-a65, rgba(18,22,31,0.65));
		color: var(--text-dim);
		font: inherit;
		font-size: 0.88rem;
		cursor: pointer;
	}

	.subtabs button.active {
		background: var(--accent);
		border-color: transparent;
		color: #fff;
	}

	.subtabs .n {
		background: rgba(255, 255, 255, 0.18);
		border-radius: 999px;
		padding: 0 7px;
		font-size: 0.76rem;
	}

	.msg {
		margin: 0 0 12px;
		font-size: 0.9rem;
	}

	.msg.err {
		color: var(--danger);
	}

	.msg.ok {
		color: var(--success);
	}

	.search {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 9px 14px;
		margin-bottom: 14px;
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-md);
		background: var(--surface-a65, rgba(18,22,31,0.65));
		color: var(--text-faint);
	}

	.search input {
		flex: 1;
		border: 0;
		background: transparent;
		color: var(--text);
		font: inherit;
		outline: none;
	}

	.clear {
		display: grid;
		place-items: center;
		width: 24px;
		height: 24px;
		border: 0;
		border-radius: 8px;
		background: transparent;
		color: var(--text-faint);
		cursor: pointer;
	}

	.grid-prod {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
		gap: 12px;
	}

	.prod {
		position: relative;
		display: flex;
		flex-direction: column;
		border-radius: var(--radius-md);
		overflow: hidden;
		content-visibility: auto;
		contain-intrinsic-size: auto 330px;
	}

	/* фото: фіксоване співвідношення, повністю видно (contain) на рівній підкладці */
	.p-photo {
		display: block;
		width: 100%;
		aspect-ratio: 4 / 3;
		background: var(--surface-2);
	}

	.prod .ph {
		width: 100%;
		height: 100%;
		display: grid;
		place-items: center;
		color: var(--text-faint);
	}

	.prod {
		transition:
			transform 0.22s cubic-bezier(0.22, 1, 0.36, 1),
			box-shadow 0.22s ease;
	}

	@media (hover: hover) {
		.prod:hover {
			transform: translateY(-3px);
			box-shadow: 0 10px 24px rgba(0, 0, 0, 0.22);
		}
	}

	/* низ картки (ціна/кнопка) завжди притиснутий донизу */
	.p-body {
		display: flex;
		flex-direction: column;
		gap: 4px;
		margin-top: auto;
		padding: 10px 12px 12px;
	}

	/* клікабельна верхівка картки (відкриває модалку товару) */
	.open {
		display: flex;
		flex-direction: column;
		align-items: stretch;
		gap: 4px;
		padding: 0;
		border: 0;
		background: transparent;
		color: inherit;
		font: inherit;
		text-align: left;
		cursor: pointer;
		flex: 1 1 auto;
	}

	.open .p-title {
		padding: 8px 12px 0;
		/* назва: рівно 2 рядки, фіксована висота блоку */
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
		min-height: calc(2 * 1.3em + 8px);
		box-sizing: content-box;
	}

	.open .p-text {
		padding: 0 12px;
	}

	.o-totals {
		display: inline-flex;
		gap: 8px;
	}
	.p-prices {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 14px;
		min-height: 2.9em;
		align-content: flex-start;
	}

	.price.short {
		opacity: 0.4;
	}
	.p-title {
		font-size: 0.92rem;
		line-height: 1.3;
	}

	.p-text {
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
		min-height: 2.3em;
	}

	.p-foot {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 8px;
		margin-top: 6px;
		min-height: 34px;
	}

	.price {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		font-weight: 700;
		font-size: 0.95rem;
	}

	.price.coins {
		color: var(--amber);
	}

	.price.cristals {
		color: var(--cyan);
	}

	.price.beavers {
		color: var(--success);
	}

	.q {
		font-size: 0.78rem;
		color: var(--text-faint);
	}

	.q.out {
		color: var(--danger);
	}

	.btn.f {
		font-size: 13px;
		padding: 7px 12px;
	}

	.btn.warn {
		color: var(--danger);
	}

	.confirm {
		position: absolute;
		inset: 0;
		z-index: 2;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 6px;
		padding: 14px;
		text-align: center;
		background: color-mix(in srgb, var(--bg) 92%, transparent);
		-webkit-backdrop-filter: blur(calc(4px + 0px));
		backdrop-filter: blur(4px);
	}

	:global(html[data-perf='lite']) .confirm {
		-webkit-backdrop-filter: none;
		backdrop-filter: none;
		background: var(--bg);
	}

	.m-confirm-lbl {
		margin: auto 0;
		flex: 1;
	}

	.c-btns {
		display: flex;
		gap: 8px;
		margin-top: 6px;
	}

	.feed-ord {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.ord {
		border-radius: var(--radius-md);
		padding: 12px 14px;
		content-visibility: auto;
		contain-intrinsic-size: auto 110px;
	}

	.ord.dim {
		opacity: 0.5;
	}

	.ord.dim .o-head .st {
		background: var(--surface-2);
		color: var(--text-faint);
	}
	.o-head {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.o-head .st {
		background: var(--accent-soft);
		color: var(--accent);
	}

	.o-items {
		display: flex;
		flex-wrap: wrap;
		gap: 10px 18px;
		margin-top: 10px;
	}

	.o-item {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.o-img {
		display: block;
		width: 34px;
		height: 34px;
		flex: none;
		border-radius: 8px;
		overflow: hidden;
	}

	.o-item .t {
		display: flex;
		flex-direction: column;
		font-size: 0.86rem;
	}

	.o-foot {
		margin-top: 10px;
		display: flex;
		justify-content: flex-end;
	}

	.empty {
		padding: 30px 6px;
		text-align: center;
	}

	/* скло тут — великий контейнер: ховер не має сіріти
	 (глобальний .glass:hover із tokens.css гасимо) */
	.prod:hover,
	.ord:hover {
		background: var(--surface-a65, rgba(18,22,31,0.65));
	}

	.skel {
		height: 220px;
		border-radius: var(--radius-md);
		background:
			linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.05), transparent),
			var(--surface-2);
		background-size: 200% 100%;
		animation: shimmer 1.3s infinite linear;
	}

	@keyframes shimmer {
		from {
			background-position: 200% 0;
		}
		to {
			background-position: -200% 0;
		}
	}

	@media (max-width: 900px) {
		.grid-prod {
			grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
		}
	}

	/* ============ модалка товару ============ */

	.hero {
		display: block;
		width: 100%;
		aspect-ratio: 4 / 3;
		max-height: 300px;
		border-radius: var(--radius-md);
		overflow: hidden;
		margin-bottom: 12px;
	}

	.hero.ph {
		height: 180px;
		display: grid;
		place-items: center;
		background: var(--surface-2);
		color: var(--text-faint);
	}

	.p-prices.big {
		margin-top: 8px;
	}

	.p-prices.big .price {
		font-size: 1.05rem;
	}

	.descr {
		margin: 10px 0;
		color: var(--text-dim);
		line-height: 1.55;
		white-space: pre-line;
	}

	.props {
		display: grid;
		gap: 6px;
		margin: 12px 0;
	}

	.props div {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 12px;
		border-bottom: 1px dashed var(--glass-border);
		padding-bottom: 5px;
	}

	.props dt {
		color: var(--text-faint);
		font-size: 0.85rem;
	}

	.props dd {
		margin: 0;
		font-size: 0.9rem;
		text-align: right;
	}

	.c-btns {
		display: flex;
		gap: 8px;
	}

	.buy {
		width: 100%;
		margin-top: 12px;
	}

	.q.center {
		text-align: center;
		padding: 10px 0 2px;
	}
</style>
