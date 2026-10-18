<script lang="ts">
	import type { Component } from 'svelte';
	import { ease, motionOK } from '$lib/motion';

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
		/** Рівна ширина табів на всю ширину контейнера. */
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

	let btns: (HTMLButtonElement | undefined)[] = $state([]);
	let list: HTMLDivElement | undefined = $state();
	let indEl: HTMLSpanElement | undefined = $state();
	let ind = $state({ x: 0, w: 0, ready: false });
	let last: { x: number; w: number } | null = null;

	const activeIdx = $derived(items.findIndex((i) => i.value === value));
	const tabIdx = $derived(
		activeIdx >= 0 && !items[activeIdx].disabled ? activeIdx : items.findIndex((i) => !i.disabled)
	);

	/** Позиціонує підкреслення; animate — «розтягнутий» перелив між табами. */
	function place(animate: boolean) {
		const b = btns[activeIdx];
		if (!b) {
			ind.ready = false;
			last = null;
			return;
		}
		const x = b.offsetLeft;
		const w = b.offsetWidth;
		if (animate && indEl && last && ind.ready && motionOK() && (last.x !== x || last.w !== w)) {
			// проміжний кадр охоплює обидва таби — індикатор тягнеться, потім стискається
			const left = Math.min(last.x, x);
			const right = Math.max(last.x + last.w, x + w);
			indEl.animate(
				[
					{ transform: `translateX(${last.x}px) scaleX(${last.w})` },
					{ transform: `translateX(${left}px) scaleX(${right - left})`, offset: 0.42 },
					{ transform: `translateX(${x}px) scaleX(${w})` }
				],
				{ duration: 520, easing: ease('out') }
			);
		}
		ind.x = x;
		ind.w = w;
		last = { x, w };
		if (!ind.ready) requestAnimationFrame(() => (ind.ready = true));
	}

	$effect(() => {
		void activeIdx;
		void items;
		void size;
		void block;
		place(true);
	});

	$effect(() => {
		if (!list) return;
		const ro = new ResizeObserver(() => place(false));
		ro.observe(list);
		return () => ro.disconnect();
	});

	// активний таб завжди в зоні видимості при горизонтальному скролі
	$effect(() => {
		btns[activeIdx]?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
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
	class="tabs s-{size} {klass}"
	class:block
	role="tablist"
	aria-label={ariaLabel}
	tabindex="-1"
	{onkeydown}
>
	<span
		bind:this={indEl}
		class="ind"
		class:ready={ind.ready}
		style="transform:translateX({ind.x}px) scaleX({ind.w})"
		aria-hidden="true"
	></span>
	{#each items as it, i (it.value)}
		{@const Icon = it.icon}
		<button
			bind:this={btns[i]}
			type="button"
			role="tab"
			class="tab"
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
	.tabs {
		position: relative;
		display: flex;
		gap: var(--space-5);
		max-width: 100%;
		overflow-x: auto;
		scrollbar-width: none;
		border-bottom: 1px solid var(--color-border);
	}
	.tabs::-webkit-scrollbar {
		display: none;
	}
	.tabs.block {
		gap: 0;
	}
	.s-sm {
		--h: 36px;
		font-size: var(--text-sm);
	}
	.s-md {
		--h: 44px;
		font-size: var(--text-md);
	}
	.tab {
		position: relative;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 6px;
		flex-shrink: 0;
		min-height: var(--h);
		padding: 0 var(--space-1);
		font: inherit;
		font-weight: var(--weight-medium);
		white-space: nowrap;
		color: var(--color-text-muted);
		background: transparent;
		border: 0;
		cursor: pointer;
		transition: color var(--dur-fast) ease;
	}
	.block .tab {
		flex: 1 1 0;
	}
	/* підкреслення: 1px-елемент, масштабований у ширину таба (лише transform) */
	.ind {
		position: absolute;
		left: 0;
		bottom: 0;
		width: 1px;
		height: 2px;
		background: var(--color-accent);
		border-radius: 1px;
		transform-origin: 0 50%;
		opacity: 0;
		pointer-events: none;
	}
	.ind.ready {
		opacity: 1;
		transition: opacity 160ms ease;
	}
	.tab:hover:not(:disabled) {
		color: var(--color-text);
	}
	.tab[aria-selected='true'] {
		color: var(--color-text);
	}
	.tab:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
	.tab:focus-visible {
		outline: 2px solid var(--color-accent);
		outline-offset: -2px;
		border-radius: var(--radius-sm);
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
</style>
