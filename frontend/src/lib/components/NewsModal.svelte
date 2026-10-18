<script lang="ts">
	import { ChevronLeft, Newspaper } from '@lucide/svelte';
	import { api, type NewsDetail, type NewsItem } from '$lib/api/client';
	import { store } from '$lib/stores/appStore.svelte';
	import { sanitizeHtml } from '$lib/sanitize';
	import { friendlyError } from '$lib/errors';
	import { Button, Dialog, EmptyState, ErrorState, Skeleton } from '$lib/ui';
	import { stagger, pressable, blurFade, motionOK, fx } from '$lib/motion';
	import { cubicOut } from 'svelte/easing';

	let {
		account_id,
		onclose
	}: {
		account_id: number;
		onclose: () => void;
	} = $props();

	/** Модалка новин: список (з кеша стора) + повний текст живим запитом.
	 *  HTML тексту санітизуємо allow-list санітайзером ($lib/sanitize):
	 *  mapi віддає довільний HTML з адмінки. */

	let open = $state(true);
	let list = $state<NewsItem[]>([]);
	let listLoading = $state(true);
	let listErr = $state('');

	async function loadList(): Promise<void> {
		listLoading = true;
		listErr = '';
		try {
			const v = await store.news(account_id);
			list = Array.isArray(v.items) ? v.items : [];
		} catch (e) {
			listErr = friendlyError(e);
		} finally {
			listLoading = false;
		}
	}

	$effect(() => {
		void loadList();
	});
	let current = $state<NewsItem | null>(null);
	let detail = $state<NewsDetail | null>(null);
	let loading = $state(false);
	let err = $state('');

	// напрямок: 1 — уперед (у деталі), -1 — назад (до списку)
	let navDir = $state<1 | -1>(1);

	/** Панель з напрямком: зсув по X (+ blur лише на рівні full); вихідна йде в протилежний бік. */
	function pane(node: Element, { dir = 1, out = false }: { dir?: 1 | -1; out?: boolean } = {}) {
		if (!motionOK()) return { duration: 0 };
		const sign = out ? -dir : dir;
		const blur = fx();
		return {
			duration: 380,
			easing: cubicOut,
			css: (t: number, u: number) =>
				`opacity:${t};transform:translateX(${u * 36 * sign}px)` + (blur ? `;filter:blur(${u * 6}px)` : '')
		};
	}
	const view = $derived(current ? `d${current.id}` : 'list');

	async function openItem(item: NewsItem): Promise<void> {
		navDir = 1;
		// гард stale-гонки: поки летить повільна відповідь по новині A,
		// користувач може відкрити B — відповідь A не має перезаписати
		// detail/loading відкритої B.
		const item0 = item;
		current = item0;
		detail = null;
		err = '';
		loading = true;
		try {
			const d = await api.newsDetail(account_id, item0.id);
			if (current !== item0) return; // уже відкрита інша новина
			detail = d;
		} catch (e) {
			if (current !== item0) return;
			err = friendlyError(e);
		} finally {
			// loading скидаємо лише якщо ця новина все ще відкрита
			if (current === item0) loading = false;
		}
	}

	/** Esc у деталях повертає до списку, а не закриває вікно. */
	function onKeydownCapture(e: KeyboardEvent): void {
		if (e.key === 'Escape' && current) {
			e.preventDefault();
			back();
		}
	}

	function back(): void {
		navDir = -1;
		current = null;
		detail = null;
		err = '';
	}

	function fmtDay(iso: string): string {
		if (!iso) return '';
		const [y, mo, d] = iso.slice(0, 10).split('-').map(Number);
		if (!y) return iso;
		return `${d} ${MONTHS_GEN[mo - 1] ?? mo} ${y}`;
	}

	const MONTHS_GEN = [
		'січня', 'лютого', 'березня', 'квітня', 'травня', 'червня',
		'липня', 'серпня', 'вересня', 'жовтня', 'листопада', 'грудня'
	];
</script>

<svelte:window onkeydowncapture={onKeydownCapture} />

<Dialog bind:open title="Новини" size="lg" {onclose}>
	<div class="stack">
	{#key view}
	<div class="pane" in:pane={{ dir: navDir }} out:pane={{ dir: navDir, out: true }}>
	{#if current}
		<div class="nav">
			<span use:pressable={{ scale: 0.95 }} style="display:inline-flex">
				<Button variant="ghost" size="sm" icon={ChevronLeft} onclick={back}>Назад</Button>
			</span>
		</div>
		{#if loading}
			<Skeleton lines={4} />
		{:else if err}
			<ErrorState
				title="Не вдалося відкрити новину"
				description={err}
				onretry={() => current && void openItem(current)}
			/>
		{:else if detail}
			<div in:blurFade={{ duration: 420, amount: 10, y: 8 }}>
				{#if detail.image}
					<img class="hero" src={detail.image} alt="" loading="lazy" />
				{/if}
				<h3 class="ttl">{detail.title}</h3>
				<p class="meta">
					{fmtDay(detail.published_at)}{#if detail.author}
						· {detail.author}{/if}
				</p>
				<div class="rich">{@html sanitizeHtml(detail.text)}</div>
			</div>
		{/if}
	{:else if listLoading}
		<Skeleton lines={5} height={64} radius="var(--radius-md)" />
	{:else if listErr}
		<ErrorState
			title="Не вдалося завантажити новини"
			description={listErr}
			onretry={() => void loadList()}
		/>
	{:else if list.length}
		<div class="feed" use:stagger={{ step: 40, y: 12, max: 10 }}>
			{#each list as n (n.id)}
				<button class="item" use:pressable={{ scale: 0.98 }} onclick={() => void openItem(n)}>
					{#if n.image}
						<img src={n.image} alt="" loading="lazy" />
					{:else}
						<span class="ph" aria-hidden="true"><Newspaper size={18} /></span>
					{/if}
					<span class="t">
						<b>{n.title}</b>
						<span class="date">{fmtDay(n.published_at)}</span>
					</span>
					{#if !n.is_viewed}
						<span class="dot-new" title="Нове" role="img" aria-label="Нове"></span>
					{/if}
				</button>
			{/each}
		</div>
	{:else}
		<EmptyState icon={Newspaper} title="Новин поки немає" />
	{/if}
	</div>
	{/key}
	</div>
</Dialog>

<style>
	/* обидві панелі на час переходу лежать в одній комірці */
	.stack {
		display: grid;
		overflow-x: clip;
	}
	.pane {
		grid-area: 1 / 1;
		min-width: 0;
	}

	.nav {
		margin: 0 calc(-1 * var(--space-2)) var(--space-2);
	}

	.feed {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.item {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		width: 100%;
		padding: var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		color: var(--color-text);
		font: inherit;
		text-align: left;
		cursor: pointer;
		transition: background var(--dur-fast) var(--ease-out);
	}

	.item:hover {
		background: var(--color-hover);
	}

	.item:focus-visible {
		outline: 2px solid var(--color-accent);
		outline-offset: 2px;
	}

	.item img,
	.item .ph {
		width: 64px;
		height: 64px;
		flex: 0 0 64px;
		border-radius: var(--radius-sm);
		object-fit: cover;
	}

	.item .ph {
		display: grid;
		place-items: center;
		background: var(--color-surface-2);
		color: var(--color-text-subtle);
	}

	.item .t {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		flex: 1;
		min-width: 0;
	}

	.item .t b {
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
		font-size: var(--text-md);
		font-weight: var(--weight-semibold);
		line-height: var(--leading-tight);
	}

	.date {
		font-size: var(--text-xs);
		color: var(--color-text-subtle);
	}

	.dot-new {
		width: 8px;
		height: 8px;
		flex: 0 0 8px;
		border-radius: var(--radius-full);
		background: var(--color-info);
		/* двічі «дихає», привертаючи увагу */
		animation: nw-breathe 1.4s var(--ease-in-out) 0.5s 2;
	}
	@keyframes nw-breathe {
		0%, 100% { transform: scale(1); box-shadow: 0 0 0 0 color-mix(in srgb, var(--color-info) 50%, transparent); }
		50% { transform: scale(1.35); box-shadow: 0 0 0 6px transparent; }
	}
	:global(html[data-perf='lite']) .dot-new,
	:global(html[data-anim='off']) .dot-new {
		animation: none;
	}

	.hero {
		width: 100%;
		max-height: 240px;
		object-fit: cover;
		border-radius: var(--radius-md);
		margin-bottom: var(--space-3);
	}

	.ttl {
		font-size: var(--text-lg);
		font-weight: var(--weight-semibold);
		line-height: var(--leading-tight);
	}

	.meta {
		margin: var(--space-2) 0 var(--space-3);
		font-size: var(--text-xs);
		color: var(--color-text-subtle);
	}

	.rich {
		line-height: var(--leading-normal);
		font-size: var(--text-base);
		color: var(--color-text-muted);
		overflow-wrap: break-word;
	}

	.rich :global(img) {
		max-width: 100%;
		border-radius: var(--radius-sm);
	}

	.rich :global(a) {
		color: var(--color-accent-text);
	}

	.rich :global(p) {
		margin: 0 0 var(--space-3);
	}
</style>
