<script lang="ts">
	import { fly } from 'svelte/transition';
	import { Trash2, Loader2, CheckCircle2, AlertTriangle } from '@lucide/svelte';
	import { PROJECT_NAME } from '$lib/config';
	import { springIn, blurFade, pressable, pop, shake } from '$lib/motion';

	let phase = $state<'idle' | 'working' | 'done' | 'error'>('idle');
	let log: string[] = $state([]);
	let card = $state<HTMLElement>();
	let stEl = $state<HTMLElement>();

	$effect(() => {
		if (phase === 'done' && stEl) pop(stEl, 1.08);
		if (phase === 'error' && card) shake(card);
	});

	function add(line: string): void {
		log = [...log, line];
	}

	async function wipe(): Promise<void> {
		phase = 'working';
		log = [];
		try {
			// 1. Service Workers
			if ('serviceWorker' in navigator) {
				const regs = await navigator.serviceWorker.getRegistrations();
				for (const r of regs) await r.unregister();
				add(`Service Workers: ${regs.length} видалено`);
			} else {
				add('Service Workers: не підтримуються');
			}

			// 2. Кеші Cache Storage
			if ('caches' in window) {
				const keys = await caches.keys();
				for (const k of keys) await caches.delete(k);
				add(`Кеші: ${keys.length} очищено`);
			}

			// 3. localStorage
			const n = localStorage.length;
			localStorage.clear();
			add(`localStorage: ${n} ключів видалено`);

			// 4. sessionStorage
			sessionStorage.clear();
			add('sessionStorage очищено');

			phase = 'done';
			add('Готово! Перезавантаження…');
			setTimeout(() => location.replace('/'), 1500);
		} catch (e) {
			add(String(e));
			phase = 'error';
		}
	}
</script>

<svelte:head><title>Відновлення доступу · M1 ID</title><meta name="robots" content="noindex, nofollow" /></svelte:head>

<main>
	<article class="glass card" bind:this={card} in:springIn={{ start: 0.94, duration: 460, y: 14 }}>
		<h1><Trash2 size={20} /> Скидання {PROJECT_NAME}</h1>
		<p class="dim">
			Видаляє service worker, усі кеші та локальні дані (у т.ч.
			вхід). Використовуй, якщо щось зависло у старій версії.
		</p>

		{#if phase === 'idle'}
			<button class="btn primary big" use:pressable onclick={wipe}>
				<Trash2 size={17} /> Скинути все</button>
		{:else if phase === 'working'}
			<p class="st" in:blurFade={{ y: 4 }}><Loader2 size={17} className="spin" /> Очищую…</p>
		{:else if phase === 'done'}
			<p class="st ok" bind:this={stEl} in:blurFade={{ y: 4 }}><CheckCircle2 size={17} /> Готово</p>
		{:else}
			<p class="st err" in:blurFade={{ y: 4 }}><AlertTriangle size={17} /> Помилка</p>
		{/if}

		{#if log.length}
			<ul transition:fly={{ y: 8, duration: 150 }}>
				{#each log as line (line)}
					<li in:fly={{ x: -10, duration: 320 }}>
						<svg class="tick" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
							<path d="M3 8.5 l3.2 3.2 l6.8 -7.4" pathLength="1" />
						</svg>
						<span>{line}</span>
					</li>
				{/each}
			</ul>
		{/if}
	</article>
</main>

<style>
	main {
		min-height: 100vh;
		display: grid;
		place-items: center;
		padding: 20px;
	}

	article {
		width: min(420px, 100%);
		padding: 22px;
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	h1 {
		margin: 0;
		font-size: 17px;
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.dim {
		margin: 0;
		font-size: 13px;
		color: var(--text-dim);
	}

	.big {
		justify-content: center;
	}

	.st {
		margin: 0;
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 14px;
	}

	.ok {
		color: var(--success);
	}

	.err {
		color: var(--danger);
	}

	ul {
		margin: 0;
		padding: 10px 14px;
		border-radius: var(--radius-md);
		background: color-mix(in srgb, var(--surface) 40%, transparent);
		font-size: 12.5px;
		color: var(--text-dim);
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	li {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.tick {
		flex: none;
		fill: none;
		stroke: var(--success);
		stroke-width: 2;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.tick path {
		stroke-dasharray: 1;
		stroke-dashoffset: 1;
		animation: rst-draw 380ms var(--ease-out) 120ms forwards;
	}
	@keyframes rst-draw {
		to { stroke-dashoffset: 0; }
	}
	:global(html[data-anim='off']) .tick path {
		animation: none;
		stroke-dashoffset: 0;
	}

	:global(.spin) {
		animation: rst-spin 0.9s linear infinite;
	}

	@keyframes rst-spin {
		to {
			transform: rotate(360deg);
		}
	}
</style>
