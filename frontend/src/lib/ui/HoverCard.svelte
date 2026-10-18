<script lang="ts" generics="T">
	/**
	 * Спільне спливне вікно (hover на десктопі, тап на сенсорних).
	 *
	 * Один екземпляр на сторінку: стан приходить з HoverCardController,
	 * вміст — snippet `content`. Вікно:
	 *  - з'являється пружиною від якоря (opacity + scale 0.96→1 + зсув);
	 *  - зникає плавно: елемент лишається змонтованим до кінця анімації виходу;
	 *  - при переході на інший якір їде до нього (FLIP: transform від старої
	 *    позиції до нової), висота змінюється плавно, вміст — crossfade;
	 *  - стрілка-покажчик переїжджає разом з вікном;
	 *  - Esc / тап поза вікном закривають; без руху при prefers-reduced-motion
	 *    та html[data-anim='off'] (motionOK()).
	 */
	import { tick, untrack, type Snippet } from 'svelte';
	import { X } from '@lucide/svelte';
	import { portal } from '$lib/actions/portal';
	import { EASE, ease, motionOK } from '$lib/motion';
	import type { HoverCardController } from './hoverCardState.svelte';

	interface Props {
		ctl: HoverCardController<T>;
		content: Snippet<[T]>;
		/** Роль вікна: tooltip — лише для читання, dialog — містить дії. */
		role?: (d: T) => 'tooltip' | 'dialog';
		/** aria-label для dialog. */
		label?: (d: T) => string;
	}

	let { ctl, content, role = () => 'tooltip', label }: Props = $props();

	const MARGIN = 8;
	const GAP = 12;
	const uid = `hc-${Math.random().toString(36).slice(2, 9)}`;

	let el = $state<HTMLElement | null>(null);
	let surface = $state<HTMLElement | null>(null);
	let body = $state<HTMLElement | null>(null);
	/** Елемент у DOM (також під час анімації виходу). */
	let mounted = $state(false);
	/** Дані, що зараз намальовані (лишаються до кінця виходу). */
	let shown = $state.raw<T | null>(null);

	let exiting = false;
	let exitAnim: Animation | null = null;
	let shownKey = '';
	let shownAnchor: HTMLElement | null = null;
	let described: HTMLElement | null = null;
	let token = 0;
	let movingTimer: ReturnType<typeof setTimeout> | undefined;

	function clamp(v: number, lo: number, hi: number): number {
		return Math.max(lo, Math.min(v, Math.max(lo, hi)));
	}

	/** Позиція над/під якорем з перевертанням біля країв в'юпорта. */
	function place(): void {
		const a = ctl.anchor;
		if (!el || !a) return;
		const r = a.getBoundingClientRect();
		const vw = document.documentElement.clientWidth;
		const vh = window.innerHeight;
		const w = el.offsetWidth;
		const h = el.offsetHeight;

		let cx = r.left + r.width / 2;
		const px = ctl.px;
		// широкий якір (рядок уроку): стаємо біля курсора, у межах якоря
		if (px != null && r.width > w * 0.6) cx = clamp(px, r.left, r.right);

		const left = clamp(cx - w / 2, MARGIN, vw - w - MARGIN);
		const above = r.top - GAP - MARGIN;
		const below = vh - r.bottom - GAP - MARGIN;
		const side: 'top' | 'bottom' = h > above && below > above ? 'bottom' : 'top';
		const rawTop = side === 'top' ? r.top - GAP - h : r.bottom + GAP;
		const top = clamp(rawTop, MARGIN, vh - h - MARGIN);
		const ax = clamp(cx - left, 20, w - 20);

		el.style.left = `${left}px`;
		el.style.top = `${top}px`;
		el.style.setProperty('--ax', `${ax}px`);
		el.style.setProperty('--hc-ease', ease('spring'));
		el.style.transformOrigin = `${ax}px ${side === 'top' ? '100%' : '0'}`;
		el.dataset.side = side;
	}

	function sideOf(): 'top' | 'bottom' {
		return el?.dataset.side === 'bottom' ? 'bottom' : 'top';
	}

	function enterAnim(fromOpacity = 0): void {
		if (!el || !motionOK()) return;
		const dy = sideOf() === 'top' ? 8 : -8;
		el.animate(
			[
				{ opacity: fromOpacity, transform: `translateY(${dy}px) scale(0.96)` },
				{ opacity: 1, transform: 'translateY(0) scale(1)' }
			],
			{ duration: 380, easing: ease('spring') }
		);
	}

	function describe(a: HTMLElement | null, d: T | null): void {
		if (described) described.removeAttribute('aria-describedby');
		described = null;
		if (a && d != null && role(d) === 'tooltip') {
			a.setAttribute('aria-describedby', uid);
			described = a;
		}
	}

	function unmount(): void {
		exiting = false;
		exitAnim = null;
		mounted = false;
		shown = null;
		shownAnchor = null;
		shownKey = '';
		describe(null, null);
	}

	function hideCard(): void {
		if (!mounted || exiting) return;
		if (!el || !motionOK()) {
			unmount();
			return;
		}
		exiting = true;
		el.dataset.exiting = '';
		const cs = getComputedStyle(el);
		const fromO = cs.opacity;
		const fromT = cs.transform;
		for (const a of el.getAnimations()) a.cancel();
		const dy = sideOf() === 'top' ? 4 : -4;
		const anim = el.animate(
			[
				{ opacity: fromO, transform: fromT },
				{ opacity: 0, transform: `translateY(${dy}px) scale(0.97)` }
			],
			{ duration: 170, easing: EASE.out, fill: 'forwards' }
		);
		exitAnim = anim;
		anim.finished
			.then(() => {
				if (exitAnim === anim) unmount();
			})
			.catch(() => {
				/* скасовано повторним відкриттям */
			});
	}

	/** Плавний переїзд до іншого якоря: FLIP-позиція, висота, crossfade вмісту. */
	async function moveCard(my: number): Promise<void> {
		if (!el || !surface || !body) return;
		const animate = motionOK();
		const from = el.getBoundingClientRect();
		const oldH = surface.offsetHeight;
		let ghost: HTMLElement | null = null;
		if (animate) {
			ghost = body.cloneNode(true) as HTMLElement;
			ghost.classList.add('hc-ghost');
			ghost.setAttribute('aria-hidden', 'true');
			surface.appendChild(ghost);
		}
		for (const a of el.getAnimations()) a.cancel();
		// стрілка анімується лише під час переїзду, не при першому показі
		el.dataset.moving = '';
		clearTimeout(movingTimer);
		movingTimer = setTimeout(() => el && delete el.dataset.moving, 520);

		shown = ctl.data;
		shownKey = ctl.key;
		shownAnchor = ctl.anchor;
		describe(ctl.anchor, ctl.data);
		await tick();
		if (my !== token || !el || !surface || !body) {
			ghost?.remove();
			return;
		}
		place();
		if (!animate) return;

		const to = el.getBoundingClientRect();
		const dx = from.left - to.left;
		const dy = from.top - to.top;
		if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) {
			el.animate(
				[{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'translate(0, 0)' }],
				{ duration: 460, easing: ease('spring') }
			);
		}
		const newH = surface.offsetHeight;
		if (Math.abs(newH - oldH) > 1) {
			surface.animate([{ height: `${oldH}px` }, { height: `${newH}px` }], {
				duration: 320,
				easing: EASE.out
			});
		}
		body.animate(
			[
				{ opacity: 0, transform: 'translateY(4px)' },
				{ opacity: 1, transform: 'translateY(0)' }
			],
			{ duration: 220, delay: 50, easing: EASE.out, fill: 'backwards' }
		);
		if (ghost) {
			const g = ghost;
			g.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 140, easing: 'linear' }).finished
				.then(() => g.remove())
				.catch(() => g.remove());
		}
	}

	async function sync(open: boolean, key: string, anchor: HTMLElement | null): Promise<void> {
		const my = ++token;
		if (!open || !anchor) {
			hideCard();
			return;
		}
		if (!mounted) {
			shown = ctl.data;
			shownKey = key;
			shownAnchor = anchor;
			mounted = true;
			await tick();
			if (my !== token) return;
			place();
			describe(anchor, ctl.data);
			enterAnim();
			return;
		}
		if (exiting) {
			// повернули курсор під час виходу — «воскрешаємо» вікно
			const startO = el ? Number(getComputedStyle(el).opacity) : 0;
			exitAnim?.cancel();
			exitAnim = null;
			exiting = false;
			if (el) delete el.dataset.exiting;
			shown = ctl.data;
			shownKey = key;
			shownAnchor = anchor;
			await tick();
			if (my !== token) return;
			place();
			describe(anchor, ctl.data);
			enterAnim(Number.isFinite(startO) ? startO : 0);
			return;
		}
		if (key === shownKey && anchor === shownAnchor) return;
		await moveCard(my);
	}

	$effect(() => {
		const open = ctl.isOpen;
		const key = ctl.key;
		const anchor = ctl.anchor;
		untrack(() => void sync(open, key, anchor));
	});

	// слідкуємо за якорем: скрол / ресайз / зникнення з DOM
	let raf = 0;
	function reposition(): void {
		if (raf) return;
		raf = requestAnimationFrame(() => {
			raf = 0;
			if (!mounted || exiting || !el) return;
			const a = ctl.anchor;
			if (!a || !a.isConnected) {
				ctl.close();
				return;
			}
			const r = a.getBoundingClientRect();
			if (r.bottom < 0 || r.top > window.innerHeight || r.right < 0 || r.left > window.innerWidth) {
				ctl.close();
				return;
			}
			place();
		});
	}

	$effect(() => {
		if (!mounted) return;
		window.addEventListener('scroll', reposition, true);
		const iv = setInterval(() => {
			if (!exiting && ctl.anchor && !ctl.anchor.isConnected) ctl.close();
		}, 400);
		return () => {
			window.removeEventListener('scroll', reposition, true);
			clearInterval(iv);
		};
	});

	$effect(() => () => {
		cancelAnimationFrame(raf);
		clearTimeout(movingTimer);
		describe(null, null);
	});

	function onKeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape' && ctl.isOpen) ctl.close();
	}

	// тап/клік поза вікном і поза якорем закриває
	function onPointerdown(e: PointerEvent): void {
		if (!ctl.isOpen) return;
		const t = e.target as Node | null;
		if (t && (el?.contains(t) || ctl.anchor?.contains(t))) return;
		ctl.close();
	}
</script>

<svelte:window
	onkeydown={onKeydown}
	onpointerdown={onPointerdown}
	onresize={reposition}
/>

{#if mounted && shown != null}
	<div
		class="hc"
		id={uid}
		bind:this={el}
		use:portal
		role={role(shown)}
		aria-label={label ? label(shown) : undefined}
		onmouseenter={() => ctl.keep()}
		onmouseleave={() => ctl.unhover()}
	>
		<div class="hc-surface" bind:this={surface}>
			<div class="hc-body" bind:this={body}>
				{@render content(shown)}
			</div>
			<button class="hc-x" type="button" aria-label="Закрити" onclick={() => ctl.close()}>
				<X size={14} strokeWidth={2.4} />
			</button>
		</div>
		<i class="hc-arrow" aria-hidden="true"></i>
	</div>
{/if}

<style>
	.hc {
		position: fixed;
		left: 0;
		top: 0;
		z-index: var(--z-popover, 900);
		width: min(300px, calc(100vw - 16px));
		transform-origin: 50% 100%;
	}

	.hc:global([data-exiting]) {
		pointer-events: none;
	}

	.hc-surface {
		position: relative;
		overflow: hidden;
		border-radius: 14px;
		background: var(--surface-2);
		border: 1px solid var(--glass-border);
		box-shadow: 0 18px 50px color-mix(in srgb, var(--bg) 60%, black);
	}

	.hc-body {
		padding: 14px 15px;
	}

	/* знімок старого вмісту: тане поверх нового під час переїзду */
	.hc-surface > :global(.hc-ghost) {
		position: absolute;
		top: 0;
		left: 0;
		width: 100%;
		pointer-events: none;
	}

	/* стрілка-покажчик: ковзає вздовж краю разом із вікном */
	.hc-arrow {
		position: absolute;
		left: var(--ax, 50%);
		width: 10px;
		height: 10px;
		margin-left: -5px;
		background: var(--surface-2);
	}

	.hc:global([data-moving]) .hc-arrow {
		transition: left 460ms var(--hc-ease, ease);
	}

	.hc:global([data-side='top']) .hc-arrow {
		bottom: -5px;
		transform: rotate(45deg);
		border-right: 1px solid var(--glass-border);
		border-bottom: 1px solid var(--glass-border);
	}

	.hc:global([data-side='bottom']) .hc-arrow {
		top: -5px;
		transform: rotate(45deg);
		border-left: 1px solid var(--glass-border);
		border-top: 1px solid var(--glass-border);
	}

	/* кнопка закриття потрібна лише без миші */
	.hc-x {
		display: none;
		position: absolute;
		top: 6px;
		right: 6px;
		width: 28px;
		height: 28px;
		place-items: center;
		border: 0;
		border-radius: 8px;
		background: transparent;
		color: var(--text-faint);
		cursor: pointer;
		z-index: 1;
	}

	.hc-x:hover {
		color: var(--text);
		background: var(--glass-bg-hover);
	}

	@media (hover: none) {
		.hc-x {
			display: grid;
		}
	}

	:global(html[data-anim='off']) .hc:global([data-moving]) .hc-arrow {
		transition: none;
	}

	@media (prefers-reduced-motion: reduce) {
		.hc:global([data-moving]) .hc-arrow {
			transition: none;
		}
	}
</style>
