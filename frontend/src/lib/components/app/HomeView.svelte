<script lang="ts">
	import { tick } from 'svelte';
	import type { Action } from 'svelte/action';
	import { fade } from 'svelte/transition';
	import type { TransitionConfig } from 'svelte/transition';
	import { cubicIn } from 'svelte/easing';
	import { Coins, GraduationCap, Gem, Medal, Trophy } from '@lucide/svelte';
	import {
		AnimatedNumber,
		blurFade,
		ease,
		fx,
		motionOK,
		slideX,
		spotlight,
		stagger
	} from '$lib/motion';
	import type {
		Dashboard,
		HwItem,
		LeaderboardView,
		MarksView,
		NewsView
	} from '$lib/api/client';
	import { store } from '$lib/stores/appStore.svelte';
	import { tapGuard } from '$lib/actions/tapGuard';
	import { portal } from '$lib/actions/portal';
	import { initials } from '$lib/sections';
	import MarksChipsCard from '$lib/components/MarksChipsCard.svelte';
	import {
		widgets,
		WIDGET_DEFS,
		WIDGET_SIZES,
		PRESETS,
		sizeName,
		type WidgetCfg,
		type WidgetKey as WidgetsKey
	} from '$lib/widgets.svelte';
	import {
		feedIcon,
		fmtDate,
		fmtDay,
		activityLabel,
		lessonOver,
		lessonsWord,
		mkCls,
		type SchedLesson,
		type Tab,
		cleanTeacher
	} from '$lib/app/helpers';

	interface Props {
		dash: Dashboard;
		activeId: number | null;
		/** Прокручувана область вмісту (потрібна драгу віджетів). */
		contentEl: HTMLElement | null;
		/** Іде скрол: клік/hover по картках тимчасово вимкнені. */
		scrolling: boolean;
		editHome: boolean;
		bScope: string;
		bPeriod: string;
		activity: ReturnType<typeof store.activity>;
		newsData: NewsView | null;
		homeMarks: MarksView | null;
		boardMini: LeaderboardView | null;
		openTab: (t: Tab) => Promise<void>;
		openDetails: (h: HwItem) => void;
		cellEnter: (e: MouseEvent, l: SchedLesson) => void;
		cellLeave: () => void;
		ensureBoard: (force?: boolean) => void;
		onnews: () => void;
	}
	// editHome/bScope/bPeriod живуть у батьківській сторінці (переживають
	// перемикання вкладок; editHome ще й керується кнопкою в шапці)
	let {
		dash,
		activeId,
		contentEl,
		scrolling,
		editHome = $bindable(),
		bScope = $bindable(),
		bPeriod = $bindable(),
		activity,
		newsData,
		homeMarks,
		boardMini,
		openTab,
		openDetails,
		cellEnter,
		cellLeave,
		ensureBoard,
		onnews
	}: Props = $props();

	/** Переходи «Усі …» унизу віджетів: вимкнені за замовчуванням,
	 *  вмикаються у панелі редагування біля пресетів. */
	const LINKS_LS = 'm1id.dash.links';
	let wgLinks = $state(false);
	try {
		wgLinks = localStorage.getItem(LINKS_LS) === '1';
	} catch {
		/* приватний режим */
	}
	function setWgLinks(v: boolean): void {
		wgLinks = v;
		try {
			localStorage.setItem(LINKS_LS, v ? '1' : '0');
		} catch {
			/* ignore */
		}
	}
	/** Перетягування: який віджет тягнемо і на який сідаємо. */
	let dragKey = $state<string | null>(null);
	let dragX = $state(0);
	let dragY = $state(0);
	let dragW = $state(0);
	/** Курсор усередині карточки: бокс не стрибає під пальці. */
	let dragOffX = $state(0);
	let dragOffY = $state(0);
	/** Мить «приземлення» для пружної анімації. */
	let justDropped = $state<string | null>(null);
	/** Живий індекс вставки під час перетягування (вільне переміщення:
	 *  сусіди розступаються одразу, бокс «докується» куди кинули). */
	let dragIdx = -1;
	/** У якого віджета відкритий пікер ширини. */
	let spanFor = $state<string | null>(null);
	let popX = $state(0);
	let popY = $state(0);

	/* ================= рух (motion v1, див. docs/MOTION.md) ================= */

	/** Каскад рядків усередині віджета: лише перші `max` ВИДИМІ рядки
	 *  (решта з'являється одразу), коротко: base + max·step + 320мс ≲ 500мс. */
	const cascade: Action<
		HTMLElement,
		{ sel: string; step?: number; max?: number; base?: number }
	> = (node, o) => {
		if (!motionOK()) return;
		const raf = requestAnimationFrame(() => {
			const vh = window.innerHeight;
			const max = o.max ?? 6;
			let n = 0;
			for (const el of node.querySelectorAll<HTMLElement>(o.sel)) {
				if (n >= max) break;
				const r = el.getBoundingClientRect();
				if (r.bottom < 0 || r.top > vh) continue;
				el.animate(
					[
						{ opacity: 0, transform: 'translateY(6px)' },
						{ opacity: 1, transform: 'none' }
					],
					{
						duration: 320,
						delay: (o.base ?? 40) + n * Math.min(o.step ?? 24, 28),
						easing: ease('out'),
						fill: 'backwards'
					}
				);
				n++;
			}
		});
		return { destroy: () => cancelAnimationFrame(raf) };
	};

	/** «Озброює» список: поки не минуло ~0.8с після монтування, нові рядки
	 *  не анімуються окремо (їх уже веде cascade); пізніші порції — так. */
	const arm: Action<HTMLElement, (v: boolean) => void> = (node, set) => {
		set(false);
		const t = setTimeout(() => set(true), 800);
		return {
			destroy() {
				clearTimeout(t);
				set(false);
			}
		};
	};
	let dlReady = $state(false);
	let actReady = $state(false);

	/** Поява нової порції рядків (ліниве дозавантаження): fade-up без blur (рядків багато). */
	function lazyIn(
		node: Element,
		p: { ready: boolean; delay?: number }
	): TransitionConfig {
		if (!p.ready) return { duration: 0 };
		return blurFade(node, { y: 8, amount: 0, duration: 280, delay: p.delay ?? 0 });
	}

	/** Поява віджета, доданого вже після першого показу сітки (палітра/пресет). */
	let gridReady = $state(false);
	$effect(() => {
		const t = setTimeout(() => (gridReady = true), 900);
		return () => clearTimeout(t);
	});
	function widgetIn(node: Element, key: string): TransitionConfig {
		// на першому показі веде stagger; після drop — FLIP (flipDrop)
		if (!motionOK() || !gridReady || justDropped === key) return { duration: 0 };
		return {
			duration: 420,
			easing: ease_back,
			css: (t, u) =>
				`opacity:${Math.min(1, t * 1.8)};transform:scale(${0.94 + 0.06 * t}) translateY(${u * 10}px)`
		};
	}
	function ease_back(t: number): number {
		const c1 = 1.4;
		const c3 = c1 + 1;
		return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
	}
	/** Прибрання віджета: м'яко зменшується й зникає (не під час драга). */
	function widgetOut(node: Element): TransitionConfig {
		if (!motionOK() || dragKey) return { duration: 0 };
		return {
			duration: 260,
			easing: cubicIn,
			css: (t, u) =>
				`opacity:${t};transform:scale(${0.88 + 0.12 * t})` + (fx() ? `;filter:blur(${u * 6}px)` : '')
		};
	}

	/** FLIP при відпусканні: з позиції плаваючого боксу — у свій слот. */
	async function flipDrop(key: string, fx: number, fy: number): Promise<void> {
		if (!motionOK()) return;
		await tick();
		const el = contentEl?.querySelector<HTMLElement>(`[data-wkey="${key}"] > article`);
		if (!el) return;
		const r = el.getBoundingClientRect();
		const dx = fx - r.left;
		const dy = fy - r.top;
		if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
		el.animate(
			[
				{ transform: `translate(${dx}px, ${dy}px) scale(1.03)` },
				{ transform: 'translate(0, 0) scale(1)' }
			],
			{ duration: 440, easing: ease('spring') }
		);
	}

	/** Годинник для «живого» уроку: тік раз на 30с. */
	let nowTs = $state(Date.now());
	$effect(() => {
		const t = setInterval(() => (nowTs = Date.now()), 30_000);
		return () => clearInterval(t);
	});
	function tMs(t: string): number | null {
		const p = (t || '').split(':');
		if (p.length !== 2) return null;
		const d = new Date();
		d.setHours(Number(p[0]), Number(p[1]), 0, 0);
		return d.getTime();
	}
	/** Прогрес уроку 0..1, якщо він іде просто зараз; інакше -1. */
	function lessonProgress(l: { start: string; end: string }, now: number): number {
		const s = tMs(l.start);
		const e = tMs(l.end);
		if (s == null || e == null || e <= s || now < s || now >= e) return -1;
		return (now - s) / (e - s);
	}

	/** Прострочений дедлайн: раніше «потрушувався» через ~1с після відкриття —
	 *  це виглядало як збій анімації, тож ефект вимкнено (хук лишився no-op). */
	const attn: Action<HTMLElement, boolean> = () => {};
	const firstLateId = $derived(dash.nearest_deadlines.find((h) => h.overdue_days > 0)?.id);


	const bScopesMeta = $derived(boardMini?.scopes ?? []);
	const bCurScope = $derived.by(() => {
		if (bScopesMeta.some((s) => s.key === bScope)) return bScope;
		return bScopesMeta[0]?.key ?? '';
	});
	const bPeriodsMeta = $derived(
		bScopesMeta.find((s) => s.key === bCurScope)?.periods ?? []
	);
	const bCurPeriod = $derived.by(() => {
		if (bPeriodsMeta.some((p) => p.key === bPeriod)) return bPeriod;
		return bPeriodsMeta[0]?.key ?? '';
	});
	const bSec = $derived(
		boardMini?.sections?.[bCurScope]?.[bCurPeriod] ?? {
			top: [],
			nearby: [],
			new_students: []
		}
	);

	/** Pointer-drag: сам бокс плаває за курсором (fixed, напівпрозорий),
	 *  а сітка одразу переїжджає — ніби боксу на місці більше немає.
	 *  Кліки по кнопках не ламаються: драг стартує лише після 6px руху.
	 *  Тач — тільки з грипа ⠿ (щоб не конфліктувати зі скролом). */
	let scrollRAF = 0;
	let mouseY = 0;

	function scrollTick(): void {
		if (!dragKey) {
			scrollRAF = 0;
			return;
		}
		const el = contentEl;
		if (el) {
			if (mouseY < 110) el.scrollTop -= 12;
			else if (window.innerHeight - mouseY < 110) el.scrollTop += 12;
		}
		scrollRAF = requestAnimationFrame(scrollTick);
	}

	function wPointerDown(e: PointerEvent, key: string): void {
		if (!editHome || e.button !== 0) return;
		const t = e.target as HTMLElement;
		if (t.closest('button, a, select, input, textarea, label, .w-spanpop, .w-rz, .w-vrz'))
			return;
		if (e.pointerType === 'touch' && !t.closest('.w-grip')) return;

		const card = e.currentTarget as HTMLElement;
		const r = card.getBoundingClientRect();
		const startX = e.clientX;
		const startY = e.clientY;
		const offX = e.clientX - r.left;
		const offY = e.clientY - r.top;
		let started = false;

		const stop = (): void => {
			window.removeEventListener('pointermove', onMove);
			window.removeEventListener('pointerup', onUp);
			window.removeEventListener('pointercancel', onUp);
			if (scrollRAF) {
				cancelAnimationFrame(scrollRAF);
				scrollRAF = 0;
			}
		};

		const onMove = (ev: PointerEvent): void => {
			mouseY = ev.clientY;
			if (!started) {
				if (Math.hypot(ev.clientX - startX,
					ev.clientY - startY) < 6) return;
				started = true;
				dragKey = key;
				dragW = r.width;
				dragOffX = offX;
				dragOffY = offY;
				spanFor = null;
				dragIdx = widgets.list.findIndex((x) => x.key === key);
				// виділення тексту ламає перетягування
				document.body.classList.add('w-noselect');
				if (!scrollRAF) scrollRAF = requestAnimationFrame(scrollTick);
			}
			if (dragKey !== key) {
				stop();
				return;
			}
			ev.preventDefault(); // браузер не виділяє текст
			dragX = ev.clientX;
			dragY = ev.clientY;
			/** Вільне переміщення: індекс вставки з позиції курсора
			 *  (смуга рядка + ліва/права половина). Живий reflow —
			 *  сусіди розступаються, на drop бокс докується щільно. */
			const others = widgets.list.filter((x) => x.key !== key);
			let k = others.length;
			const rects = new Map<string, DOMRect>();
			(contentEl?.querySelectorAll('[data-wkey]') ?? []).forEach((el) => {
				const kk = el.getAttribute('data-wkey');
				if (kk && kk !== key) rects.set(kk, el.getBoundingClientRect());
			});
			for (let i = 0; i < others.length; i++) {
				const rr = rects.get(others[i].key);
				if (!rr) continue;
				const cx = rr.left + rr.width / 2;
				if (ev.clientY < rr.top || (ev.clientY <= rr.bottom && ev.clientX < cx)) {
					k = i;
					break;
				}
			}
			if (k !== dragIdx) {
				dragIdx = k;
				widgets.moveTo(key as WidgetsKey, k, false);
			}
		};

		const onUp = (): void => {
			stop();
			document.body.classList.remove('w-noselect');
			if (!started) return;
			// фіксуємо порядок (живі moveTo під час драга LS не чіпали)
			widgets.commitResize();
			const fromX = dragX - dragOffX;
			const fromY = dragY - dragOffY;
			dragKey = null;
			dragIdx = -1;
			justDropped = key;
			void flipDrop(key, fromX, fromY);
			setTimeout(() => {
				if (justDropped === key) justDropped = null;
			}, 380);
		};

		window.addEventListener('pointermove', onMove);
		window.addEventListener('pointerup', onUp);
		window.addEventListener('pointercancel', onUp);
	}

	/** Білий роздільник між боксами (як у Samsung): тягнеш — ліва
	 *  картка росте, права стискається, із прив'язкою до колонок. */
	function rzDown(e: PointerEvent, key: WidgetsKey): void {
		e.stopPropagation();
		if (!editHome) return;
		const aEl = contentEl?.querySelector(
			`[data-wkey="${key}"]`) as HTMLElement | null;
		if (!aEl) return;
		const idx = widgets.list.findIndex((x) => x.key === key);
		if (idx < 0) return;
		const ra = aEl.getBoundingClientRect();
		const sa0 = widgets.list[idx].span;
		const pitch = (ra.width + 14) / sa0; // колонка + проміжок
		const nb = widgets.list[idx + 1] ?? null;
		const nbEl = nb ? (contentEl?.querySelector(
			`[data-wkey="${nb.key}"]`) as HTMLElement | null) : null;
		const sameRow = nbEl
			? Math.abs(nbEl.getBoundingClientRect().top - ra.top) < 24
			: false;
		const sb0 = sameRow && nb ? nb.span : 0;
		document.body.classList.add('w-noselect');
		/** Режим «спихнути сусіда вниз» з гістерезисом у 1 колонку:
		 *  потягнув за край рядка — сусід іде вниз, бокс росте до 12;
		 *  звузив назад — dense сам повертає сусіда у ряд. */
		let pushed = false;
		/** Мінімальна ширина цього боксу: показники — виняток, 2 кол. */
		const minA = key === 'stats' ? 2 : 4;

		const onMove = (ev: PointerEvent): void => {
			const k = Math.round((ev.clientX + 7 - ra.left) / pitch);
			if (sameRow && nb) {
				const minB = nb && nb.key === 'stats' ? 2 : 4;
				const maxPair = sa0 + sb0 - minB;
				if (!pushed && k > maxPair) pushed = true;
				else if (pushed && k <= maxPair - 1) pushed = false;
				if (pushed) {
					widgets.setSpan(key,
						Math.min(12, Math.max(minA, k)), false);
				} else {
					const aS = Math.max(minA, Math.min(maxPair, k));
					widgets.resizePair(key, aS, nb.key, sa0 + sb0 - aS);
				}
			} else {
				// сусіда в ряді немає: вільна ширина 4..край рядка —
				// звільнене місце одразу затягнуть сусіди (dense)
				const gridR = (contentEl as HTMLElement)
					.getBoundingClientRect().right;
				const extra = Math.max(0,
					Math.floor((gridR - ra.right + 7) / pitch));
				widgets.setSpan(key,
					Math.max(minA, Math.min(k, sa0 + extra)), false);
			}
		};
		const onUp = (): void => {
			window.removeEventListener('pointermove', onMove);
			window.removeEventListener('pointerup', onUp);
			document.body.classList.remove('w-noselect');
			widgets.commitResize();
		};
			window.addEventListener('pointermove', onMove);
			window.addEventListener('pointerup', onUp);
	}

	/** Ручка висоти (нижній край картки): тягни вгору/вниз — явна
	 *  висота з кроком 8px, контент скролиться всередині. Сусіди по
	 *  рядку теж змінюють розмір — рядок стає однієї висоти. */
	function vrzDown(e: PointerEvent, key: WidgetsKey): void {
		e.stopPropagation();
		if (!editHome) return;
		const aEl = contentEl?.querySelector(
			`[data-wkey="${key}"]`) as HTMLElement | null;
		if (!aEl) return;
		const ra = aEl.getBoundingClientRect();
		/** Сусіди по рядку: всі змінюють висоту разом — рядок стає
		 *  однієї висоти. Зменшувати можна вільно: зайвий контент
		 *  скролиться всередині картки (overflow у .has-h). */
		const rowMates: WidgetsKey[] = [];
		for (const x of widgets.list) {
			if (x.key === key) continue;
			const el = contentEl?.querySelector(
				`[data-wkey="${x.key}"]`) as HTMLElement | null;
			if (!el) continue;
			const rr = el.getBoundingClientRect();
			if (Math.abs(rr.top - ra.top) < 24) rowMates.push(x.key);
		}
		document.body.classList.add('w-noselect');

		const onMove = (ev: PointerEvent): void => {
			// показники — виняток: мінімальна висота вдвічі менша.
			// minH передається в setH: раніше всередині стора жорстко
			// клампилось до 140, тож виняток для stats не працював ніколи.
			const minH = key === 'stats' ? 70 : 140;
			const k = Math.max(minH,
				Math.min(1000, Math.round((ev.clientY - ra.top) / 8) * 8));
			widgets.setH(key, k, false, minH);
			for (const mk of rowMates) widgets.setH(mk, k, false);
		};
		const onUp = (): void => {
			window.removeEventListener('pointermove', onMove);
			window.removeEventListener('pointerup', onUp);
			document.body.classList.remove('w-noselect');
			widgets.commitResize();
		};
		window.addEventListener('pointermove', onMove);
		window.addEventListener('pointerup', onUp);
	}

	/** Чи це «я» в таблиці лідерів: порівняння ФІО як множини слів
	 *  (профіль: «Іван Мендєлєєв», таблиця: «Мендєлєєв Іван Олексійович»). */
	function fioIn(fio: string): boolean {
		const mine = dash?.user?.fio;
		if (!mine) return false;
		const words = (x: string): Set<string> =>
			new Set(
				x
					.toLowerCase()
					.replace(/[^\p{L}\s]/gu, ' ')
					.split(/\s+/)
					.filter((w) => w.length > 1)
			);
		const a = words(mine);
		const b = words(fio);
		if (a.size === 0) return false;
		for (const w of a) if (!b.has(w)) return false;
		return true;
	}

	/** Віджет «Нарахування»: доскролив тіло до дна — підтягуємо
	 *  наступну сторінку подій (без кнопок, як в оцінках). */
	function onFeedScroll(el: HTMLElement): void {
		if (!activeId || !activity?.has_more || activity.loading) return;
		if (el.scrollTop + el.clientHeight >= el.scrollHeight - 60) {
			void store.activityNext(activeId);
		}
	}

	/** Віджет «Дедлайни»: рендеримо порціями — скільки влізає (+1),
	 *  при доскролі додаємо ще. Дані локальні, «дозавантаження» миттєве. */
	let dlBody = $state<HTMLElement | null>(null);
	let dlShow = $state(4);
	$effect(() => {
		const b = dlBody;
		if (!b) return;
		const calc = () => {
			const row = b.querySelector('li');
			const rh = row ? row.getBoundingClientRect().height : 0;
			if (rh > 8) {
				dlShow = Math.max(dlShow, Math.floor((b.clientHeight + 8) / rh) + 1);
			}
		};
		calc();
		const ro = new ResizeObserver(calc);
		ro.observe(b);
		return () => ro.disconnect();
	});
	function onDlScroll(el: HTMLElement): void {
		if (el.scrollTop + el.clientHeight >= el.scrollHeight - 60) dlShow += 4;
	}

	/** Escape під час перетягування: скидаємо стан драга/пікера. */
	function onWinKey(e: KeyboardEvent): void {
		if (e.key !== 'Escape') return;
		dragKey = null;
		justDropped = null;
		dragIdx = -1;
		spanFor = null;
		document.body.classList.remove('w-noselect');
	}

	// піти з Головної посеред драга — не лишаємо заборону виділення на body
	$effect(() => () => document.body.classList.remove('w-noselect'));
</script>

<svelte:window onkeydown={onWinKey} />

					{#snippet wStats(d: Dashboard)}
			<button class="stat" onclick={() => openTab('marks')}>
				<span class="s-label">Середній бал</span>
				<span class="s-value accent-text">
					{#if d.marks_summary.overall_avg != null}<AnimatedNumber
						value={d.marks_summary.overall_avg} decimals={1} />{:else}—{/if}</span>
			</button>
			<button class="stat" onclick={() => openTab('homework')}>
				<span class="s-label">Домашка</span>
				<span class="s-value"><AnimatedNumber value={d.homework_counts.pending} /></span>
				<span class="small text-faint">
					прострочено: {d.nearest_deadlines.filter((h) => h.overdue_days > 0).length}</span>
			</button>
			<button class="stat" onclick={() => openTab('activity')}>
				<span class="s-label">
					<Coins size={14} strokeWidth={2} /> Монети</span>
				<span class="s-value">
					<AnimatedNumber value={d.balances.items.find((i) => i.key === 'coins')?.value ?? 0}
						format={(n) => n.toLocaleString('uk-UA')} />
				</span>
			</button>
			<button class="stat" onclick={() => openTab('activity')}>
				<span class="s-label">
					<Gem size={14} strokeWidth={2} /> Кристали</span>
				<span class="s-value">
					<AnimatedNumber value={d.balances.items.find((i) => i.key === 'cristals')?.value ?? 0}
						format={(n) => n.toLocaleString('uk-UA')} />
				</span>
			</button>
			<button class="stat" onclick={() => openTab('activity')}>
				<span class="s-label">
					<Medal size={14} strokeWidth={2} /> Ачивки</span>
				<span class="s-value">
					<AnimatedNumber value={d.balances.items.find((i) => i.key === 'achivements')?.value ?? 0}
						format={(n) => n.toLocaleString('uk-UA')} />
				</span>
			</button>
		{/snippet}

	{#snippet wDeadlines(d: Dashboard)}
			<h2>Найближчі дедлайни</h2>
			{#if d.nearest_deadlines.length}
				<ul
					class="rows-list wg-body"
					bind:this={dlBody}
					onscroll={(e) => onDlScroll(e.currentTarget)}
					use:cascade={{ sel: ':scope > li', step: 24 }}
					use:arm={(v) => (dlReady = v)}
				>
					{#each d.nearest_deadlines.slice(0, dlShow) as h, hi (h.id)}
						<li in:lazyIn={{ ready: dlReady, delay: (hi % 4) * 40 }}
							use:attn={h.id === firstLateId}>
							<span class="due-chip" class:late={h.overdue_days > 0}>{fmtDate(h.due)}</span>
							<div class="l-info">
								<b>{h.subject}</b>
								<span class="text-dim small">{h.title}{h.overdue_days > 0
									? ' · прострочено' : ''}</span>
							</div>
							<button class="btn ghost"
								onclick={() => { openTab('homework'); openDetails(h); }}>→</button>
						</li>
					{/each}
				</ul>
				<button class="btn link wg-all" onclick={() => openTab('homework')}>
					Усі дедлайни →</button>
			{:else}
				<p class="text-faint">Все здано 🎉</p>
			{/if}
		{/snippet}

	{#snippet wLessons(d: Dashboard)}
			<h2>
				Сьогодні
				<span class="text-faint small">
					({d.today_lessons.length} {lessonsWord(d.today_lessons.length)} ·
					{d.week_lessons_total} за тиждень)</span>
			</h2>
			{#if d.today_lessons.length}
				{@const hasMarks = d.today_lessons.some(
					(l) => l.mark != null || (l.was === 0 && lessonOver(l))
				)}
				<!-- hasMarks: слот під оцінки вмикається лише коли є що показати,
					тоді ВЕСЬ віджет вирівнюється під нього; без оцінок час — впритул праворуч -->
				{@const nextIdx = d.today_lessons.findIndex((x) => {
					const s = tMs(x.start);
					return s != null && s > nowTs;
				})}
				<ul class="rows-list wg-body tl-list" class:has-marks={hasMarks}
					use:cascade={{ sel: ':scope > li', step: 28 }}>
					{#each d.today_lessons as l, i (l.lesson_no + '-' + i)}
						{@const prog = lessonProgress(l, nowTs)}
						<li
							class="lesson today-row"
							class:live={prog >= 0}
							class:next={prog < 0 && i === nextIdx}
							class:exam={!!l.exam}
							onmouseenter={(e) => l.lesson_no > 0 && cellEnter(e, l)}
							onmouseleave={cellLeave}
							onclick={(e) => l && cellEnter(e, l)}
							role="button"
							tabindex="0"
							onkeydown={(e) => {
								if (e.key === 'Enter' || e.key === ' ') {
									e.preventDefault();
									cellEnter(e as unknown as MouseEvent, l);
								}
							}}
						>
							<div class="l-info">
								<b>
									{#if prog >= 0}<i class="live-dot breathe" aria-label="Зараз іде"></i>{/if}
									{l.subject}
									{#if prog >= 0}<span class="st-tag now">Зараз</span>
									{:else if i === nextIdx}<span class="st-tag nx">Далі</span>{/if}
									{#if l.exam}<span class="ex-tag"><GraduationCap size={11} strokeWidth={2.4} /> Екзамен</span>{/if}
								</b>
								<span class="text-dim small">
									{#if l.room}<span class="les-room">{l.room}</span><i class="dot-sep">&middot;</i>{/if}{l.theme || cleanTeacher(l.teacher)}
								</span>
							</div>
							<span class="les-time"><b>{l.start}</b><i>&ndash;{l.end}</i></span>
							{#if hasMarks}
								<!-- слот однаковий для всіх рядків => час не скаче між рядками -->
								<span class="les-slot">
									{#if l.was === 0 && lessonOver(l)}
										<span class="nk" title="Не був">Н</span>
									{/if}
									{#if l.mark != null}
										<span class="mk {mkCls(l.mark)}"
											class:ex={!!l.exam}>{l.mark}</span>
									{/if}
								</span>
							{/if}
							{#if prog >= 0}
								<span class="les-prog" aria-hidden="true"><i
									style="transform:scaleX({prog.toFixed(4)})"></i></span>
							{/if}
						</li>
					{/each}
				</ul>
				<button class="btn link wg-all" onclick={() => openTab('schedule')}>
					Розклад тижня →</button>
			{:else}
				<p class="text-faint">Сьогодні занять немає 🛋</p>
			{/if}
		{/snippet}

	{#snippet wMarks()}
			<div class="wg-body mkw">
				<MarksChipsCard marks={homeMarks} limitMonths={0}
					fixedView="grid"
					onshowall={() => openTab('marks')} />
			</div>
			<button class="btn link wg-all" onclick={() => openTab('marks')}>
				Усі оцінки →</button>
		{/snippet}

	{#snippet wActivity()}
			<h2>Останні нарахування</h2>
			{#if activity && activity.items.length}
				<ul class="rows-list wg-body"
					onscroll={(e) => onFeedScroll(e.currentTarget)}
					use:cascade={{ sel: ':scope > li.wg-item', step: 24 }}
					use:arm={(v) => (actReady = v)}>
					{#each activity.items as it, idx (it.id)}
						{@const [FIcon, FCls] = feedIcon(it)}
						{@const showDay = idx === 0
							|| activity.items[idx - 1].date !== it.date}
						<li class="wg-item" in:lazyIn={{ ready: actReady, delay: (idx % 5) * 40 }}>
							{#if showDay}
								<h3 class="feed-date wg-day">{fmtDay(it.date)}</h3>
							{/if}
							<div class="wg-row">
							<div class="feed-icon {FCls}" class:marked={it.mark != null}>
								{#if it.mark != null}
									<span class="mark-num">{it.mark}</span>
								{:else}
									<FIcon size={15} strokeWidth={2} />
									{#if !FCls && it.icon}
										<img
											class="feed-img"
											src={it.icon}
											alt=""
											loading="lazy"
											referrerpolicy="no-referrer"
											onerror={(e) => e.currentTarget.remove()}
										/>
									{/if}
								{/if}
							</div>
								<div class="l-info">
									<b>{activityLabel(it.title)}</b>
									{#if it.subtitle}
										<span class="text-dim small">{activityLabel(it.subtitle)}</span>
									{/if}
								</div>
																{#each it.awards.slice(0, 2) as aw (aw.alias)}
									{@const AIcon = aw.alias === 'coins' ? Coins
										: aw.alias === 'achivements' ? Medal : Gem}
									<span class="award {aw.alias}">
										<AnimatedNumber value={aw.value} duration={560}
											format={(n) => (n > 0 ? '+' : '') + n.toLocaleString('uk-UA')} />
										<AIcon size={12} strokeWidth={2.4} />
									</span>
								{/each}
							</div>
						</li>
					{/each}
					{#if activity.loading}
						<li class="wg-more"><span class="mini-spin"></span></li>
					{/if}
				</ul>
				<button class="btn link wg-all" onclick={() => openTab('activity')}>
					Усі нарахування →</button
				>
			{:else}
				<p class="text-faint small">Завантажую…</p>
			{/if}
		{/snippet}

	{#snippet wNews()}
			<div class="news-head">
				<h2>
					Новини
					{#if newsData?.unread}
						<span class="news-unread"><AnimatedNumber
								value={newsData.unread} duration={600} /></span>
					{/if}
				</h2>
			</div>
			{#if newsData?.items?.length}
				<div class="news-grid wg-body"
					use:cascade={{ sel: ':scope > .news-item', step: 28 }}>
					{#each newsData.items as n (n.id)}
						<button class="news-item" onclick={onnews}>
							{#if n.image}
								<img src={n.image} alt="" loading="lazy" />
							{:else}
								<span class="ph" aria-hidden="true">📰</span>
							{/if}
							<span class="t">
								<b>{n.title}</b>
								<span class="text-faint small">{n.published_at}
									{#if !n.is_viewed}· <b class="new-mark">нове</b>{/if}</span>
							</span>
						</button>
					{/each}
				</div>
				<button class="btn link wg-all" onclick={onnews}>
					Усі новини →</button>
			{:else}
				<p class="text-faint">
					{newsData ? 'Новин поки немає' : 'Завантажую…'}</p>
			{/if}
		{/snippet}

	{#snippet wBoard(span: number)}
		<div class="news-head">
			<h2>Лідери</h2>
		</div>
		{#if boardMini}
			{@const rows = [...bSec.top, ...bSec.nearby, ...bSec.new_students]}
			{@const me = rows.find((r) => fioIn(r.fio))}
			<div class="b-swrow">
				<div class="b-sw" role="group" aria-label="Охоплення">
					{#each bScopesMeta as s (s.key)}
						<button class:active={bCurScope === s.key}
							onclick={() => (bScope = s.key)}>{s.label}</button>
					{/each}
				</div>
				<div class="b-sw" role="group" aria-label="Період">
					{#each bPeriodsMeta as p (p.key)}
						<button class:active={bCurPeriod === p.key}
							onclick={() => (bPeriod = p.key)}>{p.label}</button>
					{/each}
				</div>
				<div class="flex-sp"></div>
				{#if me}
					<span class="me-chip-sm" title="Моє місце">
						<Trophy size={13} /> #{me.position ?? '🌱'}
					</span>
				{/if}
			</div>
			{#if rows.length}
				{#key bCurScope + '|' + bCurPeriod}
				<div class="b-list" class:wide={span >= 8}
					in:slideX={{ distance: 12, duration: 220 }}
					use:cascade={{ sel: '.b-row', step: 24, base: 30, max: 8 }}>
					{#each rows as r, ri (String(r.id) + '-' + ri)}
						{#if ri === 3 && (rows[3]?.position ?? 99) > 4}
							<div class="b-gap" aria-hidden="true">⋯</div>
						{/if}
						<div class="b-row" class:me={fioIn(r.fio)}>
							{#if r.position != null && r.position <= 3}
								<span class="bmedal m{r.position}">{r.position}</span>
							{:else if r.position == null}
								<span class="bseed">🌱</span>
							{:else}
								<span class="bnum mono">{r.position}</span>
							{/if}
							{#if r.photo}
								<img class="b-ava" src={r.photo} alt="" loading="lazy" />
							{:else}
								<span class="b-ava ini">{initials(r.fio)}</span>
							{/if}
							<b class="fio">{r.fio}</b>
							<span class="flex-sp"></span>
							<span class="award coins">
								<Coins size={12} /> <AnimatedNumber value={r.amount ?? 0}
								duration={700} format={(n) => n.toLocaleString('uk-UA')} /></span>
						</div>
					{/each}
				</div>
				{/key}
			{:else}
				<p class="text-faint small">Таблиця порожня</p>
			{/if}
		{:else}
			<p class="text-faint small">Завантажую…</p>
			{ensureBoard()}
		{/if}
		<button class="btn link wg-all" onclick={() => openTab('board')}>
			Уся таблиця →</button
		>
	{/snippet}

		{#snippet wCardInner(w: WidgetCfg, wi: number, d: Dashboard)}
			{#if editHome}
				<div class="w-ctl">
					<span class="w-grip" title="Перетягни">⠿</span>
					<button title="Ліворуч" disabled={wi === 0}
						onclick={() => widgets.move(w.key, -1)}>←</button>
					<button title="Праворуч"
						disabled={wi === widgets.list.length - 1}
						onclick={() => widgets.move(w.key, 1)}>→</button>
					<button class="w-span" title="Ширина"
						onclick={(e) => {
							if (spanFor === w.key) {
								spanFor = null;
								return;
							}
							const r = (e.currentTarget as HTMLElement)
								.getBoundingClientRect();
							popX = Math.max(8, r.right - 196);
							popY = r.bottom + 6;
							spanFor = w.key;
						}}>
						▭ {sizeName(w.span)}</button>
					<button class="w-del" title="Прибрати"
						onclick={() => widgets.remove(w.key)}>✕</button>
				</div>
				{#if spanFor === w.key}
					<!-- clickOutside закриває: фон-невидимка -->
					<div class="span-veil"
					use:portal
						onclick={() => (spanFor = null)}
						onkeydown={(e) => e.key === 'Enter' && (spanFor = null)}
						role="button"
						tabindex="-1"
						aria-label="Закрити"></div>
					<div class="w-spanpop" use:portal
					style="left:{popX}px; top:{popY}px">
						<span class="text-faint small">Ширина віджета</span>
						{#each WIDGET_SIZES.filter(
								(sz) => sz.span >= 4 || w.key === 'stats'
							) as sz (sz.span)}
							<button
								class="sz"
								class:on={w.span === sz.span}
								onclick={() => {
									widgets.setSpan(w.key, sz.span);
									spanFor = null;
								}}>
								<span class="sz-bar" aria-hidden="true">
									{#each Array(12) as _, ci (ci)}
										<span class="c" class:f={ci < sz.span}></span>
									{/each}
								</span>
								<span class="sz-l">{sz.label}</span>
							</button>
						{/each}
					</div>
				{/if}
			{/if}
			{#if w.key === 'stats'}
				{@render wStats(d)}
			{:else if w.key === 'deadlines'}
				{@render wDeadlines(d)}
			{:else if w.key === 'lessons'}
				{@render wLessons(d)}
			{:else if w.key === 'marks'}
				{@render wMarks()}
			{:else if w.key === 'activity'}
				{@render wActivity()}
			{:else if w.key === 'news'}
				{@render wNews()}
			{:else if w.key === 'board'}
				{@render wBoard(w.span)}
			{/if}
		{/snippet}

				{#if editHome}
					<div class="home-bar">
						<div class="flex-sp"></div>
						<div class="presets">
							{#each Object.entries(PRESETS) as [pk, p] (pk)}
								<button class="pal-chip" onclick={() => widgets.preset(pk)}>
									{p.name}</button>
							{/each}
						</div>
						<button
							class="pal-chip"
							class:on={wgLinks}
						title="Показувати кнопки «Усі …» унизу віджетів"
						onclick={() => setWgLinks(!wgLinks)}>
						{wgLinks ? '✓ ' : ''}Переходи «Усі»</button>
						<button class="btn f" onclick={() => (editHome = false)}>Готово</button>
					</div>
					<div class="palette glass">
						<span class="text-dim small">Додати/прибрати:</span>
							{#each WIDGET_DEFS as d (d.key)}
								<button class="pal-chip" class:on={widgets.isOn(d.key)}
									title={d.desc}
									onclick={() => widgets.toggle(d.key)}>
									{#if widgets.isOn(d.key)}✓ {/if}{d.label}
								</button>
							{/each}
					</div>
				{/if}

				<div
			class="grid"
			class:dragging-any={!!dragKey}
			class:hide-links={!wgLinks}
			class:scrolling={scrolling}
			use:tapGuard={8}
			use:stagger={{ step: 45, scale: true, y: 16, max: 8 }}
			in:fade={{ duration: 150 }}
		>
			{#each widgets.list as w, wi (w.key)}
				{#if dragKey === w.key}
					<!-- плаваючий бокс: поза потоком сітки, їде за курсором -->
					<article
						class="glass card w-floating"
						style="left:{dragX - dragOffX}px; top:{dragY - dragOffY}px; width:{dragW}px"
					>
						{@render wCardInner(w, wi, dash)}
					</article>
				{:else}
					<div
						class="w-item span-{w.span}"
						class:has-h={!!w.h}
						style={`--i:${wi};${w.h ? `height:${w.h}px` : ''}`}
						data-wkey={w.key}
						in:widgetIn={w.key}
						out:widgetOut
					>
						<article
							class="glass card"
							class:stats={w.key === 'stats'}
							class:editing={editHome}
							class:w-land={justDropped === w.key}
							class:lift={!editHome}
							use:spotlight
							onpointerdown={(e) => wPointerDown(e, w.key)}
						>
							{@render wCardInner(w, wi, dash)}
						</article>
						{#if editHome && dragKey !== w.key}
							<span class="w-rz" role="separator" aria-orientation="vertical"
								title="Тягни — зміниш ширину"
								onpointerdown={(e) => rzDown(e, w.key)}></span>
							<span class="w-vrz" role="separator" aria-orientation="horizontal"
								title="Тягни — зміниш висоту"
								onpointerdown={(e) => vrzDown(e, w.key)}></span>
						{/if}
					</div>
				{/if}
				{/each}
		</div>

<style>

	/* ================= сітка дашборду ================= */

	.grid {
		display: grid;
		grid-template-columns: repeat(12, 1fr);
		/* dense: пізніші менші бокси затягуються в дірки вище —
		 * «швидка стиковка» без ручного вирівнювання */
		grid-auto-flow: row dense;
		gap: 14px;
		align-content: start;
	}

	.card {
		padding: 18px;
		border-radius: var(--radius-lg);
		display: flex;
		flex-direction: column;
		gap: 12px;
		min-width: 0;
	}

	.span-5 { grid-column: span 5; }
	.span-7 { grid-column: span 7; }
	.span-12 { grid-column: span 12; }

		/* показники: сітка плиток — щільно по висоті на будь-якій ширині.
	 Зайва висота (високий ряд/явна висота) розтягує плитки й числа
	 центруються, а не лишає порожнечу знизу */
	.w-item > article.stats {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(104px, 1fr));
		gap: 8px;
		padding: 12px;
		flex: 1 1 auto;
		min-height: 0;
		align-content: stretch;
	}

	/* плитка — ледь помітний шар: пів кроку світла між карткою
	 (glass-bg) і ховером, рамка ледве-ледве. Помітно, тільки
	 якщо придивитись — у будь-якій темі */
	.stat {
		display: flex;
		flex-direction: column;
		justify-content: center;
		gap: 2px;
		min-width: 0;
		background: color-mix(in srgb, var(--glass-bg) 50%, var(--glass-bg-hover));
		border: 1px solid color-mix(in srgb, var(--glass-border) 45%, transparent);
		cursor: pointer;
		text-align: left;
		padding: 10px 12px;
		border-radius: var(--radius-md);
		transition: background 0.15s ease, border-color 0.15s ease;
	}

	.stat:hover {
		background: var(--accent-soft);
		border-color: color-mix(in srgb, var(--accent) 40%, transparent);
	}

	.stat:hover {
		background: var(--glass-bg);
	}

	.s-label {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		max-width: 100%;
		font-size: 12px;
		color: var(--text-dim);
		font-weight: 600;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.s-label :global(svg) {
		color: var(--accent);
		transition: transform 420ms var(--ease-spring);
	}

	/* іконка плитки «вистрибує» на hover */
	@media (hover: hover) and (pointer: fine) {
		.stat:hover .s-label :global(svg) {
			transform: scale(1.3) rotate(-8deg);
		}
	}

	.s-value {
		font-family: var(--font-display);
		font-weight: 900;
		font-size: 26px;
		line-height: 1.15;
	}

	h2 {
		font-size: 15px;
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}

	.rows-list {
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: 9px;
	}

	.rows-list li {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.l-info {
		display: flex;
		flex-direction: column;
		gap: 1px;
		flex: 1;
		min-width: 100px;
		font-size: 13.5px;
	}

	/* довга назва не виштовхує чипи */
	.l-info b,
	.l-info > span {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.due-chip {
		background: var(--surface-2);
		border-radius: 999px;
		padding: 4px 10px;
		font-size: 12px;
		font-weight: 700;
		white-space: nowrap;
	}

	/* База — нейтральна; колір задає mkCls (hi/mid/low), як у віджетах */

	.small {
		font-size: 11.5px;
	}

	.mono {
		font-family: ui-monospace, Consolas, monospace;
		font-size: 11.5px;
	}

	/* ================= розклад ================= */

	.flex-sp {
		flex: 1;
	}

	.btn.f {
		font-size: 13px;
		padding: 7px 12px;
	}

	/* Рядок уроку = стиль віджета «Сьогодні»: прозорий рядок з м'яким
	   hover замість плаского сірого бокса; час — жирний праворуч. */
	.lesson {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 9px 10px;
		background: transparent;
		border-radius: var(--radius-sm);
		transition: background 0.14s ease;
	}

	/* ── оцінки та екзамени ── */

	.mk {
		position: absolute;
		top: -6px;
		right: -5px;
		min-width: 21px;
		height: 21px;
		padding: 0 5px;
		border-radius: 11px;
		/* Фікс: цифра була не по центру кола. display:grid +
		 * place-items:center центрує РЯДКОВИЙ БОКС тексту, а не гліф:
		 * успадкований line-height (≈1.5) зсував гліф угору.
		 * flex + явний line-height:1 центрує саму цифру. */
		display: flex;
		align-items: center;
		justify-content: center;
		line-height: 1;
		font-size: 11.5px;
		font-weight: 800;
		color: #fff;
		box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
		z-index: 1;
	}

	.mk.hi {
		background: var(--success);
	}

	.mk.mid {
		background: var(--amber);
	}

	.mk.low {
		background: var(--danger);
	}

	.mk.ex {
		box-shadow: 0 0 0 2px var(--amber), 0 2px 8px rgba(0, 0, 0, 0.35);
	}

	.lesson.exam {
		border-left: 3px solid var(--amber);
	}

	.ex-tag {
		flex-shrink: 0;
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 4px 9px;
		border-radius: 999px;
		font-size: 10px;
		font-weight: 800;
		color: var(--amber);
		background: color-mix(in srgb, var(--amber) 13%, transparent);
		border: 1px solid color-mix(in srgb, var(--amber) 34%, transparent);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

			/* базово — дві колонки (без оцінок): час впритул праворуч */
	.tl-list .lesson {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 10px;
		background: transparent;
		border-radius: var(--radius-sm);
		padding: 8px 10px;
		transition: background 0.14s ease;
	}

	.tl-list .lesson:hover {
		background: var(--glass-bg);
	}

	/* «живий» урок: акцентний фон, дихаюча крапка, смужка прогресу */
	.tl-list .lesson {
		position: relative;
	}
	.tl-list .lesson.live {
		background: color-mix(in srgb, var(--accent) 9%, transparent);
	}
	.tl-list .lesson.next {
		background: color-mix(in srgb, var(--accent) 4%, transparent);
		box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 22%, transparent);
	}
	.live-dot {
		display: inline-block;
		width: 7px;
		height: 7px;
		margin-right: 6px;
		vertical-align: 1px;
		border-radius: 50%;
		background: var(--success, var(--accent));
	}
	.st-tag {
		display: inline-block;
		margin-left: 6px;
		padding: 1px 7px;
		border-radius: 999px;
		font-size: 9.5px;
		font-weight: 800;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		vertical-align: 1px;
	}
	.st-tag.now {
		color: var(--accent);
		background: var(--accent-soft);
	}
	.st-tag.nx {
		color: var(--text-dim);
		background: var(--surface-2);
	}
	.les-prog {
		position: absolute;
		left: 10px;
		right: 10px;
		bottom: 1px;
		height: 2px;
		border-radius: 2px;
		overflow: hidden;
		background: color-mix(in srgb, var(--accent) 16%, transparent);
		pointer-events: none;
	}
	.les-prog > i {
		display: block;
		height: 100%;
		background: var(--accent);
		transform-origin: left center;
		/* тік раз на 30с — довга м'яка інтерполяція між значеннями */
		transition: transform 1.6s var(--ease-out);
		animation: prog-in 0.5s var(--ease-out) 0.15s backwards;
	}
	@keyframes prog-in {
		from {
			transform: scaleX(0);
		}
	}
	:global(html[data-anim="off"]) .live-dot,
	:global(html[data-anim="off"]) .les-prog > i {
		animation: none;
	}

	.tl-list .les-time {
		margin-left: auto;
		white-space: nowrap;
	}

	/* є хоч одна оцінка/«Н» => весь віджет отримує третю колонку-слот */
	.tl-list.has-marks .lesson {
		grid-template-columns: minmax(0, 1fr) auto 28px;
	}

	/* слот оцінки: фіксована колонка, чип по центру */
	.tl-list .les-slot {
		display: flex;
		align-items: center;
		justify-content: center;
		min-width: 28px;
	}

	/* кабінет у другому рядку — окремий колір, не штовхає час */
	.tl-list .les-room {
		color: var(--text-faint);
		white-space: nowrap;
	}
	.tl-list .dot-sep {
		font-style: normal;
		margin: 0 5px;
		color: var(--text-faint);
	}

	/* Фікс «оцінки злетіли у куток віджета»: .mk — position:absolute
	 * (куток КОМІРКИ тижневої сітки, де батько має position:relative).
	 * У віджеті «Сьогодні» рядок уроку без positioned-контексту, тому
	 * ВСІ чипи оцінок анкорились до картки віджета і кучкувались у її
	 * правому верхньому куті. Тут чип — звичайний елемент слота. */
	.tl-list .mk {
		position: static;
	}

/* «Не був» — помітний мінус-чип (стилів не було взагалі) */
	.nk {
		flex-shrink: 0;
		display: inline-flex;
		align-items: baseline;
		gap: 3px;
		white-space: nowrap;
		font-feature-settings: 'tnum';
	}

	.les-time b {
		font-size: 13.5px;
		font-weight: 800;
		color: var(--text);
	}

	.les-time i {
		font-style: normal;
		font-size: 12px;
		font-weight: 600;
		color: var(--text-faint);
	}

	/* «Не був» — помітний мінус-чип (стилів не було взагалі) */
	.nk {
		flex-shrink: 0;
		min-width: 22px;
		height: 22px;
		padding: 0 6px;
		border-radius: 8px;
		display: inline-grid;
		place-items: center;
		font-size: 12px;
		font-weight: 800;
		color: var(--danger);
		background: color-mix(in srgb, var(--danger) 13%, transparent);
		border: 1px solid color-mix(in srgb, var(--danger) 32%, transparent);
	}

	/* сітка плиток: 1 колонка на телефоні → 3-4 на широкому ПК */

	.due-chip.late {
		color: var(--danger);
		border-color: rgba(248, 113, 113, 0.35);
		background: rgba(248, 113, 113, 0.08);
	}

	/* день — як заголовки місяців у домашці/оцінках */
	.feed-date {
		font-size: 13px;
		font-weight: 800;
		color: var(--text);
		text-transform: capitalize;
		margin: 14px 2px 0;
	}

	.feed-icon {
		width: 38px;
		height: 38px;
		border-radius: 10px;
		flex-shrink: 0;
		display: grid;
		place-items: center;
		background: var(--surface-2);
		color: var(--text-faint);
		position: relative;
		overflow: hidden;
	}

	/* іконка події з MyStat — ТІЛЬКИ для нерозпізнаних подій (FCls
	 порожній), накрита поверх Lucide-дефолту; не завантажилась —
	 прибирається, лишається Lucide */
	.feed-img {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		object-fit: cover;
	}

	.feed-icon.marked {
		background: var(--accent-soft);
		color: var(--accent);
	}

	/* тіні за типом події: іконка читається одразу */
	.feed-icon.ok {
		color: var(--success);
		background: color-mix(in srgb, var(--success) 13%, transparent);
	}

	.feed-icon.shop,
	.feed-icon.coin {
		color: var(--amber);
		background: color-mix(in srgb, var(--amber) 14%, transparent);
	}

	.feed-icon.ach {
		color: var(--cyan);
		background: color-mix(in srgb, var(--cyan) 13%, transparent);
	}

	.feed-icon.gem,
	.feed-icon.lesson {
		color: var(--accent);
		background: var(--accent-soft);
	}

	.mark-num {
		font-family: var(--font-display);
		font-weight: 800;
		font-size: 15px;
	}

	.award {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-weight: 800;
		font-size: 13.5px;
	}

	.award.cristals {
		color: var(--accent);
	}

	.award.coins {
		color: var(--amber);
	}

	.award.achivements {
		color: var(--cyan);
	}

	/* ── захист плиток від «мімо-кліків» під час скрола ──
	   1) cooldown: 160мс після останньої scroll-події клік/hover
	      по картках не проходить (pointer-events: none);
	   2) tapGuard (use: на .grid) гасить кліки зі зсувом >8px
	      від точки натискання;
	   3) touch-action: pan-y — вертикальний жест завжди віддається
	      скролу; драг/резайз у режимі редагування живуть на грипі
	      та ресайзерах із touch-action: none. */
	.grid.scrolling article:not(.w-floating) {
		pointer-events: none;
	}

	.grid > .w-item > article {
		touch-action: pan-y;
	}

	.w-grip,
	.w-rz,
	.w-vrz {
		touch-action: none;
	}

	@media (max-width: 900px) {

		/* будь-яка ширина віджета -> на всю колонку телефону */
		.span-4, .span-5, .span-6, .span-7, .span-8 {
			grid-column: span 12;
		}

		/* віджети на телефоні: компактніше, щільніше, живіше */
		.grid {
			gap: 10px;
		}

		.card {
			padding: 14px;
			border-radius: 18px;
		}

		.w-item > article.stats {
			gap: 6px;
			padding: 10px;
			grid-template-columns: repeat(auto-fit, minmax(96px, 1fr));
		}

		.stats .stat {
			padding: 8px 10px;
		}

		.s-value {
			font-size: 22px;
		}

	}

	@media (min-width: 901px) and (max-width: 1180px) {
		.span-5 {
			grid-column: span 12;
		}

		.span-7 {
			grid-column: span 12;
		}
	}

	/* ============ Новини на Головній ============ */

	.news-head {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-bottom: 12px;
	}

	.news-head h2 {
		font-size: 1.15rem;
	}

	.news-unread {
		display: inline-grid;
		place-items: center;
		min-width: 22px;
		height: 22px;
		padding: 0 7px;
		border-radius: 999px;
		background: var(--cyan);
		color: #06232b;
		font-family: var(--font-body);
		font-size: 0.78rem;
		font-weight: 700;
		vertical-align: 3px;
	}

	.news-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
		gap: 10px;
	}

	.news-item {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 8px;
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-md);
		background: var(--glass-bg);
		color: var(--text);
		font: inherit;
		text-align: left;
		cursor: pointer;
		transition: background 0.15s;
	}

	.news-item:hover {
		border-color: var(--accent-soft);
	}

	.news-item img,
	.news-item .ph {
		width: 58px;
		height: 58px;
		flex: 0 0 58px;
		border-radius: var(--radius-sm);
		object-fit: cover;
	}

	.news-item .ph {
		display: grid;
		place-items: center;
		background: var(--surface-2);
		font-size: 20px;
	}

	.news-item .t {
		display: flex;
		flex-direction: column;
		gap: 3px;
		min-width: 0;
	}

	.news-item .t b {
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
		font-size: 0.88rem;
		line-height: 1.3;
		font-weight: 600;
	}

	.new-mark {
		color: var(--cyan);
	}

	/* ============ Система віджетів Головної ============ */

	.home-bar {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-bottom: 12px;
	}

	.presets {
		display: flex;
		gap: 6px;
	}

	.palette {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
		padding: 10px 14px;
		margin-bottom: 14px;
		border-radius: var(--radius-md);
	}

	.pal-chip {
		padding: 6px 12px;
		border: 1px solid var(--glass-border);
		border-radius: 999px;
		background: var(--glass-bg);
		color: var(--text-dim);
		font: inherit;
		font-size: 0.82rem;
		cursor: pointer;
		transition: background 0.15s;
	}

	.pal-chip:hover {
		color: var(--text);
	}

	.pal-chip.on {
		background: var(--accent);
		border-color: transparent;
		color: #fff;
	}

		/* панель редагування — оверлей: жодного впливу на розкладку
	 вмісту (критично для сітки показників без заголовка) */
	.w-ctl {
		position: absolute;
		top: 6px;
		right: 10px;
		z-index: 30;
		display: flex;
		gap: 6px;
		padding: 3px;
		background: color-mix(in srgb, var(--bg) 82%, transparent);
		-webkit-backdrop-filter: blur(8px);
		backdrop-filter: blur(8px);
		border: 1px solid var(--glass-border);
		border-radius: 10px;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.28);
	}

	.w-ctl button {
		min-width: 30px;
		height: 26px;
		padding: 0 8px;
		display: grid;
		place-items: center;
		border: 1px solid var(--glass-border);
		border-radius: 8px;
		background: var(--surface-2);
		color: var(--text-dim);
		font: inherit;
		font-size: 0.72rem;
		cursor: pointer;
	}

	.w-ctl button:hover:not(:disabled) {
		color: var(--text);
		border-color: var(--accent);
	}

	.w-ctl button:disabled {
		opacity: 0.35;
		cursor: default;
	}

	.w-ctl .w-del:hover:not(:disabled) {
		color: var(--danger);
		border-color: var(--danger);
	}

	/* Режим редагування: ніжне iOS-«тремтіння» (±0.4°, фази чергуються).
	 * !important — глобальна поява карток (tokens.css) задає свій animation
	 * з вищою специфічністю; тут її вимкнено, вхід веде use:stagger. */
	article.editing {
		outline: 1.5px dashed var(--glass-border);
		outline-offset: 4px;
	}

	.grid > .w-item > article.card {
		animation: none !important;
	}

	.grid > .w-item > article.card.editing {
		animation: w-jiggle 0.42s ease-in-out infinite alternate !important;
	}

	/* різна фаза — рух живіший, картки не хитаються синхронно */
	.grid > .w-item:nth-child(2n) > article.card.editing {
		animation-direction: alternate-reverse !important;
	}
	.grid > .w-item:nth-child(3n) > article.card.editing {
		animation-delay: -0.17s !important;
	}

	@keyframes w-jiggle {
		from {
			transform: rotate(-0.4deg);
		}
		to {
			transform: rotate(0.4deg);
		}
	}

	:global(html[data-anim='off']) .grid > .w-item > article.card.editing {
		animation: none !important;
	}

	/* перетягування: обгортка — елемент сітки; ручки живуть на ній,
	 тому overflow картки їх ніколи не обрізає */
	.w-item {
		position: relative;
		min-width: 0;
		display: flex;
		flex-direction: column;
	}

	.w-item > article,
	article.w-floating {
		/* flex-колонка: тіло віджета розтягується на залишок, «Усі»
		 пріліпає до низу; shrink 1 + min-height 0 — картка реально
		 стискається до висоти обгортки (скрол у .has-h і в .wg-body) */
		display: flex;
		flex-direction: column;
		flex: 1 1 auto;
		min-height: 0;
	}

	/** Біла смуга-роздільник: тягни — міняєш ширину сусідніх боксів. */
	.w-rz {
		position: absolute;
		top: 10px;
		bottom: 10px;
		right: -13px;
		width: 14px;
		z-index: 7;
		cursor: col-resize;
		touch-action: none;
	}

	.w-rz::before {
		content: '';
		position: absolute;
		top: 0;
		bottom: 0;
		left: 50%;
		width: 3px;
		transform: translateX(-50%);
		border-radius: 3px;
		background: color-mix(in srgb, var(--accent) 55%, transparent);
		transition: background 0.15s, box-shadow 0.15s;
	}

	.w-rz:hover::before {
		background: var(--accent);
		box-shadow: 0 0 12px var(--accent-soft);
	}

	/** Вертикальна ручка висоти: нижній край картки. */
	.w-vrz {
		position: absolute;
		left: 14px;
		right: 14px;
		bottom: -13px;
		height: 18px;
		z-index: 7;
		cursor: row-resize;
		touch-action: none;
	}

	.w-vrz::before {
		content: '';
		position: absolute;
		left: 14px;
		right: 14px;
		top: 50%;
		height: 3px;
		transform: translateY(-50%);
		border-radius: 3px;
		background: color-mix(in srgb, var(--accent) 55%, transparent);
		transition: background 0.15s, box-shadow 0.15s;
	}

	.w-vrz:hover::before {
		background: var(--accent);
		box-shadow: 0 0 12px var(--accent-soft);
	}

	/* явна висота: контент скролиться всередині картки */
	.w-item.has-h > article {
		overflow-y: auto;
	}

	/* адаптивні віджети: тіло = залишок висоти картки. Скрол —
	 всередині тіла (коли бокс зовсім низький), «Усі» приліплена
	 до низу картки й ніколи не обрізається */
	.wg-body {
		flex: 1 1 auto;
		min-height: 0;
		overflow-y: auto;
		/* авто-картка: компактний прев'ю з внутрішнім листанням;
		 розтягнеш бокс (явна висота) — тіло займе весь залишок */
		max-height: 22rem;
	}

	.w-item.has-h .wg-body {
		max-height: none;
	}

	/* «Усі …» — прилиплена до низу картки: margin:auto працює коли є
	 вільне місце, padding тримає зазор коли картка по контенту */
	.wg-all {
		margin-top: auto;
		padding-top: 10px;
	}

	/* переходи вимкнено — ховаємо всі «Усі …» (і «Усі оцінки»
	 всередині компонента оцінок) */
	.grid.hide-links .wg-all {
		display: none;
	}

	.grid.hide-links :global(.mk-all) {
		display: none;
	}

	.wg-more {
		display: grid;
		place-items: center;
		padding: 8px 0 2px;
	}

	/* нарахування у віджеті: групи-дні як у вкладці (заголовок над
	 групою подій, без чіпа біля кожної події) */
	.rows-list li.wg-item {
		display: block;
	}

	.wg-row {
		display: flex;
		align-items: center;
		gap: 10px;
	}

	.wg-day {
		margin: 10px 2px 4px;
	}

	/* оцінки: корінь компонента розтягуємо, «Усі оцінки» — до низу.
	 max-height: none — тіло росте разом із контентом (не ріже сітку
	 оцінок, коли вона трохи вища за стандартний ліміт 22rem),
	 картка просто стає вищою, «Усі оцінки» прилипає до її низу */
	.wg-body.mkw {
		display: flex;
		flex-direction: column;
		overflow: visible;
		max-height: none;
	}

	.w-item > article :global(.mk) {
		flex: 1 1 auto;
		min-height: 0;
		display: flex;
		flex-direction: column;
	}

	.w-item > article :global(.mk-scroll) {
		flex: 1 1 auto;
		min-height: 0;
		overflow-y: auto;
	}

	.w-item > article :global(.mk-scroll.scrollable) {
		max-height: none;
	}

	.w-item > article :global(.mk-all) {
		margin-top: 10px;
		align-self: flex-start;
	}

	/* плаваючий бокс: напівпрозорий, їде за курсором, а сітка живе
	 без нього (position:fixed виводить його з потоку сітки) */
	article.w-floating {
		position: fixed;
		z-index: 40;
		opacity: 0.78;
		pointer-events: none;
		transform: scale(1.03) rotate(-0.6deg);
		box-shadow: var(--shadow-lg), 0 24px 60px rgba(0, 0, 0, 0.55);
		animation: w-lift 0.28s var(--ease-spring) backwards;
		margin: 0;
		will-change: left, top;
	}

	/* «приземлення» після drop робить FLIP у flipDrop() (WAAPI) */
	@keyframes w-lift {
		from {
			transform: scale(1) rotate(0deg);
			box-shadow: var(--shadow-md);
		}
	}

	/* під час перетягування сітка затихає: тряска зникає в усіх боксів,
	 курсор grabbing — видно, що тягнеться саме бокс, а не сторінка */
	.grid.dragging-any > .w-item > article.card.editing {
		animation: none !important;
	}

	.grid.dragging-any {
		cursor: grabbing;
		user-select: none;
	}

	.w-item > article.editing {
		user-select: none;
	}

	/* тач-драг гарантовано працює з грипа */
	.w-grip {
		touch-action: none;
	}

	.w-grip {
		display: grid;
		place-items: center;
		height: 26px;
		padding: 0 6px;
		color: var(--text-faint);
		font-size: 0.9rem;
		cursor: grab;
		user-select: none;
	}

	.w-ctl button {
		cursor: pointer;
	}

	/* пікер ширини: людські назви + міні-бар 12 сегментів */
	.span-veil {
		position: fixed;
		inset: 0;
		z-index: 55;
	}

	.w-spanpop {
		position: fixed;
		z-index: 60;
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 10px;
		border: 1px solid var(--glass-border);
		border-radius: 12px;
		background: var(--surface-2);
		box-shadow: 0 14px 34px rgba(0, 0, 0, 0.45);
	}

	.w-spanpop .sz {
		display: flex;
		align-items: center;
		gap: 10px;
		width: 168px;
		padding: 5px 8px;
		border: 0;
		border-radius: 8px;
		background: transparent;
		color: var(--text-dim);
		font: inherit;
		font-size: 0.82rem;
		text-align: left;
		cursor: pointer;
	}

	.w-spanpop .sz:hover {
		background: var(--accent-soft);
		color: var(--text);
	}

	.w-spanpop .sz.on {
		background: var(--accent-soft);
		color: var(--accent-text, var(--text));
	}

	.w-spanpop .sz.on .sz-l {
		font-weight: 700;
	}

	.sz-bar {
		display: inline-flex;
		gap: 1.5px;
		flex: 0 0 72px;
	}

	.sz-bar .c {
		width: 4.5px;
		height: 12px;
		border-radius: 1.5px;
		background: var(--surface-2);
		outline: 1px solid rgba(255, 255, 255, 0.06);
	}

	.sz-bar .c.f {
		background: var(--accent);
	}

	/* додаткові ширини віджетів */
	.span-4 {
		grid-column: span 4;
	}
	.span-6 {
		grid-column: span 6;
	}
	.span-8 {
		grid-column: span 8;
	}
	.span-9 {
		grid-column: span 9;
	}
	.span-10 {
		grid-column: span 10;
	}
	.span-11 {
		grid-column: span 11;
	}

	/* міні-лідерборд */
	.me-chip-sm {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 5px 10px;
		border: 1px solid rgba(255, 180, 84, 0.35);
		border-radius: 999px;
		background: rgba(255, 180, 84, 0.12);
		color: var(--amber);
		font-size: 0.8rem;
		margin-bottom: 8px;
	}

	.me-chip-sm {
		margin-bottom: 0;
	}

	/* перемикачі віджета (як у MyStat: Група | Потік, 30 днів | Весь період) */
	.b-swrow {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
		margin-bottom: 10px;
	}

	.b-sw {
		display: inline-flex;
		gap: 2px;
		padding: 2px;
		border-radius: 999px;
		background: var(--surface-2);
	}

	.b-sw button {
		border: 0;
		background: transparent;
		color: var(--text-dim);
		font: inherit;
		font-size: 0.76rem;
		padding: 4px 11px;
		border-radius: 999px;
		cursor: pointer;
		white-space: nowrap;
	}

	.b-sw button.active {
		background: var(--accent);
		color: #fff;
		font-weight: 600;
	}

	/* плоский список як в оригіналі: ①②③, ⋯, моє ім'я акцентом */
	.b-list {
		display: flex;
		flex-direction: column;
	}

	.b-list.wide {
		display: block;
		columns: 2;
		column-gap: 24px;
	}

	.b-list .b-row,
	.b-list .b-gap {
		break-inside: avoid;
	}

	.b-row {
		display: flex;
		align-items: center;
		gap: 9px;
		padding: 5.5px 8px;
		border-radius: 10px;
		min-width: 0;
	}

	.b-row.me {
		position: relative;
		background: var(--accent-soft);
	}

	/* «моє місце»: м'яка акцентна пульсація один раз (лише opacity) */
	.b-row.me::after {
		content: '';
		position: absolute;
		inset: 0;
		border-radius: inherit;
		pointer-events: none;
		box-shadow:
			0 0 0 1.5px color-mix(in srgb, var(--accent) 70%, transparent),
			0 0 20px var(--accent-soft);
		opacity: 0;
		animation: me-glow 1.5s var(--ease-out) 0.4s 1;
	}

	@keyframes me-glow {
		0%,
		100% {
			opacity: 0;
		}
		35% {
			opacity: 1;
		}
	}

	.b-row.me .fio {
		color: var(--accent);
	}

	.b-row .fio {
		font-size: 0.87rem;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.bmedal {
		width: 21px;
		height: 21px;
		flex: 0 0 21px;
		display: grid;
		place-items: center;
		border-radius: 50%;
		font-size: 0.68rem;
		font-weight: 800;
		color: #241a00;
	}

	.bmedal.m1 {
		background: #ffd35c;
	}

	.bmedal.m2 {
		background: #c9d4e4;
	}

	.bmedal.m3 {
		background: #e0985a;
	}

	.bnum {
		min-width: 21px;
		text-align: center;
		color: var(--text-faint);
		font-size: 0.8rem;
	}

	.bseed {
		width: 21px;
		text-align: center;
	}

	.b-gap {
		text-align: center;
		color: var(--text-faint);
		letter-spacing: 4px;
		padding: 0;
		line-height: 1.1;
	}

	.b-ava {
		width: 30px;
		height: 30px;
		flex: 0 0 30px;
		border-radius: 50%;
		object-fit: cover;
	}

	.b-ava.ini {
		display: grid;
		place-items: center;
		background: var(--accent-soft);
		color: var(--accent);
		font-size: 0.62rem;
		font-weight: 700;
	}

	@media (max-width: 980px) {
		.grid > .w-item,
		.grid > .w-floating {
			grid-column: 1 / -1;
		}
		.presets {
			display: none;
		}
		/* телефон/планшет: ширина завжди на весь екран — ручка ширини
		 і кнопка «Ширина» зайві. Висоту міняє нижня ручка .w-vrz */
		.w-rz,
		.w-ctl .w-span {
			display: none;
		}
	}

</style>
