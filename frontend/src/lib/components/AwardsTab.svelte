<script lang="ts">
	import { Gift, RefreshCw, Check, ShoppingBag } from '@lucide/svelte';
	import { api, type AwardsView, type AwardsItem } from '$lib/api/client';
	import { friendlyError, isNetworkError, OFFLINE_EMPTY } from '$lib/errors';
	import { AnimatedNumber, stagger, spotlight, pressable, springIn, pop } from '$lib/motion';

	let {
		account_id,
		/** Тик «Оновити» з +page: змінився → перечитуємо з force=true. */
		refreshTick = 0
	}: {
		account_id: number;
		refreshTick?: number;
	} = $props();

	let data = $state<AwardsView | null>(null);
	let err = $state('');
	let busy = $state(false);
	let itemBusy = $state<number | null>(null);
	let cat = $state('');

	async function load(force = false): Promise<void> {
		busy = true;
		err = '';
		try {
			data = await api.awards(account_id, force);
			if (!data.categories.some((c) => c.key === cat)) {
				cat = data.categories[0]?.key ?? '';
			}
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

	// елементи карток за id — для пружинного «поп» після покупки
	const itemEls = new Map<number, HTMLElement>();
	function regItem(node: HTMLElement, id: number) {
		itemEls.set(id, node);
		return { destroy: () => itemEls.delete(id) };
	}

	async function buy(item: AwardsItem): Promise<void> {
		if (itemBusy !== null || !data) return;
		itemBusy = item.id;
		err = '';
		try {
			await api.awardsBuy(account_id, [item.id]);
			await load(true);
			const el = itemEls.get(item.id);
			if (el) pop(el, 1.08);
		} catch (e) {
			err = friendlyError(e);
		} finally {
			itemBusy = null;
		}
	}

	async function equip(item: AwardsItem): Promise<void> {
		if (itemBusy !== null || !data) return;
		itemBusy = item.id;
		err = '';
		try {
			await api.awardsEquip(account_id, item.id);
			await load(true);
		} catch (e) {
			err = friendlyError(e);
		} finally {
			itemBusy = null;
		}
	}

	const CAT_LABELS: Record<string, string> = {
		body: 'Тіло',
		mouth: 'Рот',
		eyes: 'Очі',
		background: 'Фон',
		hat: 'Капелюх',
		glasses: 'Окуляри',
		clothes: 'Одяг'
	};

	function catLabel(key: string): string {
		return CAT_LABELS[key] ?? key;
	}

	const items = $derived(
		data?.categories.find((c) => c.key === cat)?.items ?? []
	);
</script>

{#if err && !data}
	<p class="empty">{err}</p>
{:else if !data}
	<p class="empty">Завантажую…</p>
{:else}
	{#if err}<p class="empty">{err}</p>{/if}
	<div class="aw-top">
		<div class="aw-balance glass-tile">
			<div class="ab-ico"><Gift size={20} strokeWidth={2} /></div>
			<div>
				<div class="ab-label">Баланс бобрів</div>
				<div class="ab-value"><AnimatedNumber value={Number(data.beavers)} /></div>
			</div>
		</div>
		<button class="btn icon" use:pressable onclick={() => load(true)} disabled={busy} title="Оновити">
			<span class="spinwrap" class:spin={busy}>
				<RefreshCw size={15} strokeWidth={2} />
			</span>
		</button>
	</div>

	{#if data.categories.length === 0}
		<p class="empty">Каталог нагород порожній</p>
	{:else}
		{#if data.categories.length > 1}
			<div class="chips-row aw-cats">
				{#each data.categories as c (c.key)}
					<button class="chip aw-cat" use:pressable class:active={cat === c.key}
						onclick={() => (cat = c.key)}>
						{catLabel(c.key)} <span class="aw-count">{c.items.length}</span>
					</button>
				{/each}
			</div>
		{/if}

		{#key cat}
		<div class="aw-grid" use:stagger={{ selector: ':scope > .aw-item', step: 28, max: 12, y: 10, scale: true }}>
			{#each items as it (it.id)}
				{@const affordable = it.free || it.purchased || it.price <= data.beavers}
				<div class="aw-item glass-tile lift" class:equipped={it.equipped}
					use:regItem={it.id} use:spotlight>
					<div class="aw-imgwrap">
						<img class="aw-img" src={it.img} alt="" loading="lazy"
							referrerpolicy="no-referrer" />
						{#if it.equipped}
							<span class="aw-badge eq" in:springIn={{ start: 0.5, y: 0, duration: 340 }}><Check size={11} strokeWidth={3} /> надіто</span>
						{:else if it.purchased}
							<span class="aw-badge own" in:springIn={{ start: 0.6, y: 0, duration: 300 }}>куплено</span>
						{/if}
					</div>
					<div class="aw-meta">
						{#if it.free || it.purchased}
							<span class="aw-price free">безкоштовно</span>
						{:else}
							<span class="aw-price" class:poor={!affordable}>
								{it.price} {it.currency}
							</span>
						{/if}
					</div>
					{#if it.equipped}
						<button class="btn f" use:pressable disabled>Надіто</button>
					{:else if it.free || it.purchased}
						<button class="btn f" use:pressable disabled={itemBusy === it.id}
							onclick={() => equip(it)}>
							{itemBusy === it.id ? '…' : 'Надіти'}
						</button>
					{:else}
						<button class="btn f buy" use:pressable disabled={itemBusy === it.id || !affordable}
							title={!affordable ? 'Недостатньо бобрів' : ''}
							onclick={() => buy(it)}>
							<ShoppingBag size={13} strokeWidth={2} />
							{itemBusy === it.id ? '…' : 'Купити'}
						</button>
					{/if}
				</div>
			{/each}
		</div>
		{/key}
	{/if}
{/if}

<style>
	.aw-top {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-bottom: 12px;
	}
	.aw-balance {
		flex: 1;
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 12px 14px;
		border-radius: 14px;
	}
	.ab-ico {
		width: 38px;
		height: 38px;
		border-radius: 12px;
		display: grid;
		place-items: center;
		background: color-mix(in srgb, var(--accent, #7aa2f7) 18%, transparent);
		color: var(--accent, #7aa2f7);
	}
	.ab-label {
		font-size: 12px;
		opacity: 0.65;
	}
	.ab-value {
		font-size: 20px;
		font-weight: 700;
		line-height: 1.1;
	}
	.aw-cats {
		margin: 0 0 12px;
	}
	.aw-cat {
		cursor: pointer;
		border: 1px solid transparent;
	}
	.aw-cat.active {
		border-color: var(--accent, #7aa2f7);
		color: var(--accent, #7aa2f7);
	}
	.aw-count {
		opacity: 0.55;
		font-size: 11px;
		margin-left: 3px;
	}
	.aw-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(128px, 1fr));
		gap: 10px;
	}
	.aw-item {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 10px;
		border-radius: 14px;
	}
	.aw-badge {
		transform-origin: left top;
	}
	.aw-item.equipped {
		outline: 1px solid color-mix(in srgb, var(--accent, #7aa2f7) 55%, transparent);
	}
	.aw-imgwrap {
		position: relative;
		aspect-ratio: 1;
		border-radius: 10px;
		overflow: hidden;
		background: rgba(128, 128, 128, 0.08);
	}
	.aw-img {
		width: 100%;
		height: 100%;
		object-fit: cover;
	}
	.aw-badge {
		position: absolute;
		top: 6px;
		left: 6px;
		display: inline-flex;
		align-items: center;
		gap: 3px;
		font-size: 10px;
		padding: 2px 7px;
		border-radius: 999px;
		background: rgba(0, 0, 0, 0.55);
		backdrop-filter: blur(4px);
	}
	.aw-badge.eq {
		color: #7ee787;
	}
	.aw-meta {
		display: flex;
		justify-content: space-between;
		align-items: center;
		min-height: 18px;
	}
	.aw-price {
		font-size: 13px;
		font-weight: 600;
	}
	.aw-price.free {
		opacity: 0.6;
		font-weight: 400;
		font-size: 12px;
	}
	.aw-price.poor {
		opacity: 0.45;
	}
	.btn {
		cursor: pointer;
	}
	.btn:disabled {
		opacity: 0.5;
		cursor: default;
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
