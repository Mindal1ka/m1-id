<script lang="ts">
	import type { Snippet } from 'svelte';
	import { portal } from '$lib/actions/portal';

	interface Props {
		/** Текст підказки. */
		label: string;
		placement?: 'top' | 'bottom';
		/** Затримка показу при наведенні, мс. */
		delay?: number;
		children?: Snippet;
	}

	let { label, placement = 'top', delay = 400, children }: Props = $props();

	const MARGIN = 8;
	const GAP = 8;
	const uid = Math.random().toString(36).slice(2, 9);
	const tipId = `tt-${uid}`;

	let wrap = $state<HTMLElement | null>(null);
	let tipEl = $state<HTMLElement | null>(null);
	let visible = $state(false);
	let pos = $state<{ top: number; left: number } | null>(null);
	/** Реальний бік після можливого фліпу — задає напрямок появи. */
	let side = $state<'top' | 'bottom'>('top');
	let timer: ReturnType<typeof setTimeout> | undefined;

	const touchOnly = (): boolean => window.matchMedia('(hover: none)').matches;

	function show(immediate = false): void {
		if (!label || touchOnly()) return;
		clearTimeout(timer);
		if (immediate) visible = true;
		else timer = setTimeout(() => (visible = true), delay);
	}

	function hide(): void {
		clearTimeout(timer);
		visible = false;
	}

	function onPointerEnter(e: PointerEvent): void {
		if (e.pointerType === 'touch') return;
		show();
	}

	function onFocusIn(e: FocusEvent): void {
		// лише клавіатурний фокус
		if ((e.target as HTMLElement).matches(':focus-visible')) show(true);
	}

	function onKeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape' && visible) {
			e.stopPropagation();
			hide();
		}
	}

	function update(): void {
		if (!wrap || !tipEl) return;
		const r = wrap.getBoundingClientRect();
		const w = tipEl.offsetWidth;
		const h = tipEl.offsetHeight;
		let s = placement;
		if (s === 'top' && r.top - GAP - h < MARGIN) s = 'bottom';
		else if (s === 'bottom' && r.bottom + GAP + h > window.innerHeight - MARGIN) s = 'top';
		side = s;
		const top = s === 'top' ? r.top - GAP - h : r.bottom + GAP;
		const left = Math.max(MARGIN, Math.min(r.left + r.width / 2 - w / 2, window.innerWidth - w - MARGIN));
		pos = { top, left };
	}

	// позиція та зв'язок aria-describedby із фокусованим дочірнім елементом
	$effect(() => {
		if (!visible || !tipEl || !wrap) {
			pos = null;
			return;
		}
		update();
		const target = wrap.firstElementChild as HTMLElement | null;
		const prev = target?.getAttribute('aria-describedby') ?? null;
		target?.setAttribute('aria-describedby', prev ? `${prev} ${tipId}` : tipId);
		window.addEventListener('scroll', hide, true);
		window.addEventListener('resize', update);
		return () => {
			if (target) {
				if (prev) target.setAttribute('aria-describedby', prev);
				else target.removeAttribute('aria-describedby');
			}
			window.removeEventListener('scroll', hide, true);
			window.removeEventListener('resize', update);
		};
	});

	$effect(() => () => clearTimeout(timer));
</script>

<span
	class="wrap"
	bind:this={wrap}
	role="presentation"
	onpointerenter={onPointerEnter}
	onpointerleave={hide}
	onpointerdown={hide}
	onfocusin={onFocusIn}
	onfocusout={hide}
	onkeydown={onKeydown}
>
	{@render children?.()}
</span>

{#if visible}
	<div
		class="tip"
		id={tipId}
		role="tooltip"
		bind:this={tipEl}
		use:portal
		style:top="{pos?.top ?? 0}px"
		style:left="{pos?.left ?? 0}px"
		style:visibility={pos ? 'visible' : 'hidden'}
		data-side={side}
	>
		{label}
	</div>
{/if}

<style>
	.wrap {
		display: inline-flex;
	}

	.tip {
		position: fixed;
		z-index: var(--z-popover);
		max-width: min(280px, calc(100vw - 16px));
		padding: var(--space-1) var(--space-2);
		font-size: var(--text-xs);
		font-weight: var(--weight-medium);
		line-height: var(--leading-normal);
		color: var(--color-text);
		background: var(--color-elevated);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		box-shadow: var(--shadow-md);
		pointer-events: none;
		transform-origin: center bottom;
		animation: tt-in 140ms var(--ease-out);
	}

	.tip[data-side='bottom'] {
		transform-origin: center top;
		--ty: -4px;
	}

	/* виїжджає від якоря: знизу вгору для top, зверху вниз для bottom */
	@keyframes tt-in {
		from {
			opacity: 0;
			transform: translateY(var(--ty, 4px)) scale(0.9);
		}
	}

	:global(html[data-anim='off']) .tip {
		animation: none;
	}
</style>
