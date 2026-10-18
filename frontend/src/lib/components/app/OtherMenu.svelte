<script lang="ts">
	import { fade } from 'svelte/transition';
	import { tick } from 'svelte';
	import type { Tab } from '$lib/app/helpers';
	import type { Component } from 'svelte';
	import type { TransitionConfig } from 'svelte/transition';
	import { backOut, cubicOut } from 'svelte/easing';
	import { springIn, pressable, stagger, motionOK, ease } from '$lib/motion';

	interface Props {
		otherOpen: boolean;
		tab: Tab;
		tabs: { key: Tab; icon: Component<{ size?: number; strokeWidth?: number }>; label: string }[];
		onopen: (t: Tab) => void;
	}
	let { otherOpen = $bindable(), tab, tabs, onopen }: Props = $props();

	let menuEl = $state<HTMLElement | null>(null);
	let trigger: HTMLElement | null = null;

	// Запам'ятовуємо тригер при відкритті, повертаємо фокус при закритті.
	$effect(() => {
		if (otherOpen) {
			trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
			void tick().then(() => items()[0]?.focus());
		} else if (trigger) {
			if (trigger.isConnected) trigger.focus();
			trigger = null;
		}
	});

	// Перехід на іншу вкладку (у т.ч. через нижню панель) закриває меню.
	let prevTab: Tab | null = null;
	$effect(() => {
		const t = tab;
		if (prevTab !== null && prevTab !== t && otherOpen) otherOpen = false;
		prevTab = t;
	});

	// Esc закриває меню з будь-якого місця, навіть якщо фокус поза ним.
	function onwindowkey(e: KeyboardEvent): void {
		if (otherOpen && e.key === 'Escape' && !menuEl?.contains(e.target as Node)) {
			e.preventDefault();
			otherOpen = false;
		}
	}

	const isMobile = (): boolean =>
		typeof window !== 'undefined' && window.matchMedia('(max-width: 900px)').matches;

	/** Закрито свайпом: сам виїзд уже програно WAAPI, out-перехід миттєвий. */
	let dragClosed = false;
	$effect(() => {
		if (otherOpen) dragClosed = false;
	});

	/** Мобільний шит: виїзд знизу (пружина; щілину від перельоту закриває ::after). */
	function sheet(_n: Element, out: boolean): TransitionConfig {
		if (!motionOK() || (out && dragClosed)) return { duration: 0 };
		return {
			duration: out ? 240 : 480,
			easing: out ? cubicOut : backOut,
			css: (t, u) => `transform:translateY(${u * 100}%);opacity:${Math.min(1, t * 3)}`
		};
	}
	function menuIn(node: Element): TransitionConfig {
		return isMobile() ? sheet(node, false) : springIn(node, { duration: 360, start: 0.94, y: 8 });
	}
	function menuOut(node: Element): TransitionConfig {
		return isMobile() ? sheet(node, true) : springIn(node, { duration: 160, start: 0.96, y: 4 });
	}

	// Проста версія drag-down-to-close: тягнемо шит за «ручку»/заголовок.
	let dragY = 0;
	let dragStart = 0;
	let dragT = 0;
	let dragging = false;
	function dragDown(e: PointerEvent): void {
		if (!isMobile() || !motionOK() || !menuEl) return;
		dragging = true;
		dragStart = e.clientY;
		dragT = e.timeStamp;
		dragY = 0;
		(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
		menuEl.style.transition = 'none';
	}
	function dragMove(e: PointerEvent): void {
		if (!dragging || !menuEl) return;
		const dy = e.clientY - dragStart;
		// вгору — з опором (гумка), вниз — вільно
		dragY = dy > 0 ? dy : dy * 0.18;
		menuEl.style.transform = `translateY(${dragY}px)`;
	}
	function dragUp(e: PointerEvent): void {
		if (!dragging || !menuEl) return;
		dragging = false;
		const v = dragY / Math.max(1, e.timeStamp - dragT); // px/мс
		const el = menuEl;
		// скасований жест (pointercancel) ніколи не закриває — лише повертає шит на місце
		if (e.type !== 'pointercancel' && (dragY > 90 || v > 0.6)) {
			dragClosed = true;
			const a = el.animate(
				[{ transform: `translateY(${dragY}px)` }, { transform: 'translateY(110%)' }],
				{ duration: 220, easing: 'cubic-bezier(0.22, 1, 0.36, 1)', fill: 'forwards' }
			);
			a.onfinish = () => (otherOpen = false);
		} else if (dragY === 0) {
			el.style.transform = '';
		} else {
			el.style.transform = '';
			el.animate([{ transform: `translateY(${dragY}px)` }, { transform: 'translateY(0)' }], {
				duration: 420,
				easing: ease('spring')
			});
		}
	}

	function items(): HTMLElement[] {
		return menuEl ? Array.from(menuEl.querySelectorAll<HTMLElement>('[role="menuitem"]')) : [];
	}

	function onkeydown(e: KeyboardEvent): void {
		const list = items();
		const i = list.indexOf(document.activeElement as HTMLElement);
		let next = -1;
		if (e.key === 'ArrowDown' || e.key === 'ArrowRight') next = (i + 1) % list.length;
		else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') next = (i - 1 + list.length) % list.length;
		else if (e.key === 'Home') next = 0;
		else if (e.key === 'End') next = list.length - 1;
		else if (e.key === 'Escape') {
			e.preventDefault();
			e.stopPropagation();
			otherOpen = false;
			return;
		} else if (e.key === 'Tab') {
			e.preventDefault();
			otherOpen = false;
			return;
		}
		if (next >= 0) {
			e.preventDefault();
			list[next]?.focus();
		}
	}
</script>

<svelte:window onkeydown={onwindowkey} />

{#if otherOpen}
	<button
		type="button"
		class="scrim"
		aria-label="Закрити меню"
		tabindex="-1"
		onclick={() => (otherOpen = false)}
		transition:fade={{ duration: 130 }}
	></button>
	<div
		class="other-menu"
		role="menu"
		aria-label="Інші розділи"
		tabindex="-1"
		bind:this={menuEl}
		{onkeydown}
		in:menuIn
		out:menuOut
	>
		<div
			class="om-drag"
			onpointerdown={dragDown}
			onpointermove={dragMove}
			onpointerup={dragUp}
			onpointercancel={dragUp}
		>
			<span class="grip" aria-hidden="true"></span>
			<div class="om-head">Інші розділи</div>
		</div>
		<div class="om-grid" use:stagger={{ step: 28, y: 10, scale: true, max: 10 }}>
			{#each tabs as t (t.key)}
				{@const Icon = t.icon}
				<button
					type="button"
					class="om-item"
					use:pressable={{ scale: 0.94 }}
					class:active={tab === t.key}
					role="menuitem"
					tabindex="-1"
					aria-current={tab === t.key ? 'page' : undefined}
					onclick={() => {
						otherOpen = false;
						onopen(t.key);
					}}
				>
					<span class="tile-ico"><Icon size={22} strokeWidth={2} /></span>
					<span class="om-label">{t.label}</span>
				</button>
			{/each}
		</div>
	</div>
{/if}

<style>
	.scrim {
		position: fixed;
		inset: 0;
		z-index: var(--z-overlay);
		background: var(--color-overlay);
		border: none;
		cursor: default;
		/* шар перехоплює дотики: ні скролу, ні «проклику» до панелі позаду */
		touch-action: none;
		-webkit-tap-highlight-color: transparent;
	}

	/* десктоп: поповер зі списком */
	.other-menu {
		position: fixed;
		left: calc(var(--sidebar-w) + var(--space-3));
		bottom: var(--space-4);
		z-index: var(--z-popover);
		width: 280px;
		max-height: 70dvh;
		overflow-y: auto;
		padding: var(--space-2);
		background: var(--color-elevated);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		box-shadow: var(--shadow-lg);
		transform-origin: bottom left;
	}

	.om-drag {
		touch-action: none;
	}
	.grip {
		display: none;
	}

	.om-head {
		padding: var(--space-2) var(--space-3);
		font-size: var(--text-xs);
		font-weight: var(--weight-semibold);
		color: var(--color-text-subtle);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.om-grid {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.om-item {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		min-height: 40px;
		padding: 0 var(--space-3);
		font: inherit;
		font-size: var(--text-md);
		font-weight: var(--weight-medium);
		color: var(--color-text);
		background: none;
		border: none;
		border-radius: var(--radius-md);
		text-align: left;
		cursor: pointer;
	}
	/* hover лише для миші: на дотику він «залипає» */
	@media (hover: hover) and (pointer: fine) {
		.om-item:hover {
			background: var(--color-hover);
		}
	}
	.om-item.active {
		background: var(--color-accent-soft);
		color: var(--color-accent-text);
	}
	.tile-ico {
		display: grid;
		place-items: center;
		color: var(--color-text-muted);
	}
	.om-item.active .tile-ico {
		color: var(--color-accent);
	}

	/* мобільний: панель-шит над нижньою навігацією, плитки 3-4 в ряд */
	@media (max-width: 900px) {
		/* Скрім не заходить на нижню панель і не темнить: вона лишається активною,
		   «Ще» закриває меню повторним натиском. Тап поза меню все одно закриває. */
		.scrim {
			bottom: var(--nav-total, 76px);
			background: transparent;
		}
		.other-menu {
			/* плаваюча картка над плаваючою нижньою панеллю */
			left: max(var(--space-3), env(safe-area-inset-left));
			right: max(var(--space-3), env(safe-area-inset-right));
			bottom: calc(var(--nav-total, 76px) + var(--space-2));
			width: auto;
			max-height: calc(100dvh - var(--nav-total, 76px) - var(--space-6));
			overscroll-behavior: contain;
			padding: var(--space-4) var(--space-4) var(--space-4);
			border-radius: var(--radius-xl);
			transform-origin: bottom center;
		}
		/* збільшена зона для свайпу вниз: ручка + заголовок */
		.om-drag {
			margin: calc(-1 * var(--space-4)) calc(-1 * var(--space-4)) 0;
			padding: var(--space-3) var(--space-4) 0;
			cursor: grab;
		}
		.grip {
			display: block;
			width: 40px;
			height: 5px;
			margin: 0 auto var(--space-3);
			border-radius: 4px;
			background: var(--color-border-strong);
		}
		.om-head {
			padding: 0 var(--space-1) var(--space-3);
		}
		.om-grid {
			display: grid;
			grid-template-columns: repeat(4, 1fr);
			gap: var(--space-2);
		}
		.om-item {
			flex-direction: column;
			justify-content: center;
			gap: var(--space-1);
			min-height: 84px;
			padding: var(--space-2) var(--space-1);
			text-align: center;
		}
		.om-item.active {
			box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 30%, transparent);
		}
		.tile-ico {
			width: 44px;
			height: 44px;
			border-radius: var(--radius-md);
			background: var(--color-surface-2);
		}
		.om-item.active .tile-ico {
			background: var(--color-accent-soft);
		}
		.om-label {
			max-width: 100%;
			overflow: hidden;
			text-overflow: ellipsis;
			white-space: nowrap;
			font-size: var(--text-xs);
		}
	}
	@media (max-width: 640px) {
		.om-grid {
			grid-template-columns: repeat(3, 1fr);
		}
	}
	/* вузькі екрани (320px): тісніші плитки, довгі підписи обрізаються */
	@media (max-width: 360px) {
		.other-menu {
			padding: var(--space-3);
		}
		.om-drag {
			margin: calc(-1 * var(--space-3)) calc(-1 * var(--space-3)) 0;
			padding: var(--space-3) var(--space-3) 0;
		}
		.om-grid {
			gap: var(--space-1);
		}
	}
</style>
