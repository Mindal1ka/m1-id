<script lang="ts">
	import { gradeTone } from './grade';
	import { pop } from '$lib/motion';

	interface Props {
		value: number | string | null;
		scale?: number;
		size?: 'sm' | 'md' | 'lg';
	}
	let { value, scale = 12, size = 'md' }: Props = $props();

	const tone = $derived(gradeTone(value, scale));
	const text = $derived(value === null || value === undefined || value === '' ? '—' : String(value));

	let el: HTMLSpanElement | undefined = $state();
	let prev: string | undefined;
	// «Пульс» при зміні оцінки після монтування
	$effect(() => {
		const t = text;
		if (prev !== undefined && prev !== t && el) pop(el, 1.22);
		prev = t;
	});
</script>

<span bind:this={el} class="grade {tone} {size}" aria-label={tone === 'none' ? 'Без оцінки' : `Оцінка ${text}`}>{text}</span>

<style>
	.grade {
		--c: var(--color-text-subtle);
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		font-weight: var(--weight-semibold);
		line-height: 1;
		color: var(--c);
		background: color-mix(in srgb, var(--c) 14%, transparent);
		border-radius: var(--radius-sm);
		transition:
			color 280ms ease,
			background 280ms ease;
	}
	.high {
		--c: var(--grade-high);
	}
	.mid {
		--c: var(--grade-mid);
	}
	.low {
		--c: var(--grade-low);
	}
	.sm {
		min-width: 24px;
		height: 24px;
		padding: 0 6px;
		font-size: var(--text-xs);
	}
	.md {
		min-width: 32px;
		height: 32px;
		padding: 0 8px;
		font-size: var(--text-md);
	}
	.lg {
		min-width: 44px;
		height: 44px;
		padding: 0 10px;
		font-size: var(--text-xl);
		border-radius: var(--radius-md);
	}
</style>
