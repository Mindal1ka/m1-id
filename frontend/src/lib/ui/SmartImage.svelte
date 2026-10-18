<script lang="ts">
	import { ImageOff } from '@lucide/svelte';
	import { fx } from '$lib/motion';

	interface Props {
		/** Адреса зображення (або ключ для `loader`). */
		src?: string | null;
		alt?: string;
		/** contain — фото повністю, без обрізання; cover — заповнити. */
		fit?: 'contain' | 'cover';
		/** Опційний асинхронний резолвер (напр. авторизований blob-URL). Викликається, коли блок близько до в'юпорта. */
		loader?: ((src: string) => Promise<string>) | null;
		radius?: string;
		/** Розмір іконки-заглушки. */
		iconSize?: number;
		/** Напівпрозорий підкладковий фон. */
		bg?: string;
	}
	let {
		src = null,
		alt = '',
		fit = 'contain',
		loader = null,
		radius = '0',
		iconSize = 24,
		bg = 'var(--surface-2)'
	}: Props = $props();

	type St = 'idle' | 'loading' | 'loaded' | 'error';
	let st = $state<St>('idle');
	let url = $state<string | null>(null);
	let box = $state<HTMLElement | null>(null);
	let img = $state<HTMLImageElement | null>(null);
	let seq = 0;

	// Скидання/резолв при зміні src. Без loader — одразу; з loader — ліниво (IntersectionObserver).
	$effect(() => {
		const s = src;
		const ld = loader;
		const el = box;
		const id = ++seq;
		url = null;
		if (!s) {
			st = 'error';
			return;
		}
		st = 'loading';
		if (!ld) {
			url = s;
			return;
		}
		const run = (): void => {
			ld(s).then(
				(u) => {
					if (id === seq) url = u;
				},
				() => {
					if (id === seq) st = 'error';
				}
			);
		};
		if (!el || typeof IntersectionObserver === 'undefined') {
			run();
			return;
		}
		const io = new IntersectionObserver(
			(es) => {
				if (es.some((e) => e.isIntersecting)) {
					io.disconnect();
					run();
				}
			},
			{ rootMargin: '300px 0px' }
		);
		io.observe(el);
		return () => io.disconnect();
	});

	// Кешоване зображення могло завантажитись до навішування onload
	$effect(() => {
		if (url && img?.complete && img.naturalWidth > 0) st = 'loaded';
	});

	const lite = $derived(!fx());
</script>

<span class="si" bind:this={box} style:border-radius={radius} style:background={bg}>
	{#if st === 'loading' || st === 'idle'}
		<span class="sk" class:lite aria-hidden="true"></span>
	{/if}
	{#if st === 'error'}
		<span class="err" role="img" aria-label={alt || 'Фото недоступне'}>
			<ImageOff size={iconSize} strokeWidth={1.6} />
		</span>
	{:else if url}
		<img
			bind:this={img}
			src={url}
			{alt}
			decoding="async"
			class:ready={st === 'loaded'}
			class:lite
			style:object-fit={fit}
			onload={() => (st = 'loaded')}
			onerror={() => (st = 'error')}
		/>
	{/if}
</span>

<style>
	.si {
		position: relative;
		display: block;
		width: 100%;
		height: 100%;
		overflow: hidden;
	}
	img {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		object-position: center;
		opacity: 0;
		transform: scale(0.96);
		filter: blur(6px);
		transition:
			opacity 0.35s ease,
			transform 0.45s cubic-bezier(0.22, 1, 0.36, 1),
			filter 0.35s ease;
	}
	img.ready {
		opacity: 1;
		transform: none;
		filter: none;
	}
	img.lite {
		transform: none;
		filter: none;
		transition: opacity 0.2s ease;
	}
	.sk {
		position: absolute;
		inset: 0;
		background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.07), transparent);
		background-size: 200% 100%;
		animation: si-shimmer 1.3s infinite linear;
	}
	.sk.lite {
		background: rgba(255, 255, 255, 0.05);
		animation: si-pulse 1.6s ease-in-out infinite;
	}
	.err {
		position: absolute;
		inset: 0;
		display: grid;
		place-items: center;
		color: var(--text-faint);
		opacity: 0.7;
	}
	:global(html[data-anim='off']) .sk {
		animation: none;
	}
	@keyframes si-shimmer {
		from {
			background-position: 200% 0;
		}
		to {
			background-position: -200% 0;
		}
	}
	@keyframes si-pulse {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0.4;
		}
	}
</style>
