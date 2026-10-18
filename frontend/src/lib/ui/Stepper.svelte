<script lang="ts">
	import { Minus, Plus } from '@lucide/svelte';
	import type { TransitionConfig } from 'svelte/transition';
	import { cubicOut } from 'svelte/easing';
	import { motionOK, pressable } from '$lib/motion';

	interface Props {
		value?: number;
		min?: number;
		max?: number;
		step?: number;
		disabled?: boolean;
		onchange?: (value: number) => void;
		class?: string;
	}

	let {
		value = $bindable(0),
		min = -Infinity,
		max = Infinity,
		step = 1,
		disabled = false,
		onchange,
		class: klass = ''
	}: Props = $props();

	// напрямок зміни значення: +1 — вгору (число «їде» вгору), -1 — вниз
	let dir = $state(1);
	let prevV = value;
	$effect.pre(() => {
		const v = value;
		if (v !== prevV) dir = v > prevV ? 1 : -1;
		prevV = v;
	});

	/** Рулетка: старе число виїжджає, нове заїжджає з протилежного боку. */
	function roll(_node: Element, { d, leaving = false }: { d: number; leaving?: boolean }): TransitionConfig {
		if (!motionOK()) return { duration: 0 };
		return {
			duration: 280,
			easing: cubicOut,
			css: (t, u) =>
				`opacity:${t};filter:blur(${u * 2}px);transform:translateY(${(leaving ? -d : d) * u * 70}%)`
		};
	}

	function set(v: number) {
		// прибираємо float-хвости (0.1 + 0.2)
		const n = Math.min(max, Math.max(min, Math.round(v * 1e6) / 1e6));
		if (n === value) return;
		value = n;
		onchange?.(n);
	}

	function onkeydown(e: KeyboardEvent) {
		if (disabled) return;
		if (e.key === 'ArrowUp') {
			e.preventDefault();
			set(value + step);
		} else if (e.key === 'ArrowDown') {
			e.preventDefault();
			set(value - step);
		}
	}
</script>

<div class="st {klass}" class:disabled role="group">
	<button
		type="button"
		class="b"
		aria-label="Зменшити"
		disabled={disabled || value <= min}
		onclick={() => set(value - step)}
		use:pressable={{ scale: 0.86 }}
	>
		<Minus size={16} />
	</button>
	<span
		class="val"
		role="spinbutton"
		tabindex={disabled ? -1 : 0}
		aria-valuenow={value}
		aria-valuemin={Number.isFinite(min) ? min : undefined}
		aria-valuemax={Number.isFinite(max) ? max : undefined}
		aria-disabled={disabled || undefined}
		{onkeydown}
	>
		{#key value}
			<span class="num" in:roll={{ d: dir }} out:roll={{ d: dir, leaving: true }}>{value}</span>
		{/key}
	</span>
	<button
		type="button"
		class="b"
		aria-label="Збільшити"
		disabled={disabled || value >= max}
		onclick={() => set(value + step)}
		use:pressable={{ scale: 0.86 }}
	>
		<Plus size={16} />
	</button>
</div>

<style>
	.st {
		display: inline-flex;
		align-items: center;
		height: var(--control-h-md);
		background: var(--color-surface-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		overflow: hidden;
	}
	.st.disabled {
		opacity: 0.55;
	}
	.b {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: var(--control-h-md);
		height: 100%;
		color: var(--color-text);
		background: transparent;
		border: 0;
		cursor: pointer;
		transition: background var(--dur-fast) ease;
	}
	.b:hover:not(:disabled) {
		background: var(--color-hover);
	}
	.b:active:not(:disabled) {
		background: var(--color-pressed);
	}
	.b:disabled {
		opacity: 0.35;
		cursor: not-allowed;
	}
	.val {
		display: inline-grid;
		place-items: center;
		align-self: stretch;
		overflow: hidden;
		min-width: 48px;
		padding: 0 var(--space-2);
		font-size: var(--text-md);
		font-weight: var(--weight-semibold);
		text-align: center;
		color: var(--color-text);
		outline: 0;
	}
	/* старе й нове число стоять в одній комірці, поки йде перехід */
	.num {
		grid-area: 1 / 1;
		font-variant-numeric: tabular-nums;
	}
	.val:focus-visible,
	.b:focus-visible {
		outline: 2px solid var(--color-accent);
		outline-offset: -2px;
		border-radius: var(--radius-sm);
	}
</style>
