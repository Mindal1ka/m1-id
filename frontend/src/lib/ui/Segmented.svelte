<script lang="ts">
	import type { Component } from 'svelte';
	import { pressable } from '$lib/motion';

	interface Item {
		value: string;
		label: string;
		icon?: Component<any>;
		badge?: string | number;
		disabled?: boolean;
	}

	interface Props {
		items: Item[];
		value?: string;
		onchange?: (value: string) => void;
		size?: 'sm' | 'md';
		/** Рівна ширина елементів на всю ширину контейнера. */
		block?: boolean;
		'aria-label'?: string;
		class?: string;
	}

	let {
		items,
		value = $bindable(''),
		onchange,
		size = 'md',
		block = false,
		'aria-label': ariaLabel,
		class: klass = ''
	}: Props = $props();

	let list: HTMLDivElement | undefined = $state();
	let btns: (HTMLButtonElement | undefined)[] = $state([]);
	let ind = $state({ x: 0, w: 0, ready: false });

	const activeIdx = $derived(items.findIndex((i) => i.value === value));
	// roving tabindex: фокусабельний вибраний або перший доступний
	const tabIdx = $derived(
		activeIdx >= 0 && !items[activeIdx].disabled ? activeIdx : items.findIndex((i) => !i.disabled)
	);

	function measure() {
		const b = btns[activeIdx];
		if (!b) {
			ind.ready = false;
			return;
		}
		ind.x = b.offsetLeft;
		ind.w = b.offsetWidth;
		// перше позиціонування — без анімації, transition вмикаємо наступним кадром
		if (!ind.ready) requestAnimationFrame(() => (ind.ready = true));
	}

	$effect(() => {
		void activeIdx;
		void items;
		void size;
		void block;
		measure();
	});

	$effect(() => {
		if (!list) return;
		const ro = new ResizeObserver(measure);
		ro.observe(list);
		return () => ro.disconnect();
	});

	function select(v: string) {
		if (v === value) return;
		value = v;
		onchange?.(v);
	}

	function onkeydown(e: KeyboardEvent) {
		const keys = ['ArrowRight', 'ArrowLeft', 'Home', 'End'];
		if (!keys.includes(e.key)) return;
		const enabled = items.map((it, i) => (it.disabled ? -1 : i)).filter((i) => i >= 0);
		if (!enabled.length) return;
		e.preventDefault();
		const cur = enabled.indexOf(tabIdx);
		let next = cur;
		if (e.key === 'ArrowRight') next = (cur + 1) % enabled.length;
		else if (e.key === 'ArrowLeft') next = (cur - 1 + enabled.length) % enabled.length;
		else if (e.key === 'Home') next = 0;
		else next = enabled.length - 1;
		const idx = enabled[next];
		btns[idx]?.focus();
		select(items[idx].value);
	}
</script>

<div
	bind:this={list}
	class="seg s-{size} {klass}"
	class:block
	role="tablist"
	aria-label={ariaLabel}
	tabindex="-1"
	{onkeydown}
>
	<span
		class="ind"
		class:ready={ind.ready}
		style="width:{ind.w}px;transform:translateX({ind.x}px)"
		aria-hidden="true"
	></span>
	{#each items as it, i (it.value)}
		{@const Icon = it.icon}
		<button
			bind:this={btns[i]}
			type="button"
			role="tab"
			class="item"
			use:pressable={{ scale: 0.95 }}
			aria-selected={it.value === value}
			tabindex={i === tabIdx ? 0 : -1}
			disabled={it.disabled}
			onclick={() => select(it.value)}
		>
			{#if Icon}<Icon size={size === 'sm' ? 14 : 16} />{/if}
			<span class="lbl">{it.label}</span>
			{#if it.badge !== undefined && it.badge !== ''}<span class="badge">{it.badge}</span>{/if}
		</button>
	{/each}
</div>

<style>
	.seg {
		position: relative;
		display: inline-flex;
		gap: 2px;
		padding: 3px;
		max-width: 100%;
		overflow-x: auto;
		scrollbar-width: none;
		background: var(--color-surface-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-full);
	}
	.seg::-webkit-scrollbar {
		display: none;
	}
	.seg.block {
		display: flex;
		width: 100%;
	}
	.s-sm {
		--h: 28px;
		font-size: var(--text-sm);
	}
	.s-md {
		--h: 34px;
		font-size: var(--text-md);
	}
	.ind {
		position: absolute;
		top: 3px;
		bottom: 3px;
		left: 0;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-full);
		box-shadow: var(--shadow-sm);
		opacity: 0;
		pointer-events: none;
	}
	/* пілюля їде пружиною й трохи «розтягується» разом із шириною */
	.ind.ready {
		opacity: 1;
		transition:
			transform 480ms var(--ease-spring),
			width 480ms var(--ease-spring),
			opacity 160ms ease;
	}
	:global(html[data-anim='off']) .ind.ready {
		transition: none;
	}
	.item {
		position: relative;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 6px;
		flex-shrink: 0;
		min-height: var(--h);
		padding: 0 var(--space-4);
		font: inherit;
		font-weight: var(--weight-medium);
		white-space: nowrap;
		color: var(--color-text-muted);
		background: transparent;
		border: 0;
		border-radius: var(--radius-full);
		cursor: pointer;
		transition: color var(--dur-fast) ease;
	}
	.block .item {
		flex: 1 1 0;
	}
	.item:hover:not(:disabled):not([aria-selected='true']) {
		color: var(--color-text);
	}
	.item[aria-selected='true'] {
		color: var(--color-text);
	}
	.item:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
	.item:focus-visible {
		outline: 2px solid var(--color-accent);
		outline-offset: -2px;
		border-radius: var(--radius-full);
	}
	.badge {
		min-width: 18px;
		padding: 0 5px;
		font-size: var(--text-xs);
		line-height: 18px;
		color: var(--color-accent-text);
		background: var(--color-accent-soft);
		border-radius: var(--radius-full);
	}
	@media (max-width: 640px) {
		.s-sm {
			--h: 32px;
		}
		.s-md {
			--h: 38px;
		}
	}
</style>
