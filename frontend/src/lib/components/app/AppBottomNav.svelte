<script lang="ts">
	import { Ellipsis, UserRound } from '@lucide/svelte';
	import type { Component } from 'svelte';
	import type { Tab } from '$lib/app/helpers';
	import { pressable, motionOK, ease } from '$lib/motion';

	interface Props {
		tabs: { key: Tab; icon: Component<{ size?: number; strokeWidth?: number }>; label: string }[];
		mainTabs: ReadonlySet<Tab>;
		tab: Tab;
		isOther: boolean;
		menuOpen: boolean;
		onopen: (t: Tab) => void;
		onother: () => void;
		/** Користувач гортає вміст вниз: панель з'їжджає (необов'язково). */
		hidden?: boolean;
		/** Відкрите меню «Інше»: панель ніколи не ховаємо (необов'язково). */
		otherOpen?: boolean;
	}
	let {
		tabs,
		mainTabs,
		tab,
		isOther,
		menuOpen = $bindable(),
		onopen,
		onother,
		hidden = false,
		otherOpen = false
	}: Props = $props();

	// На телефоні рендеримо лише те, що показуємо: основні вкладки + Інше + Профіль.
	// Решта вкладок живе в панелі «Інше» — зайві вузли (display:none) не потрібні.
	const shown = $derived(tabs.filter((t) => mainTabs.has(t.key)));

	// Ключ пункту з індикатором: «Інше» для прихованих вкладок, інакше сама вкладка.
	// Поки меню «Інше» відкрите, підсвічується «Ще» (а не поточна вкладка).
	const activeKey = $derived<string>(isOther || otherOpen ? 'other' : tab);
	const order = $derived<string[]>([...shown.map((t) => t.key as string), 'other']);

	let barEl = $state<HTMLElement | null>(null);
	let itemEls = $state<Record<string, HTMLElement | undefined>>({});
	let icoEls = $state<Record<string, HTMLElement | undefined>>({});
	let indInner = $state<HTMLElement | null>(null);
	let indX = $state(0);
	let indY = $state(0);
	let indW = $state(0);
	let indH = $state(0);
	let indReady = $state(false);
	/** false = переносимо індикатор миттєво (перший кадр, поворот, шрифти). */
	let animated = $state(false);
	let rafA = 0;
	let rafB = 0;

	/** Позиція пункту відносно панелі через offset* (не залежить від transform/scale
	 *  під час натискання; .item — прямий нащадок fixed-панелі, що є його offsetParent). */
	function measure(instant: boolean): void {
		const el = itemEls[activeKey];
		if (!el || !barEl || el.offsetWidth === 0) {
			indReady = false;
			animated = false;
			return;
		}
		if (instant || !indReady) {
			animated = false;
			cancelAnimationFrame(rafA);
			cancelAnimationFrame(rafB);
			// вмикаємо перехід лише через 2 кадри після миттєвого переносу
			rafA = requestAnimationFrame(() => {
				rafB = requestAnimationFrame(() => (animated = true));
			});
		}
		indX = el.offsetLeft;
		indY = el.offsetTop;
		indW = el.offsetWidth;
		indH = el.offsetHeight;
		indReady = true;
	}

	// Зміна активного пункту / набору пунктів → плавний перенос.
	let prevKey: string | null = null;
	$effect(() => {
		const k = activeKey;
		void shown.length;
		void itemEls[k];
		const first = prevKey === null;
		measure(first);

		if (!first && prevKey !== k) {
			if (motionOK()) {
				// пружний «підстрибок» іконки при активації
				icoEls[k]?.animate(
					[
						{ transform: 'translateY(0) scale(1)' },
						{ transform: 'translateY(-2px) scale(1.18)', offset: 0.4 },
						{ transform: 'translateY(0) scale(1)' }
					],
					{ duration: 520, easing: ease('spring') }
				);
				// squash & stretch: індикатор витягується у напрямку руху (лише transform)
				const dir = order.indexOf(k) >= order.indexOf(prevKey ?? k) ? 1 : -1;
				if (indInner) {
					indInner.style.transformOrigin = dir > 0 ? 'left center' : 'right center';
					indInner.animate(
						[
							{ transform: 'scale(1, 1)' },
							{ transform: 'scale(1.42, 0.9)', offset: 0.35 },
							{ transform: 'scale(1, 1)' }
						],
						{ duration: 520, easing: ease('out') }
					);
				}
			}
		}
		prevKey = k;
	});

	// Перемір: зміна розміру панелі (поворот, адресний рядок), шрифти.
	$effect(() => {
		if (!barEl) return;
		const bar = barEl;
		const redo = () => measure(true);
		let ro: ResizeObserver | undefined;
		if (typeof ResizeObserver !== 'undefined') {
			ro = new ResizeObserver(redo);
			ro.observe(bar);
		}
		void document.fonts?.ready.then(redo);
		window.addEventListener('orientationchange', redo);
		return () => {
			ro?.disconnect();
			window.removeEventListener('orientationchange', redo);
			cancelAnimationFrame(rafA);
			cancelAnimationFrame(rafB);
		};
	});

	/* ---------- екранна клавіатура: панель ховаємо ----------
	 * Лише на дотикових пристроях (pointer: coarse) і лише за visualViewport:
	 * на десктопі зміна розміру вікна не повинна ховати панель. */
	let kbd = $state(false);
	let typing = $state(false);
	let baseH = 0;

	$effect(() => {
		const vv = window.visualViewport;
		const coarse = window.matchMedia('(pointer: coarse)');
		baseH = vv?.height ?? window.innerHeight;
		let lastW = window.innerWidth;
		const check = () => {
			if (!coarse.matches || !vv) {
				kbd = false;
				return;
			}
			// поворот/зміна ширини — нова базова висота
			if (window.innerWidth !== lastW) {
				lastW = window.innerWidth;
				baseH = vv.height;
			}
			baseH = Math.max(baseH, vv.height);
			kbd = baseH - vv.height > 150;
		};
		const isField = (el: EventTarget | null): boolean =>
			el instanceof HTMLElement &&
			(el.matches('input:not([type="checkbox"]):not([type="radio"]):not([type="button"]):not([type="submit"]):not([type="range"]), textarea, select') ||
				el.isContentEditable);
		let blurT = 0;
		const fin = (e: FocusEvent) => {
			clearTimeout(blurT);
			if (coarse.matches && isField(e.target)) typing = true;
		};
		const fout = () => {
			clearTimeout(blurT);
			// невелика затримка: фокус може одразу перейти на інше поле
			blurT = window.setTimeout(() => (typing = coarse.matches && isField(document.activeElement)), 120);
		};
		vv?.addEventListener('resize', check);
		coarse.addEventListener('change', check);
		document.addEventListener('focusin', fin);
		document.addEventListener('focusout', fout);
		check();
		return () => {
			clearTimeout(blurT);
			vv?.removeEventListener('resize', check);
			coarse.removeEventListener('change', check);
			document.removeEventListener('focusin', fin);
			document.removeEventListener('focusout', fout);
		};
	});

	/* ---------- скидання «залиплих» станів натискання ---------- */
	function resetPress(): void {
		if (!barEl) return;
		for (const b of barEl.querySelectorAll<HTMLElement>('.item')) {
			for (const a of b.getAnimations()) a.cancel();
		}
	}
	$effect(() => {
		const onVis = () => {
			if (document.visibilityState !== 'visible') resetPress();
		};
		document.addEventListener('visibilitychange', onVis);
		window.addEventListener('blur', resetPress);
		window.addEventListener('pagehide', resetPress);
		return () => {
			document.removeEventListener('visibilitychange', onVis);
			window.removeEventListener('blur', resetPress);
			window.removeEventListener('pagehide', resetPress);
		};
	});

	// Після зміни вкладки панель знову показуємо, доки не з'явиться нова команда ховатись.
	let reveal = $state(false);
	$effect(() => {
		void tab;
		reveal = true;
	});
	$effect(() => {
		void hidden;
		reveal = false;
	});

	const away = $derived(kbd || typing || (hidden && !reveal && !menuOpen && !otherOpen));
</script>

<nav
	class="bottombar frosted"
	class:away
	aria-label="Основна навігація"
	bind:this={barEl}
	inert={away}
	oncontextmenu={(e) => e.preventDefault()}
>
	<span
		class="ind"
		class:ready={indReady}
		class:animated
		aria-hidden="true"
		style:width={`${indW}px`}
		style:height={`${indH}px`}
		style:transform={`translate3d(${indX}px, ${indY}px, 0)`}
	>
		<span class="ind-i" bind:this={indInner}></span>
	</span>
	{#each shown as t (t.key)}
		{@const Icon = t.icon}
		<button
			type="button"
			class="item"
			use:pressable={{ scale: 0.92 }}
			bind:this={itemEls[t.key]}
			class:active={tab === t.key && !otherOpen}
			aria-current={tab === t.key ? 'page' : undefined}
			onclick={() => onopen(t.key)}
		>
			<span class="ico" bind:this={icoEls[t.key]}><Icon size={22} strokeWidth={2} /></span>
			<span class="bl">{t.label}</span>
		</button>
	{/each}
	<button
		type="button"
		class="item other-btn"
		use:pressable={{ scale: 0.92 }}
		bind:this={itemEls['other']}
		class:active={isOther || otherOpen}
		aria-haspopup="menu"
		aria-expanded={otherOpen}
		onclick={onother}
	>
		<span class="ico" bind:this={icoEls['other']}><Ellipsis size={22} strokeWidth={2} /></span>
		<span class="bl">Інше</span>
	</button>
	<button
		type="button"
		class="item prof"
		use:pressable={{ scale: 0.92 }}
		class:active={menuOpen}
		aria-haspopup="menu"
		aria-expanded={menuOpen}
		onclick={() => (menuOpen = !menuOpen)}
	>
		<span class="ico"><UserRound size={22} strokeWidth={2} /></span>
		<span class="bl">Профіль</span>
	</button>
</nav>

<style>
	/* Спільні розміри плаваючої панелі: використовує й +page (padding контенту) і меню. */
	:global(:root) {
		--nav-bar-h: 62px;
		--nav-gap: max(var(--space-3), calc(var(--safe-bottom) * 0.6));
		--nav-total: calc(var(--nav-bar-h) + var(--nav-gap));
	}

	.bottombar {
		display: none;
		position: fixed;
		left: max(var(--space-2), env(safe-area-inset-left));
		right: max(var(--space-2), env(safe-area-inset-right));
		bottom: var(--nav-gap);
		z-index: var(--z-nav);
		height: var(--nav-bar-h);
		box-sizing: border-box;
		padding: 4px;
		align-items: stretch;
		gap: 2px;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-full);
		box-shadow: var(--shadow-lg);
		-webkit-user-select: none;
		user-select: none;
		-webkit-touch-callout: none;
		touch-action: manipulation;
		-webkit-tap-highlight-color: transparent;
		/* лише transform/opacity — композитор */
		transition:
			transform 380ms var(--ease-spring),
			opacity 200ms ease;
		will-change: transform;
	}
	.bottombar.away {
		transform: translateY(calc(100% + var(--nav-gap) + 12px));
		opacity: 0;
		pointer-events: none;
		transition:
			transform 260ms cubic-bezier(0.4, 0, 0.7, 0.2),
			opacity 200ms ease;
	}

	.item {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 2px;
		padding: 0;
		font: inherit;
		font-size: 10.5px;
		line-height: 1.15;
		font-weight: var(--weight-medium);
		color: var(--color-text-muted);
		background: none;
		border: none;
		border-radius: var(--radius-full);
		cursor: pointer;
		position: relative;
		z-index: 1;
		touch-action: manipulation;
		-webkit-tap-highlight-color: transparent;
		transition: color var(--dur-base) ease;
	}
	.item:focus-visible {
		outline: 2px solid var(--color-accent);
		outline-offset: -2px;
	}

	.ico {
		display: grid;
		place-items: center;
		transition: color var(--dur-base) ease;
	}

	/* ковзний індикатор: зовнішній елемент їде (transform), внутрішній розтягується */
	.ind {
		position: absolute;
		top: 0;
		left: 0;
		z-index: 0;
		opacity: 0;
		pointer-events: none;
		will-change: transform;
	}
	.ind.ready {
		opacity: 1;
	}
	.ind.animated {
		transition: transform 480ms var(--ease-spring);
	}
	.ind-i {
		display: block;
		width: 100%;
		height: 100%;
		border-radius: var(--radius-full);
		background: var(--color-accent-soft);
		box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 18%, transparent);
	}
	:global(html[data-anim='off']) .ind.animated,
	:global(html[data-anim='off']) .bottombar,
	:global(html[data-anim='off']) .bottombar.away {
		transition: none;
	}
	@media (prefers-reduced-motion: reduce) {
		.ind.animated,
		.bottombar,
		.bottombar.away {
			transition: none;
		}
	}

	.bl {
		opacity: 0.8;
		font-size: 10px;
		letter-spacing: -0.01em;
		transition: opacity var(--dur-base) ease;
		max-width: 100%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.item.active {
		color: var(--color-accent-text);
	}
	.item.active .bl {
		opacity: 1;
		font-weight: var(--weight-semibold);
	}
	.item.active .ico {
		color: var(--color-accent);
	}
	/* «Профіль» не має ковзного індикатора — власний фон */
	.item.prof.active {
		background: var(--color-accent-soft);
	}

	/* hover лише для миші: на дотику він «залипає» */
	@media (hover: hover) and (pointer: fine) {
		.item:not(.active):hover {
			color: var(--color-text);
		}
	}

	@media (max-width: 900px) {
		.bottombar {
			display: flex;
		}
	}
</style>
