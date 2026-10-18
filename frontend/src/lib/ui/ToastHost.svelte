<script lang="ts">
	import { CircleAlert, X } from '@lucide/svelte';
	import { cubicOut } from 'svelte/easing';
	import type { TransitionConfig } from 'svelte/transition';
	import { portal } from '$lib/actions/portal';
	import { ease, motionOK, shake } from '$lib/motion';
	import { closeToast, pauseToast, resumeToast, toasts, type Toast } from '$lib/stores/toast.svelte';

	const GAP = 8;
	const FLING_DISTANCE = 90; // px: далі цього свайп закриває тост
	const FLING_VELOCITY = 0.5; // px/ms

	let mobile = $state(false);

	$effect(() => {
		const mq = window.matchMedia('(max-width: 640px)');
		mobile = mq.matches;
		const on = (e: MediaQueryListEvent): void => {
			mobile = e.matches;
		};
		mq.addEventListener('change', on);
		return () => mq.removeEventListener('change', on);
	});

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
	const enterSpring = springEase(0.55, 14);

	/** Поява з краю (праворуч-вгорі / знизу на мобільному) з легким перельотом. */
	function toastIn(_node: Element): TransitionConfig {
		if (!motionOK()) return { duration: 0 };
		const m = mobile;
		return {
			duration: 520,
			easing: enterSpring,
			css: (t, u) =>
				`opacity:${Math.min(1, t * 2.2)};transform:${
					m ? `translateY(${u * 44}px)` : `translateX(${u * 56}px)`
				} scale(${0.94 + 0.06 * t})`
		};
	}

	/** Зникнення: звичайний від'їзд або продовження руху після свайпу. */
	function toastOut(node: Element): TransitionConfig {
		if (!motionOK()) return { duration: 0 };
		const el = node as HTMLElement;
		const fling = Number(el.dataset.fling ?? 0);
		const off = Number(el.dataset.off ?? 0);
		if (fling) {
			const target = fling * (el.offsetWidth + 60);
			return {
				duration: 240,
				easing: cubicOut,
				css: (t, u) => `opacity:${t};transform:translateX(${off + u * (target - off)}px)`
			};
		}
		const m = mobile;
		return {
			duration: 240,
			easing: cubicOut,
			css: (t, u) =>
				`opacity:${t};transform:${m ? `translateY(${u * 24}px)` : `translateX(${u * 36}px)`} scale(${1 - 0.04 * u})`
		};
	}

	// ---- розкриття стека, пауза автозакриття ----
	let expanded = $state(false);
	let dragId = $state<number | null>(null);
	let leaveTimer: ReturnType<typeof setTimeout> | undefined;

	const paused = $derived(expanded || dragId !== null);

	function enter(): void {
		clearTimeout(leaveTimer);
		expanded = true;
	}
	function leave(): void {
		clearTimeout(leaveTimer);
		leaveTimer = setTimeout(() => (expanded = false), 140);
	}
	$effect(() => () => clearTimeout(leaveTimer));

	// пауза/відновлення таймерів усіх тостів (нові тости під час hover теж на паузі)
	$effect(() => {
		const p = paused;
		for (const t of toasts.list) {
			if (p) pauseToast(t.id);
			else resumeToast(t.id);
		}
	});

	// ---- вимірювання висот для розкритого стека ----
	let heights = $state<Record<number, number>>({});

	function measure(node: HTMLElement, id: number): { destroy(): void } {
		const ro = new ResizeObserver(() => {
			heights[id] = node.offsetHeight;
		});
		ro.observe(node);
		return {
			destroy(): void {
				ro.disconnect();
				delete heights[id];
			}
		};
	}

	const offsets = $derived.by(() => {
		const o: Record<number, number> = {};
		let acc = 0;
		for (let i = toasts.list.length - 1; i >= 0; i--) {
			const t = toasts.list[i];
			o[t.id] = acc;
			acc += (heights[t.id] ?? 48) + GAP;
		}
		return o;
	});

	/** Положення «слота» у стеку: k — глибина (0 = найновіший). */
	function slotStyle(t: Toast, index: number): string {
		const k = toasts.list.length - 1 - index;
		const sign = mobile ? -1 : 1;
		const z = 20 - k;
		if (expanded) {
			return `z-index:${z};transform:translateY(${sign * (offsets[t.id] ?? 0)}px);opacity:1`;
		}
		const shown = Math.min(k, 3);
		const opacity = k >= 3 ? 0 : 1 - k * 0.18;
		return `z-index:${z};transform:translateY(${sign * shown * 10}px) scale(${1 - shown * 0.04});opacity:${opacity}`;
	}

	// ---- смужка залишку часу ----
	function progress(node: HTMLElement, p: { ms: number; paused: boolean }) {
		if (!motionOK() || p.ms <= 0) {
			node.style.display = 'none';
			return;
		}
		const a = node.animate([{ transform: 'scaleX(1)' }, { transform: 'scaleX(0)' }], {
			duration: p.ms,
			easing: 'linear',
			fill: 'forwards'
		});
		if (p.paused) a.pause();
		return {
			update(n: { ms: number; paused: boolean }): void {
				if (n.paused) a.pause();
				else a.play();
			},
			destroy(): void {
				a.cancel();
			}
		};
	}

	/** Помилка один раз «труситься» після появи. */
	function errorShake(node: HTMLElement, tone: string): { destroy(): void } | void {
		if (tone !== 'error') return;
		const id = setTimeout(() => shake(node), 380);
		return { destroy: () => clearTimeout(id) };
	}

	// ---- свайп для закриття ----
	let startX = 0;
	let samples: { t: number; x: number }[] = [];
	let springBack: Animation | null = null;

	function onDown(e: PointerEvent, id: number): void {
		if (e.pointerType === 'mouse' && e.button !== 0) return;
		if ((e.target as HTMLElement).closest('button')) return;
		const el = e.currentTarget as HTMLElement;
		springBack?.cancel();
		springBack = null;
		startX = e.clientX;
		samples = [{ t: e.timeStamp, x: e.clientX }];
		dragId = id;
		el.setPointerCapture(e.pointerId);
	}

	function onMove(e: PointerEvent): void {
		if (dragId === null) return;
		const el = e.currentTarget as HTMLElement;
		const dx = e.clientX - startX;
		el.style.transform = `translateX(${dx}px)`;
		el.style.opacity = String(1 - Math.min(0.65, Math.abs(dx) / (el.offsetWidth * 1.2)));
		samples.push({ t: e.timeStamp, x: e.clientX });
		while (samples.length > 2 && e.timeStamp - samples[0].t > 100) samples.shift();
	}

	function onUp(e: PointerEvent): void {
		if (dragId === null) return;
		const el = e.currentTarget as HTMLElement;
		const id = dragId;
		const dx = e.clientX - startX;
		const first = samples[0];
		const dt = e.timeStamp - first.t;
		const v = dt > 0 ? (e.clientX - first.x) / dt : 0;
		dragId = null;
		const flung = Math.abs(dx) > FLING_DISTANCE || (Math.abs(v) > FLING_VELOCITY && Math.abs(dx) > 20);
		if (e.type !== 'pointercancel' && flung) {
			el.dataset.fling = String(Math.sign(Math.abs(v) > FLING_VELOCITY ? v : dx) || 1);
			el.dataset.off = String(dx);
			closeToast(id);
			return;
		}
		el.style.transform = '';
		el.style.opacity = '';
		if (motionOK() && dx !== 0) {
			springBack = el.animate([{ transform: `translateX(${dx}px)` }, { transform: 'translateX(0)' }], {
				duration: 520,
				easing: ease('spring')
			});
		}
	}
</script>

<div class="host" use:portal aria-live="polite" role="status" data-keep-interactive>
	{#each toasts.list as t, i (t.id)}
		<div
			class="slot"
			style={slotStyle(t, i)}
			use:measure={t.id}
			onpointerenter={enter}
			onpointerleave={leave}
			onfocusin={enter}
			onfocusout={leave}
			role="presentation"
		>
			<div
				class="toast {t.tone}"
				in:toastIn
				out:toastOut
				use:errorShake={t.tone}
				onpointerdown={(e) => onDown(e, t.id)}
				onpointermove={onMove}
				onpointerup={onUp}
				onpointercancel={onUp}
				role="presentation"
			>
				{#if t.tone === 'success'}
					<svg class="ico check" viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true">
						<circle class="ring" cx="12" cy="12" r="9.5" pathLength="1" />
						<path class="tick" d="M7.5 12.5l3 3 6-6.5" pathLength="1" />
					</svg>
				{:else if t.tone === 'error'}
					<CircleAlert class="ico" size={20} aria-hidden="true" />
				{/if}
				<span class="msg">{t.msg}</span>
				<button type="button" class="x" onclick={() => closeToast(t.id)} aria-label="Закрити сповіщення">
					<X size={16} aria-hidden="true" />
				</button>
				<span class="bar" use:progress={{ ms: t.ms, paused }} aria-hidden="true"></span>
			</div>
		</div>
	{/each}
</div>

<style>
	.host {
		position: fixed;
		z-index: var(--z-toast);
		top: calc(var(--topbar-h) + var(--space-3));
		right: var(--space-4);
		display: grid;
		width: min(420px, calc(100vw - 32px));
		pointer-events: none;
	}

	/* усі тости в одній клітинці сітки — стек, що розкривається на hover */
	.slot {
		grid-area: 1 / 1;
		align-self: start;
		justify-self: end;
		max-width: 100%;
		pointer-events: auto;
		transform-origin: center top;
		transition:
			transform 560ms var(--ease-spring),
			opacity 300ms var(--ease-out);
	}

	.toast {
		--tone: var(--color-accent);
		position: relative;
		display: flex;
		align-items: center;
		gap: var(--space-2);
		max-width: 100%;
		padding: var(--space-2) var(--space-2) var(--space-2) var(--space-4);
		font-size: var(--text-md);
		color: var(--color-text);
		background: var(--color-elevated);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-full);
		box-shadow: var(--shadow-lg);
		touch-action: pan-y;
		user-select: none;
		-webkit-user-select: none;
	}

	.toast.success {
		--tone: var(--color-success);
		border-color: color-mix(in srgb, var(--color-success) 40%, var(--color-border));
	}

	.toast.error {
		--tone: var(--color-danger);
		border-color: color-mix(in srgb, var(--color-danger) 40%, var(--color-border));
	}

	.toast :global(.ico) {
		flex-shrink: 0;
		margin-left: calc(var(--space-1) * -1);
		color: var(--tone);
	}

	/* галочка «промальовується» */
	.check .ring {
		stroke: var(--tone);
		stroke-width: 1.8;
		stroke-dasharray: 1;
		animation: toast-draw 460ms var(--ease-out) 120ms backwards;
	}

	.check .tick {
		stroke: var(--tone);
		stroke-width: 2.2;
		stroke-linecap: round;
		stroke-linejoin: round;
		stroke-dasharray: 1;
		animation: toast-draw 380ms var(--ease-out) 380ms backwards;
	}

	.check {
		transform-box: fill-box;
		transform-origin: center;
		animation: toast-pop 520ms var(--ease-spring) 380ms;
	}

	@keyframes toast-draw {
		from {
			stroke-dashoffset: 1;
		}
		to {
			stroke-dashoffset: 0;
		}
	}

	@keyframes toast-pop {
		50% {
			transform: scale(1.18);
		}
	}

	.msg {
		min-width: 0;
		overflow-wrap: anywhere;
	}

	.x {
		flex-shrink: 0;
		display: grid;
		place-items: center;
		width: 28px;
		height: 28px;
		padding: 0;
		margin-left: auto;
		color: var(--color-text-muted);
		background: transparent;
		border: none;
		border-radius: var(--radius-full);
		cursor: pointer;
		transition: background var(--dur-fast) var(--ease-out);
	}

	.x:hover {
		color: var(--color-text);
		background: var(--color-hover);
	}

	/* тонка смужка залишку часу в нижній частині пігулки */
	.bar {
		position: absolute;
		left: 18px;
		right: 18px;
		bottom: 3px;
		height: 2px;
		border-radius: var(--radius-full);
		background: var(--tone);
		opacity: 0.55;
		transform-origin: left center;
		pointer-events: none;
	}

	:global(html[data-anim='off']) .slot {
		transition: none;
	}

	:global(html[data-anim='off']) .check,
	:global(html[data-anim='off']) .check :is(.ring, .tick) {
		animation: none;
	}

	@media (max-width: 640px) {
		.host {
			top: auto;
			right: auto;
			left: 50%;
			bottom: calc(var(--nav-total, 76px) + 12px);
			transform: translateX(-50%);
		}

		.slot {
			align-self: end;
			justify-self: center;
			transform-origin: center bottom;
		}

		.x {
			width: 40px;
			height: 40px;
		}
	}
</style>
