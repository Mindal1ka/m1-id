<script lang="ts">
	import { ChevronUp, UserRound } from '@lucide/svelte';
	import type { Component } from 'svelte';
	import type { Tab } from '$lib/app/helpers';
	import { pressable, motionOK, ease } from '$lib/motion';

	interface Props {
		tabs: { key: Tab; icon: Component<{ size?: number; strokeWidth?: number }>; label: string }[];
		tab: Tab;
		menuOpen: boolean;
		onopen: (t: Tab) => void;
	}
	let { tabs, tab, menuOpen = $bindable(), onopen }: Props = $props();

	// Єдиний індикатор активного пункту. Під час View Transition він «перетікає»
	// між пунктами (view-transition-name: nav-indicator); без підтримки VT —
	// фолбек: CSS-transition по transform з виміряних offsetTop/offsetHeight.
	// View Transitions для вкладок більше не використовуються (див. motion enterContent) — лише CSS-перехід
	const hasVT = false;
	let navEl = $state<HTMLElement | null>(null);
	let itemEls = $state<Record<string, HTMLElement | undefined>>({});
	let indY = $state(0);
	let indH = $state(0);
	let indReady = $state(false);

	function measure(): void {
		const el = itemEls[tab];
		if (!el || el.offsetHeight === 0) {
			indReady = false;
			return;
		}
		indY = el.offsetTop;
		indH = el.offsetHeight;
		indReady = true;
	}

	$effect(() => {
		// залежності: активна вкладка й набір пунктів
		void tab;
		void tabs.length;
		measure();
	});

	$effect(() => {
		if (!navEl || typeof ResizeObserver === 'undefined') return;
		const ro = new ResizeObserver(() => measure());
		ro.observe(navEl);
		return () => ro.disconnect();
	});

	/** Іконка трохи «зсувається» на hover (лише миша, лише якщо рух дозволено). */
	function nudge(e: PointerEvent, on: boolean): void {
		if (!motionOK() || e.pointerType !== 'mouse') return;
		const ico = (e.currentTarget as HTMLElement).querySelector('svg');
		ico?.animate(
			[{ transform: on ? 'translateX(0)' : 'translateX(2px)' }, { transform: on ? 'translateX(2px)' : 'translateX(0)' }],
			{ duration: 320, easing: ease('spring'), fill: 'forwards' }
		);
	}
</script>

<aside class="side">
	<a class="brand brand-font" href="/landing">M1 ID</a>
	<nav class="side-nav" aria-label="Основна навігація" bind:this={navEl}>
		{#if indReady}
			<span
				class="ind"
				class:vt={hasVT}
				aria-hidden="true"
				style:transform={`translateY(${indY}px)`}
				style:height={`${indH}px`}
			></span>
		{/if}
		{#each tabs as t (t.key)}
			{@const Icon = t.icon}
			<button
				type="button"
				class="item"
				use:pressable={{ scale: 0.97 }}
				bind:this={itemEls[t.key]}
				onpointerenter={(e) => nudge(e, true)}
				onpointerleave={(e) => nudge(e, false)}
				class:active={tab === t.key}
				aria-current={tab === t.key ? 'page' : undefined}
				onclick={() => onopen(t.key)}
			>
				<Icon size={18} strokeWidth={2} />
				<span class="label">{t.label}</span>
			</button>
		{/each}
	</nav>
	<div class="side-foot">
		<button
			type="button"
			class="foot-btn"
			use:pressable={{ scale: 0.97 }}
			class:open={menuOpen}
			aria-haspopup="menu"
			aria-expanded={menuOpen}
			onclick={() => (menuOpen = !menuOpen)}
			title="Профіль і акаунти"
		>
			<span class="avatar" aria-hidden="true"><UserRound size={16} strokeWidth={2} /></span>
			<span class="label">Профіль</span>
			<ChevronUp size={16} strokeWidth={2} class="chev" />
		</button>
	</div>
</aside>

<style>
	.side {
		width: var(--sidebar-w);
		flex-shrink: 0;
		min-height: 0;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		padding: var(--space-4) var(--space-3);
		background: var(--color-surface);
		border-right: 1px solid var(--color-border);
	}

	.brand {
		font-size: var(--text-lg);
		font-weight: var(--weight-bold);
		color: var(--color-text);
		text-decoration: none;
		padding: var(--space-1) var(--space-3);
		border-radius: var(--radius-sm);
		transition: color var(--dur-base) ease;
	}
	.brand:hover {
		color: var(--color-accent-text);
	}

	.side-nav {
		position: relative;
		display: flex;
		flex-direction: column;
		gap: 2px;
		flex: 1;
	}

	.item,
	.foot-btn {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		width: 100%;
		min-height: 38px;
		padding: 0 var(--space-3);
		font: inherit;
		font-size: var(--text-md);
		font-weight: var(--weight-medium);
		color: var(--color-text-muted);
		background: none;
		border: none;
		border-radius: var(--radius-md);
		text-align: left;
		cursor: pointer;
		transition:
			background var(--dur-fast) ease,
			color var(--dur-fast) ease;
	}
	.item :global(svg) {
		flex-shrink: 0;
	}

	.item:hover,
	.foot-btn:hover,
	.foot-btn.open {
		background: var(--color-hover);
		color: var(--color-text);
	}

	.item {
		position: relative;
		z-index: 1;
	}
	.item.active,
	.item.active:hover {
		background: transparent;
		color: var(--color-accent-text);
	}

	/* ковзний індикатор: лише transform; висота виставлена інлайном (статично) */
	.ind {
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
		z-index: 0;
		border-radius: var(--radius-md);
		background: var(--color-accent-soft);
		pointer-events: none;
		transition: transform 420ms var(--ease-spring);
	}
	.ind::before {
		content: '';
		position: absolute;
		left: 0;
		top: 25%;
		bottom: 25%;
		width: 3px;
		border-radius: 0 3px 3px 0;
		background: var(--color-accent);
	}
	/* з VT анімацію веде браузер — власний transition вимикаємо */
	.ind.vt {
		view-transition-name: nav-indicator;
		transition: none;
	}
	:global(html[data-anim='off']) .ind {
		transition: none;
	}
	.item.active :global(svg) {
		color: var(--color-accent);
	}

	.side-foot {
		padding-top: var(--space-3);
		border-top: 1px solid var(--color-border);
	}

	.foot-btn {
		min-height: 44px;
	}

	.avatar {
		display: grid;
		place-items: center;
		width: 28px;
		height: 28px;
		flex-shrink: 0;
		border-radius: var(--radius-full);
		background: var(--color-accent-soft);
		color: var(--color-accent-text);
	}

	.label {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.foot-btn :global(.chev) {
		margin-left: auto;
		color: var(--color-text-subtle);
		transition: transform var(--dur-base) ease;
	}
	.foot-btn.open :global(.chev) {
		transform: rotate(180deg);
	}

	@media (max-width: 900px) {
		.side {
			display: none;
		}
	}
</style>
