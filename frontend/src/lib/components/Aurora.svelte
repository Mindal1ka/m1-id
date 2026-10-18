<script lang="ts">
	import { theme } from '$lib/theme.svelte';

	/* Пауза, коли вкладка прихована; статика при prefers-reduced-motion */
	let hidden = $state(false);
	let reduced = $state(false);

	$effect(() => {
		const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
		const onVis = () => (hidden = document.hidden);
		const onMq = () => (reduced = mq.matches);
		onVis();
		onMq();
		document.addEventListener('visibilitychange', onVis);
		mq.addEventListener('change', onMq);
		return () => {
			document.removeEventListener('visibilitychange', onVis);
			mq.removeEventListener('change', onMq);
		};
	});

	const paused = $derived(hidden || reduced);
</script>

<!-- Опційний фон «північне сяйво»: повільно дрейфуючі розмиті плями (за замовчуванням вимк). -->
{#if theme.aurora}
	<div class="aurora" class:paused aria-hidden="true">
		<div class="blob b1"></div>
		<div class="blob b2"></div>
		<div class="blob b3"></div>
	</div>
{/if}

<style>
	.aurora {
		position: fixed;
		inset: 0;
		z-index: -1;
		overflow: hidden;
		pointer-events: none;
	}

	.blob {
		position: absolute;
		width: 44vw;
		max-width: 620px;
		aspect-ratio: 1;
		border-radius: 50%;
		filter: blur(80px);
		opacity: var(--aur-op, 0.28);
		mix-blend-mode: var(--aur-blend, screen);
		will-change: transform;
		transition:
			background 0.7s ease,
			opacity 0.5s ease;
	}

	/* пауза: анімацію зупинено, will-change знято */
	.paused .blob {
		animation-play-state: paused !important;
		will-change: auto;
	}

	@media (prefers-reduced-motion: reduce) {
		.blob {
			animation: none !important;
			will-change: auto;
		}
	}

	/* суцільні кольори: м'якість дає лише blur, без CSS-градієнтів */
	.b1 {
		background: var(--aur-1, #6c7cff);
		top: -12%;
		left: -8%;
		animation: drift-a 26s ease-in-out infinite alternate;
	}

	.b2 {
		background: var(--aur-2, #22d3ee);
		bottom: -18%;
		right: -10%;
		animation: drift-b 32s ease-in-out infinite alternate;
	}

	.b3 {
		background: var(--aur-3, #8b5cf6);
		top: 38%;
		left: 52%;
		width: 30vw;
		animation: drift-c 38s ease-in-out infinite alternate;
	}

	@keyframes drift-a {
		to {
			transform: translate(14vw, 10vh) scale(1.15);
		}
	}
	@keyframes drift-b {
		to {
			transform: translate(-12vw, -12vh) scale(0.9);
		}
	}
	@keyframes drift-c {
		to {
			transform: translate(-16vw, -6vh) scale(1.2);
		}
	}
</style>
