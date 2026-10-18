<script module lang="ts">
	// Спільний стан усіх діалогів: лічильник блокувань скролу та стек (для Esc і приглушення).
	let scrollLocks = 0;
	let savedOverflow = '';
	let savedPaddingRight = '';
	let uid = 0;
	/** Реактивний стек відкритих діалогів: нижні приглушуються, коли зверху відкрито інший. */
	const nest = $state<{ ids: number[] }>({ ids: [] });

	function lockScroll(): void {
		if (scrollLocks++ > 0) return;
		const b = document.body;
		savedOverflow = b.style.overflow;
		savedPaddingRight = b.style.paddingRight;
		const sw = window.innerWidth - document.documentElement.clientWidth;
		b.style.overflow = 'hidden';
		if (sw > 0) b.style.paddingRight = `${sw}px`;
	}

	function unlockScroll(): void {
		if (scrollLocks === 0 || --scrollLocks > 0) return;
		document.body.style.overflow = savedOverflow;
		document.body.style.paddingRight = savedPaddingRight;
	}

	// Остання точка натискання: діалог "виростає" з місця, куди клікнули.
	let lastDown: { x: number; y: number; t: number } | null = null;
	if (typeof window !== 'undefined') {
		window.addEventListener(
			'pointerdown',
			(e) => {
				lastDown = { x: e.clientX, y: e.clientY, t: performance.now() };
			},
			{ capture: true, passive: true }
		);
	}

	/** Пружинний easing (затухаючі коливання) для JS-переходів Svelte. */
	function springEase(zeta: number, omega: number): (t: number) => number {
		const wd = omega * Math.sqrt(1 - zeta * zeta);
		return (t) =>
			t <= 0
				? 0
				: t >= 1
					? 1
					: 1 - Math.exp(-zeta * omega * t) * (Math.cos(wd * t) + ((zeta * omega) / wd) * Math.sin(wd * t));
	}
	// desktop: легкий переліт; sheet: критичне демпфування (без щілини знизу)
	const springDesktop = springEase(0.6, 14);
	const springSheet = (t: number): number => (t <= 0 ? 0 : t >= 1 ? 1 : 1 - Math.exp(-11 * t) * (1 + 11 * t));
</script>

<script lang="ts">
	import { X } from '@lucide/svelte';
	import type { Snippet } from 'svelte';
	import { untrack } from 'svelte';
	import { cubicOut } from 'svelte/easing';
	import type { TransitionConfig } from 'svelte/transition';
	import { focusTrap, inertBackground } from '$lib/actions/focusTrap';
	import { portal } from '$lib/actions/portal';
	import { ease, motionOK } from '$lib/motion';

	interface Props {
		open?: boolean;
		title?: string;
		description?: string;
		size?: 'sm' | 'md' | 'lg' | 'full';
		dismissible?: boolean;
		onclose?: () => void;
		/** Повністю замінює шапку (заголовок + опис). */
		header?: Snippet;
		footer?: Snippet;
		children?: Snippet;
	}

	let {
		open = $bindable(false),
		title = '',
		description = '',
		size = 'md',
		dismissible = true,
		onclose,
		header,
		footer,
		children
	}: Props = $props();

	const id = ++uid;
	const titleId = `dlg-title-${id}`;
	const descId = `dlg-desc-${id}`;
	const SIZES = { sm: '400px', md: '560px', lg: '760px', full: '100%' } as const;

	const mobileMq = '(max-width: 640px)';
	const isMobile = (): boolean => typeof window !== 'undefined' && window.matchMedia(mobileMq).matches;

	let panelEl = $state<HTMLElement | null>(null);
	let scrimEl = $state<HTMLElement | null>(null);

	// діалог накрито іншим, що відкрився зверху
	const covered = $derived(nest.ids.includes(id) && nest.ids[nest.ids.length - 1] !== id);

	function close(): void {
		if (!open) return;
		open = false;
		onclose?.();
	}

	// ---- блокування скролу + стек діалогів ----
	$effect(() => {
		if (!open) return;
		dragOffset = 0;
		exitVelocity = 0;
		lockScroll();
		untrack(() => (nest.ids = [...nest.ids, id]));
		return () => {
			untrack(() => (nest.ids = nest.ids.filter((x) => x !== id)));
			unlockScroll();
		};
	});

	function onKeydown(e: KeyboardEvent): void {
		if (!open || e.key !== 'Escape' || e.defaultPrevented) return;
		if (nest.ids[nest.ids.length - 1] !== id || !dismissible) return;
		e.preventDefault();
		close();
	}

	// ---- клік по overlay (лише якщо і натиснули, і відпустили на ньому) ----
	let downOnBackdrop = false;
	function onRootPointerDown(e: PointerEvent): void {
		downOnBackdrop = e.target === e.currentTarget;
	}
	function onRootClick(e: MouseEvent): void {
		if (dismissible && downOnBackdrop && e.target === e.currentTarget) close();
		downOnBackdrop = false;
	}

	// ---- перетягування sheet за ручку/шапку (лише мобільний) ----
	const CLOSE_FRACTION = 0.3; // закрити, якщо зсув > 30% висоти
	const CLOSE_VELOCITY = 0.6; // або швидкість > 0.6 px/ms
	let dragging = $state(false);
	let dragOffset = 0; // поточний зсув панелі, px (від'ємний = опір вгору)
	let exitVelocity = 0; // швидкість кидка, px/ms (для тривалості виходу)
	let startY = 0;
	let samples: { t: number; y: number }[] = [];
	let springBack: Animation | null = null;

	/** Опір при тязі вгору (як у iOS): чим далі, тим важче. */
	function rubber(d: number): number {
		const dim = 140;
		return (1 - 1 / ((d * 0.55) / dim + 1)) * dim;
	}

	function onGrabDown(e: PointerEvent): void {
		if (!dismissible || !isMobile()) return;
		if ((e.target as HTMLElement).closest('button, a, input, textarea, select')) return;
		springBack?.cancel();
		springBack = null;
		startY = e.clientY;
		samples = [{ t: e.timeStamp, y: e.clientY }];
		dragging = true;
		(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
	}

	function onGrabMove(e: PointerEvent): void {
		if (!dragging || !panelEl) return;
		const dy = e.clientY - startY;
		dragOffset = dy >= 0 ? dy : -rubber(-dy);
		panelEl.style.transform = `translateY(${dragOffset}px)`;
		if (scrimEl) {
			const p = Math.min(1, Math.max(0, dragOffset) / (panelEl.offsetHeight || 1));
			scrimEl.style.opacity = String(1 - p);
		}
		samples.push({ t: e.timeStamp, y: e.clientY });
		while (samples.length > 2 && e.timeStamp - samples[0].t > 100) samples.shift();
	}

	function onGrabEnd(e: PointerEvent): void {
		if (!dragging || !panelEl) return;
		dragging = false;
		const first = samples[0];
		const dt = e.timeStamp - first.t;
		const v = dt > 0 ? (e.clientY - first.y) / dt : 0;
		const h = panelEl.offsetHeight || 1;
		const shouldClose =
			e.type !== 'pointercancel' && (dragOffset > h * CLOSE_FRACTION || (v > CLOSE_VELOCITY && dragOffset > 8));
		if (shouldClose) {
			exitVelocity = Math.max(0, v);
			close(); // вихід продовжить рух із поточного зсуву (див. panelOut)
			return;
		}
		// повернення на місце пружиною
		const from = dragOffset;
		const scrimFrom = scrimEl?.style.opacity ? Number(scrimEl.style.opacity) : 1;
		panelEl.style.transform = '';
		if (scrimEl) scrimEl.style.opacity = '';
		dragOffset = 0;
		if (motionOK() && from !== 0) {
			springBack = panelEl.animate([{ transform: `translateY(${from}px)` }, { transform: 'translateY(0)' }], {
				duration: 520,
				easing: ease('spring')
			});
			scrimEl?.animate([{ opacity: scrimFrom }, { opacity: 1 }], { duration: 300, easing: ease('out') });
		}
	}

	// ---- анімації ----
	/** Точка натискання -> transform-origin панелі (якщо відкрито кліком щойно). */
	function applyOrigin(node: HTMLElement): void {
		node.style.transformOrigin = '';
		if (!lastDown || performance.now() - lastDown.t > 1200) return;
		const r = node.getBoundingClientRect();
		const x = Math.min(Math.max(lastDown.x - r.left, 0), r.width);
		const y = Math.min(Math.max(lastDown.y - r.top, -40), r.height + 40);
		node.style.transformOrigin = `${x}px ${y}px`;
	}

	function panelIn(node: Element): TransitionConfig {
		if (!motionOK()) return { duration: 0 };
		if (isMobile()) {
			return {
				duration: 520,
				easing: springSheet,
				css: (_t, u) => `transform: translateY(${u * 100}%)`
			};
		}
		applyOrigin(node as HTMLElement);
		return {
			duration: 460,
			easing: springDesktop,
			css: (t, u) => `opacity: ${Math.min(1, t * 2.4)}; transform: translateY(${u * 8}px) scale(${0.94 + 0.06 * t})`
		};
	}

	function panelOut(node: Element): TransitionConfig {
		if (!motionOK()) return { duration: 0 };
		if (isMobile()) {
			// продовжуємо рух із місця, де відпустили палець
			const off = dragOffset;
			const el = node as HTMLElement;
			const rest = Math.max(1, (el.offsetHeight || 400) - off);
			const duration = exitVelocity > 0 ? Math.min(300, Math.max(160, rest / Math.max(exitVelocity, 0.9))) : 260;
			return {
				duration,
				easing: cubicOut,
				css: (_t, u) => `transform: translateY(calc(${off}px + ${u} * (100% - ${off}px)))`
			};
		}
		return {
			duration: 180,
			easing: cubicOut,
			css: (t, u) => `opacity: ${t}; transform: scale(${1 - 0.03 * u})`
		};
	}

	// Радіус розмиття НЕ анімується покадрово: scrim має статичний backdrop-filter,
	// а переходи змінюють лише opacity (дешево для композитора).
	function scrimIn(_node: Element): TransitionConfig {
		if (!motionOK()) return { duration: 0 };
		return { duration: 320, easing: cubicOut, css: (t) => `opacity: ${t}` };
	}

	function scrimOut(node: Element): TransitionConfig {
		if (!motionOK()) return { duration: 0 };
		const cur = Number.parseFloat(getComputedStyle(node).opacity) || 1;
		return {
			duration: 200,
			easing: cubicOut,
			css: (t) => `opacity: ${t * cur}`
		};
	}
</script>

<svelte:window onkeydown={onKeydown} />

{#if open}
	<div
		class="root"
		use:portal
		use:inertBackground
		onpointerdown={onRootPointerDown}
		onclick={onRootClick}
		role="presentation"
	>
		<div class="scrim" bind:this={scrimEl} in:scrimIn out:scrimOut aria-hidden="true"></div>
		<div
			class="panel"
			class:full={size === 'full'}
			class:dragging
			class:covered
			style:--w={SIZES[size]}
			bind:this={panelEl}
			use:focusTrap
			in:panelIn
			out:panelOut
			role="dialog"
			aria-modal="true"
			aria-labelledby={title ? titleId : undefined}
			aria-label={title ? undefined : 'Вікно'}
			aria-describedby={description ? descId : undefined}
		>
			<div
				class="head"
				onpointerdown={onGrabDown}
				onpointermove={onGrabMove}
				onpointerup={onGrabEnd}
				onpointercancel={onGrabEnd}
				role="presentation"
			>
				<span class="handle" aria-hidden="true"></span>
				{#if header}
					<div class="custom-head">{@render header()}</div>
				{:else if title || description}
					<div class="titlebar">
						{#if title}<h2 id={titleId}>{title}</h2>{/if}
						{#if description}<p id={descId}>{description}</p>{/if}
					</div>
				{/if}
				{#if dismissible}
					<button type="button" class="close" onclick={close} aria-label="Закрити">
						<X size={20} aria-hidden="true" />
					</button>
				{/if}
			</div>

			<div class="body">
				{#if header && description}<p id={descId} class="sr-only">{description}</p>{/if}
				{@render children?.()}
			</div>

			{#if footer}
				<div class="foot">{@render footer()}</div>
			{/if}
		</div>
	</div>
{/if}

<style>
	.root {
		position: fixed;
		inset: 0;
		z-index: var(--z-modal);
		display: flex;
		align-items: center;
		justify-content: center;
		padding: var(--space-6);
	}

	/* затемнення + розмиття фону; наростають через transition і тягнуться за пальцем */
	.scrim {
		position: absolute;
		inset: 0;
		background: var(--color-overlay);
		-webkit-backdrop-filter: blur(calc(6px + 0px));
		backdrop-filter: blur(calc(6px + 0px));
		pointer-events: none;
	}

	/* lite: без backdrop-filter — темніший суцільний scrim */
	:global(html[data-perf='lite']) .scrim {
		-webkit-backdrop-filter: none;
		backdrop-filter: none;
		background: color-mix(in srgb, var(--color-overlay) 82%, black);
	}

	.panel {
		position: relative;
		display: flex;
		flex-direction: column;
		width: 100%;
		max-width: var(--w);
		max-height: min(88dvh, 100%);
		overflow: hidden;
		outline: none;
		color: var(--color-text);
		background: var(--color-elevated);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-xl);
		box-shadow: var(--shadow-lg);
		/* окрема властивість scale: не конфліктує з transform-анімаціями входу/перетягування */
		transition:
			scale 420ms var(--ease-spring),
			filter 320ms var(--ease-out);
	}

	/* поверх відкрито інший діалог: цей трохи відступає й темнішає */
	.panel.covered {
		scale: 0.98;
		filter: brightness(0.9);
	}

	/* lite: без filter на великій панелі */
	:global(html[data-perf='lite']) .panel {
		transition: scale 420ms var(--ease-spring);
	}
	:global(html[data-perf='lite']) .panel.covered {
		filter: none;
	}

	:global(html[data-anim='off']) .panel {
		transition: none;
	}

	.panel.full {
		height: 100%;
		max-height: 100%;
	}

	.head {
		position: relative;
		flex-shrink: 0;
		z-index: 1;
		background: var(--color-elevated);
	}

	.handle {
		display: none;
	}

	.titlebar,
	.custom-head {
		padding: var(--space-5) var(--space-16) var(--space-3) var(--space-6);
	}

	.titlebar h2 {
		font-size: var(--text-lg);
		font-weight: var(--weight-semibold);
		line-height: var(--leading-tight);
		overflow-wrap: anywhere;
	}

	.titlebar p {
		margin-top: var(--space-1);
		font-size: var(--text-md);
		color: var(--color-text-muted);
	}

	.close {
		position: absolute;
		top: var(--space-3);
		right: var(--space-3);
		display: grid;
		place-items: center;
		width: 36px;
		height: 36px;
		padding: 0;
		color: var(--color-text-muted);
		background: transparent;
		border: none;
		border-radius: var(--radius-md);
		cursor: pointer;
		transition:
			background var(--dur-fast) var(--ease-out),
			color var(--dur-fast) var(--ease-out);
	}

	.close:hover {
		color: var(--color-text);
		background: var(--color-hover);
	}

	.close:active {
		background: var(--color-pressed);
	}

	.body {
		flex: 1 1 auto;
		min-height: 0;
		overflow-y: auto;
		overscroll-behavior: contain;
		padding: var(--space-2) var(--space-6) var(--space-6);
		font-size: var(--text-md);
	}

	.foot {
		flex-shrink: 0;
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: var(--space-2);
		padding: var(--space-4) var(--space-6);
		background: var(--color-elevated);
		border-top: 1px solid var(--color-border);
	}

	@media (max-width: 640px) {
		.root {
			align-items: flex-end;
			padding: 0;
		}

		.panel {
			max-width: none;
			max-height: 92dvh;
			padding-bottom: env(safe-area-inset-bottom, 0px);
			border-bottom: none;
			border-radius: var(--radius-xl) var(--radius-xl) 0 0;
		}

		.panel.full {
			height: 92dvh;
		}

		.head {
			touch-action: none;
		}

		.handle {
			display: block;
			width: 36px;
			height: 4px;
			margin: var(--space-2) auto 0;
			background: var(--color-border-strong);
			border-radius: var(--radius-full);
		}

		.titlebar,
		.custom-head {
			padding: var(--space-3) var(--space-16) var(--space-3) var(--space-4);
		}

		.close {
			top: var(--space-2);
			right: var(--space-2);
			width: 40px;
			height: 40px;
		}

		.body {
			padding: var(--space-2) var(--space-4) var(--space-4);
		}

		.foot {
			flex-direction: column-reverse;
			align-items: stretch;
			padding: var(--space-3) var(--space-4);
		}

		.foot > :global(*) {
			width: 100%;
		}
	}
</style>
