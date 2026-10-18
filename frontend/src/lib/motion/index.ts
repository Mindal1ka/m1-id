/**
 * M1 ID · система руху (motion v2).
 *
 * Принципи:
 *  - лише transform/opacity (композитор). `filter: blur` — тільки для
 *    одиночних елементів і лише на рівні продуктивності «full»;
 *  - пружини замість лінійних таймінгів;
 *  - два рівні продуктивності: html[data-perf="full" | "lite"] — визначається
 *    автоматично (пам'ять/ядра/Save-Data/заміряний FPS) або вручну в налаштуваннях.
 *    У «lite» лишаються ВСІ анімації руху, зникають лише дорогі ефекти
 *    (blur, прожектор, нахил, backdrop-filter);
 *  - усе вимикається при prefers-reduced-motion АБО «Анімація появи» = «Вимк».
 * Правила застосування — docs/MOTION.md.
 */

import type { Action } from 'svelte/action';
import type { TransitionConfig } from 'svelte/transition';
import { cubicOut, backOut } from 'svelte/easing';

/* ---------------- криві ---------------- */

/** Пружинні криві для WAAPI (linear() апроксимує пружину; є фолбек). */
export const EASE = {
	out: 'cubic-bezier(0.22, 1, 0.36, 1)',
	inOut: 'cubic-bezier(0.65, 0, 0.35, 1)',
	/** м'яка пружина з легким перельотом */
	spring:
		'linear(0, 0.009, 0.035 2.1%, 0.141 4.4%, 0.723 12.9%, 0.938 16.7%, 1.017 19.4%, 1.067, 1.099 24.3%, 1.108 26%, 1.100 28.1%, 1.078 30.5%, 1.003 38.6%, 0.984 42.8%, 0.979 46.5%, 0.983 50.9%, 0.998 63.3%, 1.002 72.8%, 1)',
	/** пружина для натискання (швидка, з маленьким відскоком) */
	snappy:
		'linear(0, 0.08 2%, 0.35 6%, 0.7 11%, 0.95 16%, 1.04 20%, 1.06 23%, 1.04 28%, 1 36%, 0.995 45%, 1)'
} as const;

let springSupported: boolean | null = null;
/** Крива за назвою (без підтримки CSS linear() — cubic-bezier з перельотом). */
export function ease(name: keyof typeof EASE): string {
	if (name !== 'spring' && name !== 'snappy') return EASE[name];
	if (springSupported === null) {
		springSupported =
			typeof CSS !== 'undefined' && CSS.supports('transition-timing-function', 'linear(0, 1)');
	}
	return springSupported ? EASE[name] : 'cubic-bezier(0.34, 1.56, 0.64, 1)';
}

/* ---------------- дозволи ---------------- */

/** Рух дозволено? (системне reduced-motion + налаштування застосунку). */
export function motionOK(): boolean {
	if (typeof window === 'undefined') return false;
	if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return false;
	return document.documentElement.dataset.anim !== 'off';
}

/** Пристрій з мишею (hover-ефекти лише тут). */
export function canHover(): boolean {
	return typeof window !== 'undefined' && window.matchMedia('(hover: hover) and (pointer: fine)').matches;
}

/* ---------------- рівень продуктивності ---------------- */

export type PerfMode = 'auto' | 'full' | 'lite';
const LS_PERF = 'm1id.perf';

/** Поточний рівень: true = дорогі ефекти дозволено. */
export function fx(): boolean {
	return typeof document !== 'undefined' && document.documentElement.dataset.perf !== 'lite';
}

/** Лише статичні ознаки слабкого пристрою. Рівень вирішується ОДИН раз до
 *  першого кадру (дзеркало в app.html) і не змінюється посеред сесії.
 *  FPS-замір прибрано: він міряв кадри під час стартових анімацій і помилково
 *  вмикав «lite» посеред них — анімація «обривалась» приблизно через секунду. */
export function staticLite(): boolean {
	const n = navigator as Navigator & {
		deviceMemory?: number;
		connection?: { saveData?: boolean };
	};
	if (n.connection?.saveData) return true;
	const mem = typeof n.deviceMemory === 'number' ? n.deviceMemory : 8;
	const cores = typeof n.hardwareConcurrency === 'number' ? n.hardwareConcurrency : 8;
	return mem <= 2 || cores <= 2 || (mem <= 4 && cores <= 4);
}

function setPerfAttr(v: 'full' | 'lite'): void {
	document.documentElement.dataset.perf = v;
}

/** Обраний користувачем режим (auto за замовчуванням). */
export function getPerfMode(): PerfMode {
	try {
		const v = localStorage.getItem(LS_PERF);
		if (v === 'full' || v === 'lite') return v;
	} catch {
		/* приватний режим */
	}
	return 'auto';
}

/** Застосувати режим продуктивності (виклик на старті та з налаштувань). */
export function applyPerf(mode: PerfMode = getPerfMode()): void {
	if (typeof document === 'undefined') return;
	try {
		if (mode === 'auto') localStorage.removeItem(LS_PERF);
		else localStorage.setItem(LS_PERF, mode);
	} catch {
		/* ignore */
	}
	if (mode !== 'auto') {
		setPerfAttr(mode);
		return;
	}
	setPerfAttr(staticLite() ? 'lite' : 'full');
}

/* ---------------- actions ---------------- */

/** Пружне натискання: scale вниз при pointerdown, відскок при відпусканні. */
export const pressable: Action<HTMLElement, { scale?: number } | undefined> = (node, opts) => {
	let scale = opts?.scale ?? 0.96;
	let anim: Animation | null = null;
	const down = (e: PointerEvent) => {
		if (e.button !== 0 || !motionOK() || node.hasAttribute('disabled')) return;
		anim?.cancel();
		anim = node.animate([{ transform: 'scale(1)' }, { transform: `scale(${scale})` }], {
			duration: 120,
			easing: EASE.out,
			fill: 'forwards'
		});
	};
	/** Поточний масштаб (з урахуванням анімації, що ще йде) — щоб відпускання не «стрибало». */
	const currentScale = (): number => {
		try {
			const t = getComputedStyle(node).transform;
			if (!t || t === 'none') return 1;
			const a = new DOMMatrixReadOnly(t).a;
			return Number.isFinite(a) && a > 0 ? a : scale;
		} catch {
			return scale;
		}
	};
	const up = () => {
		if (!anim) return;
		const from = currentScale();
		anim.cancel();
		anim = node.animate([{ transform: `scale(${from})` }, { transform: 'scale(1)' }], {
			duration: 420,
			easing: ease('snappy')
		});
		anim.onfinish = () => (anim = null);
	};
	node.addEventListener('pointerdown', down, { passive: true });
	node.addEventListener('pointerup', up);
	node.addEventListener('pointerleave', up);
	node.addEventListener('pointercancel', up);
	return {
		update(o) {
			scale = o?.scale ?? 0.96;
		},
		destroy() {
			node.removeEventListener('pointerdown', down);
			node.removeEventListener('pointerup', up);
			node.removeEventListener('pointerleave', up);
			node.removeEventListener('pointercancel', up);
		}
	};
};

type RevealOpts = { delay?: number; y?: number; blur?: boolean; once?: boolean } | undefined;

/** Спільний IntersectionObserver для всіх reveal (один замість сотні). */
let revealIO: IntersectionObserver | null = null;
const revealCb = new WeakMap<Element, () => void>();
function getRevealIO(): IntersectionObserver {
	if (!revealIO) {
		revealIO = new IntersectionObserver(
			(entries) => {
				for (const e of entries) {
					if (!e.isIntersecting) continue;
					revealIO!.unobserve(e.target);
					revealCb.get(e.target)?.();
					revealCb.delete(e.target);
				}
			},
			{ rootMargin: '0px 0px -6% 0px' }
		);
	}
	return revealIO;
}

/** Поява при потраплянні у в'юпорт: fade + підйом (+ blur лише на «full»). */
export const reveal: Action<HTMLElement, RevealOpts> = (node, opts) => {
	if (!motionOK() || typeof IntersectionObserver === 'undefined') return;
	const y = opts?.y ?? 14;
	const blur = (opts?.blur ?? false) && fx();
	node.style.opacity = '0';
	revealCb.set(node, () => {
		node.style.opacity = '';
		node.animate(
			[
				{ opacity: 0, transform: `translateY(${y}px)`, ...(blur ? { filter: 'blur(6px)' } : {}) },
				{ opacity: 1, transform: 'none', ...(blur ? { filter: 'blur(0)' } : {}) }
			],
			{ duration: 560, delay: opts?.delay ?? 0, easing: EASE.out, fill: 'backwards' }
		);
	});
	const io = getRevealIO();
	io.observe(node);
	return {
		destroy: () => {
			io.unobserve(node);
			revealCb.delete(node);
			node.style.opacity = '';
		}
	};
};

/** Початковий transform появи за стилем із налаштувань (html[data-anim]):
 *  rise (за замовчуванням) | fade | slide | pop — той самий вибір, що й у CSS-появі. */
function entryFrom(y: number, scale?: boolean): string {
	switch (document.documentElement.dataset.anim) {
		case 'fade':
			return 'none';
		case 'slide':
			return 'translateX(-20px)';
		case 'pop':
			return 'scale(0.94)';
		default:
			return `translateY(${y}px) scale(${scale ? 0.97 : 1})`;
	}
}

/* ---------------- двигун появи (enter engine) ----------------
 * ЄДИНИЙ механізм появи карток/рядків у застосунку (замість глобальної
 * CSS-появи з nth-child, яка рахувала лише 13 елементів і билася з WAAPI).
 *  - анімується КОЖЕН елемент, що з'явився, рівно один раз;
 *  - порядок каскаду — за позицією на екрані: ранг = номер рядка + номер
 *    колонки, тож сітки йдуть діагональною хвилею, а списки — згори вниз;
 *  - поза екраном — без анімації одразу, а при прокрутці (IntersectionObserver
 *    з запасом знизу, тож елемент не «блимає»);
 *  - елементи, додані пізніше (дані догрузились, «показати ще»), теж
 *    анімуються — MutationObserver на контейнері;
 *  - елемент, що вже має власну (Svelte-) анімацію появи, пропускається. */

type EnterCfg = {
	step: number;
	y: number;
	scale: boolean;
	blur: boolean;
	/** максимальний ранг затримки (далі — однакова затримка) */
	cap: number;
};

const entered = new WeakSet<Element>();
/** Конфіг каскаду контейнера — для повторного програвання (replayEnter). */
const engineCfg = new WeakMap<HTMLElement, { cfg: EnterCfg; selector?: string }>();
const pendingCfg = new WeakMap<Element, EnterCfg>();

/** Максимальна сумарна затримка появи одного елемента, мс. */
const MAX_ENTER_DELAY = 600;

function runEnter(el: HTMLElement, cfg: EnterCfg, delay: number): void {
	const blur = cfg.blur && fx();
	el.animate(
		[
			{ opacity: 0, transform: entryFrom(cfg.y, cfg.scale), ...(blur ? { filter: 'blur(10px)' } : {}) },
			// кінцевий opacity не задаємо: анімація повертається до значення з CSS
			// (елементи з opacity<1 не «стрибають»)
			{ transform: 'none', ...(blur ? { filter: 'blur(0px)' } : {}) }
		],
		{
			duration: blur ? 560 : 440,
			delay: Math.min(MAX_ENTER_DELAY, Math.max(0, delay)),
			easing: ease('spring'),
			fill: 'backwards'
		}
	);
}

/** Повторно програти каскад появи для вже змонтованого вмісту (вкладка, що
 *  живе в DOM між візитами): ті самі налаштування, що й у use:stagger, лише
 *  для елементів у видимій області `.content`. */
export function replayEnter(root: HTMLElement | null | undefined): void {
	if (!root || !motionOK()) return;
	requestAnimationFrame(() => {
		const vh = window.innerHeight;
		const content = root.closest(CONTENT_SEL);
		const cr = content?.getBoundingClientRect();
		const top = cr && cr.height > 0 ? cr.top : 0;
		const bottom = cr && cr.height > 0 ? cr.bottom : vh;
		const targets = root.matches('[data-stagger]') ? [root] : [];
		targets.push(...root.querySelectorAll<HTMLElement>('[data-stagger]'));
		const items: { el: HTMLElement; r: DOMRect; cfg: EnterCfg }[] = [];
		for (const c of targets) {
			const reg = engineCfg.get(c);
			if (!reg) continue;
			const els = reg.selector
				? Array.from(c.querySelectorAll<HTMLElement>(reg.selector))
				: (Array.from(c.children) as HTMLElement[]);
			for (const el of els) {
				const r = el.getBoundingClientRect();
				if (r.width === 0 || r.bottom < top || r.top > bottom) continue;
				items.push({ el, r, cfg: reg.cfg });
			}
		}
		if (!items.length) return;
		const ranks = rankOf(items);
		items.forEach(({ el, cfg }, i) => {
			if (busyAnimating(el)) return;
			runEnter(el, cfg, Math.min(ranks[i], cfg.cap) * cfg.step);
		});
	});
}

/** Чи вже має елемент власну скінченну анімацію (Svelte in:, WAAPI). */
function busyAnimating(el: HTMLElement): boolean {
	if (typeof el.getAnimations !== 'function') return false;
	for (const a of el.getAnimations()) {
		if (typeof CSSTransition !== 'undefined' && a instanceof CSSTransition) continue;
		const it = a.effect?.getTiming().iterations;
		if (it === Infinity) continue;
		if (a.playState === 'running' || a.pending) return true;
	}
	return false;
}

/** Позиційний ранг: рядок (за top) + колонка (за left). */
function rankOf(items: { el: HTMLElement; r: DOMRect }[]): number[] {
	/** Номер кластера кожного значення: сортуємо, новий кластер — якщо
	 *  розрив від попереднього значення > 8px (стабільно, без «злипання»). */
	const cluster = (vals: number[]): number[] => {
		const idx = vals.map((v, i) => [v, i] as const).sort((a, b) => a[0] - b[0]);
		const out = new Array<number>(vals.length);
		let c = -1;
		let prev = -Infinity;
		for (const [v, i] of idx) {
			if (v - prev > 8) c++;
			prev = v;
			out[i] = c;
		}
		return out;
	};
	const rows = cluster(items.map(({ r }) => r.top));
	const cols = cluster(items.map(({ r }) => r.left));
	return items.map((_, i) => rows[i] + cols[i]);
}

/** Пачки, що йдуть одна за одною (дані рендеряться частинами), продовжують
 *  каскад, а не стартують з нуля: зсув = залишок затримки попередньої пачки. */
let lastBatchAt = 0;
let lastBatchEnd = 0;
function batchBase(): number {
	const now = performance.now();
	const left = lastBatchEnd - (now - lastBatchAt);
	return left > 0 ? left : 0;
}

/** Прокручуваний контейнер застосунку: IntersectionObserver для елементів усередині
 *  нього має root = `.content` (інакше шапка/нижня панель спотворюють «видимість»). */
const CONTENT_SEL = '.content';
const enterIOs = new Map<Element | null, IntersectionObserver>();
const ioOf = new WeakMap<Element, IntersectionObserver>();
let ioBatch: HTMLElement[] = [];
let ioRaf = 0;

function onEnterIO(entries: IntersectionObserverEntry[]): void {
	for (const e of entries) {
		if (!e.isIntersecting) continue;
		ioOf.get(e.target)?.unobserve(e.target);
		ioOf.delete(e.target);
		ioBatch.push(e.target as HTMLElement);
	}
	if (ioBatch.length && !ioRaf) {
		ioRaf = requestAnimationFrame(() => {
			ioRaf = 0;
			const batch = ioBatch.filter((el) => el.isConnected && pendingCfg.has(el));
			ioBatch = [];
			const items = batch.map((el) => ({ el, r: el.getBoundingClientRect() }));
			const ranks = rankOf(items);
			items.forEach(({ el }, i) => {
				const cfg = pendingCfg.get(el)!;
				pendingCfg.delete(el);
				entered.add(el);
				if (!motionOK() || busyAnimating(el)) return;
				runEnter(el, cfg, Math.min(ranks[i], 6) * Math.min(cfg.step, 40));
			});
		});
	}
}

/** Спостерігати елемент: показати анімацією, коли він (з запасом знизу) потрапить у видиму область. */
function observeEnter(el: HTMLElement): void {
	const root = el.closest(CONTENT_SEL);
	let io = enterIOs.get(root);
	if (!io) {
		// спрацьовує трохи ДО входу у в'юпорт — анімація стартує з opacity 0
		io = new IntersectionObserver(onEnterIO, { root, rootMargin: '0px 0px 15% 0px' });
		enterIOs.set(root, io);
	}
	ioOf.set(el, io);
	io.observe(el);
}

type EnterItem = { el: HTMLElement; cfg: EnterCfg };

/** Обробити пачку нових елементів: видимі — каскадом, решта — при прокрутці.
 *  Пачка збирається з УСІХ контейнерів за кадр (див. scheduleScan): кілька
 *  сусідніх списків (напр. секції днів у «Харчуванні») ранжуються разом, тож
 *  каскад іде згори вниз по всій сторінці, а не стартує з нуля в кожній секції. */
function enterBatch(items: EnterItem[]): void {
	// рух вимкнено: лише позначаємо елементи (щоб після увімкнення не «вибухнули»
	// всі наявні); двигун лишається підключеним — увімкнення діє без перезавантаження
	if (!motionOK()) {
		for (const { el } of items) entered.add(el);
		return;
	}
	const vh = window.innerHeight;
	/** Межі видимої області для елемента: `.content` (якщо він усередині) або в'юпорт. */
	const bounds = new Map<Element | null, { top: number; bottom: number }>();
	const boundsOf = (el: HTMLElement) => {
		const root = el.closest(CONTENT_SEL);
		let b = bounds.get(root);
		if (!b) {
			const rr = root?.getBoundingClientRect();
			b = rr && rr.height > 0 ? { top: rr.top, bottom: rr.bottom } : { top: 0, bottom: vh };
			bounds.set(root, b);
		}
		return b;
	};
	const vis: { el: HTMLElement; r: DOMRect; cfg: EnterCfg }[] = [];
	for (const { el, cfg } of items) {
		if (entered.has(el) || !el.isConnected) continue;
		const r = el.getBoundingClientRect();
		// приховані (display:none): не позначаємо, а чекаємо, поки з'являться
		// (IntersectionObserver спрацює, щойно елемент отримає розмір і потрапить у вікно)
		if (r.width === 0 && r.height === 0) {
			if (!pendingCfg.has(el)) {
				pendingCfg.set(el, cfg);
				observeEnter(el);
			}
			continue;
		}
		if (pendingCfg.has(el)) continue; // уже чекає прокрутки
		entered.add(el);
		if (busyAnimating(el)) continue;
		const bd = boundsOf(el);
		if (r.bottom < bd.top || r.top > bd.bottom) {
			// вище області — просто показуємо; нижче — чекаємо прокрутки
			if (r.top > bd.bottom) {
				pendingCfg.set(el, cfg);
				observeEnter(el);
			}
			continue;
		}
		vis.push({ el, r, cfg });
	}
	if (!vis.length) return;
	const ranks = rankOf(vis);
	const base = batchBase();
	let end = 0;
	vis.forEach(({ el, cfg }, i) => {
		const d = Math.min(MAX_ENTER_DELAY, Math.round(base + Math.min(ranks[i], cfg.cap) * cfg.step));
		if (d > end) end = d;
		runEnter(el, cfg, d);
	});
	lastBatchAt = performance.now();
	lastBatchEnd = Math.min(end, MAX_ENTER_DELAY);
}

/** Один rAF на кадр для всіх контейнерів (rAF іде ДО малювання — новий
 *  елемент не встигає «блимнути»). */
const dirtyScans = new Set<() => EnterItem[]>();
let scanRaf = 0;
function scheduleScan(scan: () => EnterItem[]): void {
	dirtyScans.add(scan);
	if (scanRaf) return;
	scanRaf = requestAnimationFrame(() => {
		scanRaf = 0;
		const items: EnterItem[] = [];
		for (const s of dirtyScans) items.push(...s());
		dirtyScans.clear();
		enterBatch(items);
	});
}

type EngineOpts = {
	selector?: string;
	/** елементи всередині вкладених [data-stagger] пропускаються (їх веде свій контейнер) */
	own?: boolean;
} & Partial<EnterCfg>;

function attachEngine(node: HTMLElement, opts: EngineOpts): () => void {
	const cfg: EnterCfg = {
		step: opts.step ?? 32,
		y: opts.y ?? 10,
		scale: opts.scale ?? false,
		blur: opts.blur ?? false,
		cap: opts.cap ?? 12
	};
	const sel = opts.selector;
	engineCfg.set(node, { cfg, selector: sel });
	/** Чи підходить елемент для цього контейнера. */
	const accept = (el: HTMLElement): boolean => {
		if (entered.has(el)) return false;
		if (!opts.own) return true;
		// лише «свої»: найближчий контейнер-каскад — це node, і немає
		// предка-кандидата (щоб картка й вкладена картка не анімувались двічі)
		if (el.parentElement?.closest('[data-stagger]') !== node) return false;
		const up = el.parentElement?.closest(sel!);
		return !(up && up !== node && node.contains(up));
	};
	/** Початковий повний обхід (далі — лише піддерева доданих вузлів). */
	const fullScan = (): HTMLElement[] =>
		(sel
			? Array.from(node.querySelectorAll<HTMLElement>(sel))
			: (Array.from(node.children) as HTMLElement[])
		).filter(accept);
	/** Кандидати з піддерева щойно доданого вузла. */
	const scanAdded = (n: HTMLElement, out: Set<HTMLElement>): void => {
		if (!n.isConnected) return;
		if (!sel) {
			if (n.parentElement === node && accept(n)) out.add(n);
			return;
		}
		if (n.matches(sel) && accept(n)) out.add(n);
		for (const el of n.querySelectorAll<HTMLElement>(sel)) if (accept(el)) out.add(el);
	};

	let alive = true;
	let initial = true;
	let added: HTMLElement[] = [];
	const job = (): EnterItem[] => {
		if (!alive) return [];
		const out = new Set<HTMLElement>();
		if (initial) {
			initial = false;
			for (const el of fullScan()) out.add(el);
		}
		const list = added;
		added = [];
		for (const n of list) scanAdded(n, out);
		return Array.from(out, (el) => ({ el, cfg }));
	};
	scheduleScan(job);
	const mo = new MutationObserver((recs) => {
		let any = false;
		for (const rec of recs) {
			for (const n of Array.from(rec.addedNodes)) {
				if (n.nodeType === 1) {
					added.push(n as HTMLElement);
					any = true;
				}
			}
		}
		if (any) scheduleScan(job);
	});
	mo.observe(node, { childList: true, subtree: !!sel });
	return () => {
		alive = false;
		added = [];
		dirtyScans.delete(job);
		mo.disconnect();
	};
}

type StaggerOpts =
	| { selector?: string; step?: number; y?: number; max?: number; scale?: boolean; blur?: boolean }
	| undefined;

/** Каскадна поява дітей контейнера (списки, сітки) — на двигуні появи.
 *  `max` — після скількох «рангів» затримка перестає рости (НЕ ліміт кількості:
 *  анімуються всі елементи, поза екраном — при прокрутці). */
export const stagger: Action<HTMLElement, StaggerOpts> = (node, opts) => {
	// позначка: глобальний двигун (autoEnter) не чіпає дітей цього контейнера
	node.setAttribute('data-stagger', '');
	if (typeof MutationObserver === 'undefined') return;
	const off = attachEngine(node, {
		selector: opts?.selector,
		step: opts?.step,
		y: opts?.y,
		scale: opts?.scale,
		blur: opts?.blur,
		cap: opts?.max
	});
	return { destroy: off };
};

/** Що анімує глобальний двигун (те саме, що раніше робила CSS-поява). */
export const AUTO_ENTER_SEL =
	'.glass.card:not(.w-floating), article.glass, .wg-h, .wg-cell.filled, .pill, .m1-enter, [data-enter]';

/** Глобальна поява карток у межах кореня (вішається один раз у +layout).
 *  Пропускає все, що веде вкладений use:stagger. */
export const autoEnter: Action<HTMLElement> = (node) => {
	node.setAttribute('data-stagger', '');
	if (typeof MutationObserver === 'undefined') return;
	const off = attachEngine(node, { selector: AUTO_ENTER_SEL, own: true, step: 40, y: 12, cap: 10 });
	return { destroy: off };
};

/** 3D-нахил картки за курсором (лише миша і рівень «full»). */
export const tilt: Action<HTMLElement, { max?: number } | undefined> = (node, opts) => {
	if (!canHover()) return;
	const max = opts?.max ?? 5;
	let raf = 0;
	let rect: DOMRect | null = null;
	let px = 0;
	let py = 0;
	const enter = () => {
		rect = node.getBoundingClientRect();
	};
	const move = (e: PointerEvent) => {
		if (!motionOK() || !fx()) return;
		if (!rect) rect = node.getBoundingClientRect();
		px = (e.clientX - rect.left) / rect.width - 0.5;
		py = (e.clientY - rect.top) / rect.height - 0.5;
		if (raf) return;
		raf = requestAnimationFrame(() => {
			raf = 0;
			node.style.transform = `perspective(900px) rotateX(${(-py * max).toFixed(2)}deg) rotateY(${(px * max).toFixed(2)}deg)`;
		});
	};
	const leave = () => {
		cancelAnimationFrame(raf);
		raf = 0;
		rect = null;
		if (!node.style.transform) return;
		node.style.transition = `transform 600ms ${ease('spring')}`;
		node.style.transform = '';
		setTimeout(() => (node.style.transition = ''), 600);
	};
	node.addEventListener('pointerenter', enter);
	node.addEventListener('pointermove', move, { passive: true });
	node.addEventListener('pointerleave', leave);
	return {
		destroy() {
			cancelAnimationFrame(raf);
			node.removeEventListener('pointerenter', enter);
			node.removeEventListener('pointermove', move);
			node.removeEventListener('pointerleave', leave);
		}
	};
};

/** «Прожектор»: м'яка пляма світла, що йде за курсором.
 *  Дешева реалізація: ОДИН дочірній елемент із фіксованим градієнтом, що
 *  рухається лише через transform (без перемальовування), rAF-тротлінг,
 *  розмір картки кешується на вході. Лише миша і рівень «full». */
export const spotlight: Action<HTMLElement> = (node) => {
	if (!canHover()) return;
	node.classList.add('spotlight');
	let glow: HTMLSpanElement | null = null;
	let rect: DOMRect | null = null;
	let raf = 0;
	let x = 0;
	let y = 0;
	let layer: HTMLSpanElement | null = null;
	const ensure = () => {
		if (glow) return glow;
		// Пляма живе в шарі inset:0 з overflow:hidden: інакше в картці з
		// власним скролом (віджет з явною висотою) 360px-пляма розширювала
		// область прокрутки — з'являвся великий порожній скрол донизу.
		layer = document.createElement('span');
		layer.className = 'spotlight-layer';
		layer.setAttribute('aria-hidden', 'true');
		glow = document.createElement('span');
		glow.className = 'spotlight-glow';
		layer.append(glow);
		node.prepend(layer);
		return glow;
	};
	const enter = () => {
		if (!fx() || !motionOK()) return;
		rect = node.getBoundingClientRect();
		ensure();
	};
	const move = (e: PointerEvent) => {
		if (!rect || !glow) return;
		x = e.clientX - rect.left;
		y = e.clientY - rect.top;
		if (raf) return;
		raf = requestAnimationFrame(() => {
			raf = 0;
			glow!.style.transform = `translate(${x}px, ${y}px)`;
		});
	};
	const leave = () => {
		rect = null;
	};
	node.addEventListener('pointerenter', enter);
	node.addEventListener('pointermove', move, { passive: true });
	node.addEventListener('pointerleave', leave);
	return {
		destroy() {
			cancelAnimationFrame(raf);
			layer?.remove();
			node.classList.remove('spotlight');
			node.removeEventListener('pointerenter', enter);
			node.removeEventListener('pointermove', move);
			node.removeEventListener('pointerleave', leave);
		}
	};
};

/** Плавна прокрутка колесом миші (помірна, без «желе»).
 *  - лише для дискретного колеса миші: тачпад і сенсор і так плавні. Тачпад
 *    розпізнається за потоком дрібних/дробових дельт (часто з deltaX≠0); щойно
 *    подія за останні ~400мс скидалась на тачпад, весь жест лишається нативним;
 *  - вкладені прокручувані блоки (віджети, списки, модалки) крутяться
 *    нативно, поки самі можуть прокрутитися в цьому напрямку;
 *  - ctrl/shift + колесо (зум, горизонталь) — нативно;
 *  - зовнішні зміни scrollTop (scrollTo, клавіші, повзунок) зупиняють анімацію
 *    і синхронізують позицію — без боротьби за прокрутку;
 *  - вимикається разом із рухом (motionOK()). */
export const smoothWheel: Action<HTMLElement, { ease?: number } | undefined> = (node, opts) => {
	// частка залишку відстані за кадр: 0.14 ≈ 300–350мс «доїзду» — плавно, але не мляво
	const k = opts?.ease ?? 0.14;
	let target = node.scrollTop;
	let raf = 0;
	let animating = false;
	/** Остання позиція, яку виставили ми (для виявлення сторонніх змін scrollTop). */
	let lastSet = node.scrollTop;
	/** До якого моменту (performance.now) жест вважається тачпадом. */
	let padUntil = 0;

	const maxTop = () => node.scrollHeight - node.clientHeight;

	/** Чи є між target і node блок, що сам прокрутиться в напрямку dy. */
	const nestedScrolls = (from: EventTarget | null, dy: number): boolean => {
		let el = from instanceof Element ? from : null;
		while (el && el !== node) {
			if (el instanceof HTMLElement && el.scrollHeight > el.clientHeight + 1) {
				const oy = getComputedStyle(el).overflowY;
				if (oy === 'auto' || oy === 'scroll' || oy === 'overlay') {
					if (dy > 0 ? el.scrollTop < el.scrollHeight - el.clientHeight - 1 : el.scrollTop > 0) return true;
				}
			}
			el = el.parentElement;
		}
		return false;
	};

	/** Дискретне колесо миші (а не тачпад). Мишею вважаємо: рядковий режим (Firefox)
	 *  або піксельні цілі крупні дельти (100/120 і кратні) без горизонталі. Тачпад —
	 *  дрібні/дробові дельти або deltaX≠0; після такої події ~400мс усе нативно. */
	const isMouseWheel = (e: WheelEvent): boolean => {
		if (e.deltaMode === 1) return true;
		if (e.deltaMode !== 0) return false;
		const now = performance.now();
		const dy = Math.abs(e.deltaY);
		const dx = Math.abs(e.deltaX);
		const padLike =
			!Number.isInteger(e.deltaY) || !Number.isInteger(e.deltaX) || dx >= 1 || dy < 50;
		if (padLike) {
			padUntil = now + 400;
			return false;
		}
		return now >= padUntil;
	};

	// власна дробова позиція: scrollTop браузер округлює, і на малих залишках
	// (diff·k < 0.5px) анімація інакше «застрягала» б назавжди
	let pos = 0;
	let last = 0;

	/** Зупинити анімацію й синхронізувати позицію з фактичним scrollTop. */
	const stop = () => {
		if (raf) cancelAnimationFrame(raf);
		raf = 0;
		animating = false;
		target = pos = lastSet = node.scrollTop;
	};

	/** scrollTop змінив хтось інший (scrollTo, клавіші, повзунок)? */
	const externallyMoved = () => Math.abs(node.scrollTop - lastSet) > 2;

	const step = (now: number) => {
		if (externallyMoved()) {
			stop();
			return;
		}
		// незалежно від частоти кадрів (60/120/144 Гц): k нормовано на 60 fps
		const dt = last ? Math.min(64, now - last) : 16.7;
		last = now;
		const f = 1 - Math.pow(1 - k, dt / 16.7);
		pos += (target - pos) * f;
		if (Math.abs(target - pos) < 0.5) pos = target;
		node.scrollTop = pos;
		lastSet = node.scrollTop;
		if (pos === target) {
			animating = false;
			raf = 0;
			return;
		}
		raf = requestAnimationFrame(step);
	};

	const onWheel = (e: WheelEvent) => {
		if (e.defaultPrevented || e.ctrlKey || e.shiftKey || !motionOK() || !isMouseWheel(e)) {
			// нативна прокрутка посеред анімації: віддаємо керування браузеру
			if (animating) stop();
			return;
		}
		const dy = e.deltaMode === 1 ? e.deltaY * 40 : e.deltaY;
		if (nestedScrolls(e.target, dy)) {
			if (animating) stop();
			return;
		}
		const max = maxTop();
		if (max <= 0) return;
		e.preventDefault();
		// хтось прокрутив сторінку між кадрами — починаємо з фактичної позиції
		if (animating && externallyMoved()) stop();
		if (!animating) target = pos = lastSet = node.scrollTop;
		target = Math.max(0, Math.min(max, target + dy));
		if (!animating) {
			animating = true;
			last = 0;
			raf = requestAnimationFrame(step);
		}
	};

	// Інші джерела прокрутки (повзунок, клавіші, scrollIntoView) — без боротьби:
	// будь-яка взаємодія, крім колеса, зупиняє анімацію.
	const stopIfBusy = () => {
		if (animating) stop();
	};
	const onScroll = () => {
		if (animating && externallyMoved()) stop();
	};

	node.addEventListener('wheel', onWheel, { passive: false });
	node.addEventListener('scroll', onScroll, { passive: true });
	node.addEventListener('pointerdown', stopIfBusy);
	node.addEventListener('touchstart', stopIfBusy, { passive: true });
	window.addEventListener('keydown', stopIfBusy, true);
	return {
		destroy() {
			cancelAnimationFrame(raf);
			node.removeEventListener('wheel', onWheel);
			node.removeEventListener('scroll', onScroll);
			node.removeEventListener('pointerdown', stopIfBusy);
			node.removeEventListener('touchstart', stopIfBusy);
			window.removeEventListener('keydown', stopIfBusy, true);
		}
	};
};

/** Магнітна кнопка: злегка тягнеться до курсора. */
export const magnetic: Action<HTMLElement, { strength?: number } | undefined> = (node, opts) => {
	if (!canHover()) return;
	const k = opts?.strength ?? 0.18;
	let raf = 0;
	let rect: DOMRect | null = null;
	const move = (e: PointerEvent) => {
		if (!motionOK()) return;
		if (!rect) rect = node.getBoundingClientRect();
		const dx = (e.clientX - (rect.left + rect.width / 2)) * k;
		const dy = (e.clientY - (rect.top + rect.height / 2)) * k;
		if (raf) return;
		raf = requestAnimationFrame(() => {
			raf = 0;
			node.style.translate = `${dx.toFixed(1)}px ${dy.toFixed(1)}px`;
		});
	};
	const leave = () => {
		cancelAnimationFrame(raf);
		raf = 0;
		rect = null;
		node.style.transition = `translate 500ms ${ease('spring')}`;
		node.style.translate = '';
		setTimeout(() => (node.style.transition = ''), 500);
	};
	node.addEventListener('pointermove', move, { passive: true });
	node.addEventListener('pointerleave', leave);
	return {
		destroy() {
			cancelAnimationFrame(raf);
			node.removeEventListener('pointermove', move);
			node.removeEventListener('pointerleave', leave);
		}
	};
};

/** Коротке «потрушування» (помилка валідації, відмова). */
export function shake(node: HTMLElement): void {
	if (!motionOK()) return;
	node.animate(
		[
			{ transform: 'translateX(0)' },
			{ transform: 'translateX(-7px)' },
			{ transform: 'translateX(6px)' },
			{ transform: 'translateX(-4px)' },
			{ transform: 'translateX(2px)' },
			{ transform: 'translateX(0)' }
		],
		{ duration: 420, easing: EASE.out }
	);
}

/** «Пульс» успіху (галочка, нове значення). */
export function pop(node: HTMLElement, scale = 1.12): void {
	if (!motionOK()) return;
	node.animate([{ transform: 'scale(1)' }, { transform: `scale(${scale})` }, { transform: 'scale(1)' }], {
		duration: 460,
		easing: ease('spring')
	});
}

/* ---------------- Svelte transitions ---------------- */

/** Поява з пружинним масштабом (поповери, меню, бейджі). */
export function springIn(
	node: Element,
	{ delay = 0, duration = 380, start = 0.92, y = 6 }: { delay?: number; duration?: number; start?: number; y?: number } = {}
): TransitionConfig {
	if (!motionOK()) return { duration: 0 };
	return {
		delay,
		duration,
		easing: backOut,
		css: (t, u) => `opacity:${Math.min(1, t * 1.6)};transform:translateY(${u * y}px) scale(${start + (1 - start) * t})`
	};
}

/** М'яка поява/зникнення (перемикання вмісту, скелетон → дані).
 *  Blur — лише на рівні «full»; у «lite» — той самий рух без blur. */
export function blurFade(
	node: Element,
	{ delay = 0, duration = 320, amount = 8, y = 0 }: { delay?: number; duration?: number; amount?: number; y?: number } = {}
): TransitionConfig {
	if (!motionOK()) return { duration: 0 };
	const b = fx() ? amount : 0;
	const yy = y || (b ? 0 : 4);
	return {
		delay,
		duration,
		easing: cubicOut,
		css: (t, u) =>
			`opacity:${t};transform:translateY(${u * yy}px)` + (b ? `;filter:blur(${u * b}px)` : '')
	};
}

/** Виїзд збоку з напрямком (крок вперед/назад). */
export function slideX(
	node: Element,
	{ dir = 1, distance = 28, duration = 360, delay = 0 }: { dir?: 1 | -1; distance?: number; duration?: number; delay?: number } = {}
): TransitionConfig {
	if (!motionOK()) return { duration: 0 };
	return {
		delay,
		duration,
		easing: cubicOut,
		css: (t, u) => `opacity:${t};transform:translateX(${u * distance * dir}px)`
	};
}

/* ---------------- перемикання вкладок ---------------- */

export type VTDir = 'forward' | 'back' | 'up' | 'fade';

/** Поява нового вмісту вкладки на ЖИВОМУ DOM (без знімків View Transitions):
 *  дешево, не «замерзає» на ледачих вкладках і не конфліктує з внутрішніми
 *  анімаціями вкладки. Попередня анімація скасовується (швидкі перемикання). */
const enterAnims = new WeakMap<HTMLElement, Animation>();
export function enterContent(el: HTMLElement | null | undefined, dir: VTDir = 'fade'): void {
	if (!el || !motionOK()) return;
	enterAnims.get(el)?.cancel();
	const from =
		dir === 'forward'
			? 'translateX(24px)'
			: dir === 'back'
				? 'translateX(-24px)'
				: dir === 'up'
					? 'translateY(14px) scale(0.99)'
					: 'translateY(8px)';
	const a = el.animate([{ opacity: 0, transform: from }, { opacity: 1, transform: 'none' }], {
		duration: dir === 'fade' ? 260 : 340,
		easing: EASE.out
	});
	enterAnims.set(el, a);
}

/** @deprecated Замінено на enterContent: знімки View Transitions «замерзали»
 *  на ледачих вкладках і були дорогими на слабких пристроях. Лишено для сумісності. */
export async function withViewTransition(update: () => void | Promise<void>, _dir: VTDir = 'fade'): Promise<void> {
	await update();
}

export { default as AnimatedNumber } from './AnimatedNumber.svelte';
