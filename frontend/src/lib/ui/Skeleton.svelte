<script lang="ts">
	interface Props {
		width?: string | number;
		height?: string | number;
		radius?: string;
		lines?: number;
	}
	let { width = '100%', height = 16, radius = 'var(--radius-sm)', lines = 0 }: Props = $props();

	const px = (v: string | number) => (typeof v === 'number' ? `${v}px` : v);
</script>

{#if lines > 0}
	<div class="stack" aria-hidden="true">
		{#each Array(lines) as _, i (i)}
			<span
				class="sk shimmer"
				style:height={px(height)}
				style:border-radius={radius}
				style:width={i === lines - 1 && lines > 1 ? '60%' : px(width)}
			></span>
		{/each}
	</div>
{:else}
	<span
		class="sk shimmer"
		aria-hidden="true"
		style:width={px(width)}
		style:height={px(height)}
		style:border-radius={radius}
	></span>
{/if}

<style>
	.sk {
		display: block;
		max-width: 100%;
		background: var(--color-surface-2);
		/* рядок скелетона без вмісту: браузер може не малювати його поза екраном */
		contain: paint;
	}
	/* lite: замість шимера — проста пульсація opacity; усі скелетони на одній
	   CSS-анімації (спільний таймлайн, без розсинхрону) */
	:global(html[data-perf='lite']) .sk.shimmer::after {
		display: none;
	}
	:global(html[data-perf='lite']) .sk.shimmer {
		animation: sk-pulse 1.6s ease-in-out infinite;
	}
	@keyframes sk-pulse {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0.55;
		}
	}
	:global(html[data-anim='off']) .sk.shimmer {
		animation: none;
	}
	.stack {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
</style>
