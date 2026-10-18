<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { TransitionConfig } from 'svelte/transition';
	import { portal } from '$lib/actions/portal';
	import { motionOK, springIn, stagger } from '$lib/motion';
	import Dialog from './Dialog.svelte';

	type Placement = 'bottom-start' | 'bottom-end' | 'top-start' | 'top-end' | 'bottom' | 'top';

	interface Props {
		open?: boolean;
		/** Якір ззовні; якщо не задано — береться обгортка snippet `trigger`. */
		anchor?: HTMLElement | null;
		trigger?: Snippet<[{ open: boolean; toggle: () => void }]>;
		placement?: Placement;
		offset?: number;
		role?: string;
		/** Доступна назва панелі (aria-label; на мобільному — заголовок sheet). */
		label?: string;
		/** На <=640px показувати як bottom sheet (Dialog). */
		sheetOnMobile?: boolean;
		onclose?: () => void;
		children?: Snippet;
	}

	let {
		open = $bindable(false),
		anchor = null,
		trigger,
		placement = 'bottom-start',
		offset = 8,
		role = 'dialog',
		label = '',
		sheetOnMobile = false,
		onclose,
		children
	}: Props = $props();

	const MARGIN = 8;

	let triggerEl = $state<HTMLElement | null>(null);
	let panelEl = $state<HTMLElement | null>(null);
	let pos = $state<{ top: number; left: number; side: 'top' | 'bottom' } | null>(null);
	let mobile = $state(false);

	const anchorEl = $derived(anchor ?? triggerEl);
	const asSheet = $derived(sheetOnMobile && mobile);

	$effect(() => {
		const mq = window.matchMedia('(max-width: 640px)');
		mobile = mq.matches;
		const on = (e: MediaQueryListEvent): void => {
			mobile = e.matches;
		};
		mq.addEventListener('change', on);
		return () => mq.removeEventListener('change', on);
	});

	function close(): void {
		if (!open) return;
		open = false;
		onclose?.();
	}

	function toggle(): void {
		if (open) close();
		else open = true;
	}

	/** Позиція fixed від rect якоря: фліп за браком місця + кламп у в'юпорті. */
	function update(): void {
		if (!anchorEl || !panelEl) return;
		const r = anchorEl.getBoundingClientRect();
		const w = panelEl.offsetWidth;
		const h = panelEl.offsetHeight;
		const vw = window.innerWidth;
		const vh = window.innerHeight;

		let side: 'top' | 'bottom' = placement.startsWith('top') ? 'top' : 'bottom';
		const roomBelow = vh - r.bottom - offset - MARGIN;
		const roomAbove = r.top - offset - MARGIN;
		if (side === 'bottom' && h > roomBelow && roomAbove > roomBelow) side = 'top';
		else if (side === 'top' && h > roomAbove && roomBelow > roomAbove) side = 'bottom';

		let left: number;
		if (placement.endsWith('-start')) left = r.left;
		else if (placement.endsWith('-end')) left = r.right - w;
		else left = r.left + r.width / 2 - w / 2;

		let top = side === 'bottom' ? r.bottom + offset : r.top - offset - h;

		left = Math.max(MARGIN, Math.min(left, vw - w - MARGIN));
		top = Math.max(MARGIN, Math.min(top, vh - h - MARGIN));
		pos = { top, left, side };
	}

	/** Точка, з якої «виростає» панель: протилежний бік до напрямку відкриття. */
	const origin = $derived.by(() => {
		const side = pos?.side ?? (placement.startsWith('top') ? 'top' : 'bottom');
		const v = side === 'bottom' ? 'top' : 'bottom';
		const h = placement.endsWith('-start') ? 'left' : placement.endsWith('-end') ? 'right' : 'center';
		return `${h} ${v}`;
	});

	/** Швидке зникнення: fade + легке стискання. */
	function popOut(_node: Element): TransitionConfig {
		if (!motionOK()) return { duration: 0 };
		return {
			duration: 120,
			css: (t, u) => `opacity:${t};transform:scale(${1 - 0.04 * u})`
		};
	}

	/** Для role=menu пункти каскадом (по 25мс) виринають слідом за панеллю. */
	function menuStagger(node: HTMLElement): void {
		if (role !== 'menu') return;
		stagger(node, { step: 25, y: 4, max: 10 });
	}

	// позиціонування, перерахунок на scroll/resize та зміну розміру панелі
	$effect(() => {
		if (!open || asSheet || !panelEl || !anchorEl) {
			pos = null;
			return;
		}
		update();
		const ro = new ResizeObserver(update);
		ro.observe(panelEl);
		window.addEventListener('scroll', update, true);
		window.addEventListener('resize', update);
		return () => {
			ro.disconnect();
			window.removeEventListener('scroll', update, true);
			window.removeEventListener('resize', update);
		};
	});

	// Esc (capture, щоб не закрити заодно батьківський Dialog) і клік поза панеллю
	$effect(() => {
		if (!open || asSheet) return;
		const onKey = (e: KeyboardEvent): void => {
			if (e.key !== 'Escape') return;
			e.stopPropagation();
			e.preventDefault();
			close();
		};
		const onDown = (e: PointerEvent): void => {
			const t = e.target as Node | null;
			if (!t || panelEl?.contains(t) || anchorEl?.contains(t)) return;
			close();
		};
		window.addEventListener('keydown', onKey, true);
		document.addEventListener('pointerdown', onDown, true);
		return () => {
			window.removeEventListener('keydown', onKey, true);
			document.removeEventListener('pointerdown', onDown, true);
		};
	});
</script>

{#if trigger}
	<span class="trigger" bind:this={triggerEl}>{@render trigger({ open, toggle })}</span>
{/if}

{#if asSheet}
	<Dialog bind:open size="sm" title={label} {onclose}>
		{@render children?.()}
	</Dialog>
{:else if open}
	<div
		class="panel"
		bind:this={panelEl}
		use:portal
		use:menuStagger
		{role}
		aria-label={label || undefined}
		style:top="{pos?.top ?? 0}px"
		style:left="{pos?.left ?? 0}px"
		style:visibility={pos ? 'visible' : 'hidden'}
		style:transform-origin={origin}
		in:springIn={{ y: placement.startsWith('top') ? 6 : -6, start: 0.9, duration: 360 }}
		out:popOut
	>
		{@render children?.()}
	</div>
{/if}

<style>
	.trigger {
		display: inline-flex;
	}

	.panel {
		position: fixed;
		z-index: var(--z-popover);
		min-width: 160px;
		max-width: calc(100vw - 16px);
		max-height: calc(100dvh - 16px);
		overflow: auto;
		overscroll-behavior: contain;
		color: var(--color-text);
		font-size: var(--text-md);
		background: var(--color-elevated);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		box-shadow: var(--shadow-lg);
	}
</style>
