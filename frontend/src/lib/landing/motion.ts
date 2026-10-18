// Моушн лендінгу: рекламне інтро на весь екран → збірка hero-заголовка →
// барабан «мав → міг → має» → ударна хвиля з уламками → розліт
// літер при скролі. Чистий WAAPI + canvas, без бібліотек.
//
// Розмітку (пререндерену) дає LandingHero.svelte; модуль лише оживляє її.
// Початковий прихований стан задає клас html.lh-anim (ставить інлайн-скрипт
// у <head>, щоб не було спалаху готового заголовка до гідрації).

export interface MotionRefs {
	root: HTMLElement; // .lh-scroll
	ad: HTMLElement; // .lh-ad
	canvas: HTMLCanvasElement; // .lh-fx
	skip: HTMLButtonElement; // .lh-skip
	brand: HTMLElement | null; // логотип у шапці лендінгу (ціль FLIP)
}

interface Item {
	el: HTMLElement;
	x: number;
	y: number;
	r: number;
	vx: number;
	vy: number;
	vr: number;
	cx: number;
	cy: number;
	sx: number;
	sy: number;
	sr: number;
	dl: number; // затримка розвалу (частка прогресу скролу)
	landed: boolean; // вже «вдарилась» об скріншот
	color: string; // колір уламків
	big: boolean;
}
interface Pending {
	it: Item;
	t: number;
	vx: number;
	vy: number;
	vr: number;
}
interface Shard {
	x: number;
	y: number;
	vx: number;
	vy: number;
	t: number;
	life: number;
	chunk: boolean;
	w: number;
	rot: number;
	vrot: number;
	c: string;
}
interface Ring {
	x: number;
	y: number;
	t: number;
	life: number;
	max: number;
	w: number;
}
interface Flash {
	x: number;
	y: number;
	t: number;
	life: number;
	r: number;
}

const EXPO = 'cubic-bezier(.16,1,.3,1)';
const C = { fg: '#e9ecf4', accent: '#9d8cff', muted: '#8b93a6' };
const P = {
	violet: '#9d8cff',
	coral: '#ff5a3c',
	yellow: '#ffd23f',
	blue: '#3d5afe',
	paper: '#f1efe8',
	ink: '#0a0c10'
};

const rnd = (a: number, b: number): number => a + Math.random() * (b - a);

export function mountLandingMotion(refs: MotionRefs): () => void {
	const html = document.documentElement;
	const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
	(window as unknown as { __lhMounted?: boolean }).__lhMounted = true;

	const { root, ad, canvas, skip, brand } = refs;
	const q = <T extends HTMLElement>(sel: string): T => {
		const el = root.querySelector<T>(sel);
		if (!el) throw new Error(`landing motion: ${sel} not found`);
		return el;
	};
	const stage = q('.lh-stage');
	const title = q('.lh-title');
	const l1 = q('.lh-l1');
	const l2 = q('.lh-l2');
	const l3 = q('.lh-l3');
	const l4 = q('.lh-l4');
	const row34 = q('.lh-row34');
	const scan = q('.lh-scan');
	const slot = q('.lh-slot');
	const sw = q('.lh-sw');
	const strike = q('.lh-strike');
	const mark = q('.lh-mark');
	const sub = q('.lh-sub');
	const shot = q('.lh-shot');
	const avg = root.querySelector<HTMLElement>('.lh-avg');

	if (reduced) {
		html.classList.remove('lh-anim', 'lh-ad-on');
		slot.classList.add('lh-final');
		return () => {};
	}
	html.classList.add('lh-anim');

	// ── розбиття тексту на літери в масках ──
	function makeWord(text: string): HTMLElement {
		const w = document.createElement('span');
		w.className = 'lh-word';
		const m = document.createElement('span');
		m.className = 'lh-m';
		w.appendChild(m);
		for (const t of text) {
			const ch = document.createElement('span');
			ch.className = 'lh-ch';
			const ci = document.createElement('span');
			ci.className = 'lh-ci';
			ci.textContent = t;
			ch.appendChild(ci);
			m.appendChild(ch);
		}
		return w;
	}
	function splitLine(line: HTMLElement): void {
		const texts = [...line.childNodes].filter((n) => n.nodeType === Node.TEXT_NODE);
		const text = texts.map((n) => n.textContent ?? '').join('').trim();
		texts.forEach((n) => n.remove());
		const anchor = line.querySelector('.lh-scan');
		for (const w of text.split(/\s+/)) line.insertBefore(makeWord(w), anchor);
	}
	splitLine(l1);
	splitLine(l2);
	splitLine(l4);
	l3.querySelectorAll<HTMLElement>('.lh-w').forEach((el) =>
		el.replaceWith(makeWord(el.textContent ?? ''))
	);

	title.classList.add('lh-split');

	const meas = document.createElement('span');
	meas.className = 'lh-meas';
	l3.appendChild(meas);
	const measure = (t: string): number => {
		meas.textContent = t;
		return meas.offsetWidth;
	};
	// усі слова барабана по 3 літери — ширина слота майже не змінюється
	const REEL = ['мав', 'міг', 'має'];

	// Чи вміщається «яким <найширше слово> бути.» в один рядок? Рішення
	// фіксуємо до старту барабана, щоб рядок не переносився посеред анімації.
	function layoutRow(): void {
		const cur = sw.textContent ?? '';
		const prevTr = slot.style.transition;
		slot.style.transition = 'none';
		row34.classList.remove('lh-stack', 'lh-inline');
		slot.style.width = Math.max(...REEL.map(measure)) + 'px';
		const wrapped = l4.offsetTop > l3.offsetTop + 4;
		row34.classList.add(wrapped ? 'lh-stack' : 'lh-inline');
		slot.style.width = measure(cur) + 'px';
		void slot.offsetWidth;
		slot.style.transition = prevTr;
	}

	// ── фізика літер ──
	const items: Item[] = [...title.querySelectorAll<HTMLElement>('.lh-ci')].map((el) => ({
		el,
		x: 0,
		y: 0,
		r: 0,
		vx: 0,
		vy: 0,
		vr: 0,
		cx: 0,
		cy: 0,
		sx: 0,
		sy: 0,
		sr: 0,
		dl: 0,
		landed: false,
		color: el.closest('.lh-l2') ? C.muted : el.classList.contains('lh-pi') ? C.accent : C.fg,
		big: el.classList.contains('lh-pi')
	}));

	function computeCenters(): void {
		const sr = stage.getBoundingClientRect();
		const tr = title.getBoundingClientRect();
		const tcx = tr.left + tr.width / 2 - sr.left;
		const H = sr.height;
		for (const it of items) {
			const r = it.el.getBoundingClientRect();
			it.cx = r.left + r.width / 2 - sr.left - it.x;
			it.cy = r.top + r.height / 2 - sr.top - it.y;
			// літери падають на скріншот, що підіймається знизу:
			// нижні рядки сиплються першими, кожна — зі своєю затримкою
			it.sx = (it.cx - tcx) * 0.22 + rnd(-90, 90);
			// на вертикальному телефоні кадр вищий і стоїть вище — літери падають на нього
			const phone = innerWidth <= 760 && innerHeight > 500;
			it.sy = (phone ? H * 0.32 + rnd(0, H * 0.3) : H * 0.6 + rnd(0, H * 0.28)) - it.cy;
			it.sr = rnd(-150, 150) * (it.big ? 0.4 : 1);
			it.dl = Math.max(0, 0.26 - (it.cy / H) * 0.3) + rnd(0, 0.09);
		}
	}

	// ── хелпери анімацій ──
	let anims: Animation[] = [];
	let run = 0;
	let ready = false;
	let alive = true;
	const A = (el: Element, kf: Keyframe[], o: KeyframeAnimationOptions): Animation => {
		const a = el.animate(kf, { fill: 'both', ...o });
		anims.push(a);
		return a;
	};
	const sleep = (ms: number, id: number): Promise<void> =>
		new Promise((res, rej) =>
			setTimeout(() => (id === run && alive ? res() : rej(new Error('stale'))), ms)
		);
	const rise = (chars: Element[], delay: number, step = 26, dur = 820): void =>
		chars.forEach((c, i) =>
			A(
				c,
				[{ transform: 'translateY(118%) rotate(8deg)' }, { transform: 'translateY(0) rotate(0)' }],
				{ duration: dur, delay: delay + i * step, easing: EXPO }
			)
		);

	// ── canvas: хвиля, спалах, уламки ──
	const ctx = canvas.getContext('2d');
	const shards: Shard[] = [];
	const rings: Ring[] = [];
	const flashes: Flash[] = [];
	const pending: Pending[] = [];
	let shake = 0;

	function resize(): void {
		layoutRow();
		const dpr = Math.min(devicePixelRatio || 1, 2);
		canvas.width = innerWidth * dpr;
		canvas.height = innerHeight * dpr;
		ctx?.setTransform(dpr, 0, 0, dpr, 0, 0);
		if (ready) computeCenters();
	}

	function burst(x: number, y: number, power: number, pal?: string[]): void {
		const now = performance.now();
		if (ready) {
			for (const it of items) {
				const r = it.el.getBoundingClientRect();
				const dx = r.left + r.width / 2 - x;
				const dy = r.top + r.height / 2 - y;
				const d = Math.hypot(dx, dy) || 1;
				const f = power * 2100 * Math.exp(-d / 360);
				pending.push({
					it,
					t: now + d / 2.6,
					vx: (dx / d) * f,
					vy: (dy / d) * f - f * 0.15,
					vr: (Math.random() - 0.5) * f * 0.09
				});
			}
		}
		const scale = innerWidth / 1400 + 0.4;
		rings.push({ x, y, t: 0, life: 0.7, max: 560 * power * scale, w: 10 });
		rings.push({ x, y, t: -0.08, life: 0.9, max: 900 * power * scale, w: 3 });
		flashes.push({ x, y, t: 0, life: 0.16, r: 70 * power });
		const n = Math.round(90 * power);
		for (let i = 0; i < n; i++) {
			const a = Math.random() * Math.PI * 2;
			const sp = (500 + Math.random() * 1500) * power;
			const chunk = Math.random() < 0.18;
			const fallback =
				Math.random() < 0.55 ? C.accent : Math.random() < 0.7 ? C.fg : C.muted;
			shards.push({
				x,
				y,
				vx: Math.cos(a) * sp,
				vy: Math.sin(a) * sp,
				t: 0,
				life: 0.55 + Math.random() * 0.7,
				chunk,
				w: chunk ? 5 + Math.random() * 7 : 1.5 + Math.random() * 1.8,
				rot: Math.random() * 6,
				vrot: (Math.random() - 0.5) * 20,
				c: (pal && pal[i % pal.length]) || fallback
			});
		}
		shake = Math.max(shake, 16 * power);
	}

	// дрібний розсип уламків у місці, де літера «вдарилась» об скріншот
	function crumble(x: number, y: number, color: string): void {
		for (let i = 0; i < 9; i++) {
			const a = rnd(Math.PI * 1.05, Math.PI * 1.95); // віялом угору
			const sp = rnd(120, 460);
			shards.push({
				x: x + rnd(-10, 10),
				y,
				vx: Math.cos(a) * sp,
				vy: Math.sin(a) * sp,
				t: 0,
				life: rnd(0.35, 0.7),
				chunk: Math.random() < 0.5,
				w: Math.random() < 0.5 ? rnd(2.5, 6) : rnd(1.2, 2.2),
				rot: rnd(0, 6),
				vrot: rnd(-18, 18),
				c: i % 3 === 0 ? C.accent : color
			});
		}
	}

	// ── hero: збірка заголовка ──
	let introRunning = false;

	async function intro(): Promise<void> {
		const id = ++run;
		introRunning = true;
		sw.style.transform = '';
		ready = false;
		anims.forEach((a) => a.cancel());
		anims = [];
		title.classList.remove('lh-open');
		slot.classList.remove('lh-final');
		sub.style.opacity = '';
		sw.textContent = 'мав';
		layoutRow();
		slot.style.transition = 'none';
		slot.style.width = measure('мав') + 'px';
		void slot.offsetWidth;
		slot.style.transition = '';
		pending.length = 0;
		for (const it of items) {
			it.x = it.y = it.r = it.vx = it.vy = it.vr = 0;
			it.landed = false;
			it.el.style.opacity = '';
		}

		rise([...l1.querySelectorAll('.lh-ch')], 120);
		const W = l2.offsetWidth;
		const sweep = { duration: 720, delay: 430, easing: 'cubic-bezier(.7,0,.25,1)' };
		A(l2, [{ clipPath: 'inset(-30% 100% -30% 0)' }, { clipPath: 'inset(-30% 0% -30% 0)' }], sweep);
		A(
			scan,
			[
				{ transform: 'translateX(0)', opacity: 1 },
				{ transform: `translateX(${W}px)`, opacity: 1, offset: 0.97 },
				{ transform: `translateX(${W}px)`, opacity: 0 }
			],
			sweep
		);
		A(l2, [{ color: 'transparent' }, { color: C.fg, offset: 0.12 }, { color: 'transparent' }], {
			duration: 700,
			delay: 1150,
			easing: 'ease-out',
			fill: 'none'
		});

		rise([...l3.querySelectorAll('.lh-ch')], 760);
		A(sw, [{ transform: 'translateY(118%)' }, { transform: 'translateY(0)' }], {
			duration: 620,
			delay: 840,
			easing: EXPO
		});
		rise([...l4.querySelectorAll('.lh-ch')], 900);

		try {
			await sleep(1180, id);
			for (const next of ['міг', 'має']) {
				const s = A(strike, [{ transform: 'scaleX(0)' }, { transform: 'scaleX(1)' }], {
					duration: 120,
					easing: 'cubic-bezier(.5,0,.2,1)'
				});
				await s.finished;
				await sleep(70, id);
				const out = A(sw, [{ transform: 'translateY(0)' }, { transform: 'translateY(-118%)' }], {
					duration: 120,
					easing: 'cubic-bezier(.6,0,1,1)'
				});
				await out.finished;
				if (id !== run) return;
				sw.textContent = next;
				slot.style.width = measure(next) + 'px';
				strike.getAnimations().forEach((a) => a.cancel());
				const inn = A(sw, [{ transform: 'translateY(118%)' }, { transform: 'translateY(0)' }], {
					duration: next === 'має' ? 260 : 150,
					easing: EXPO
				});
				await inn.finished;
				await sleep(next === 'має' ? 40 : 90, id);
			}
			const mi = A(
				mark,
				[
					{ transform: 'scaleX(0)', transformOrigin: 'left' },
					{ transform: 'scaleX(1)', transformOrigin: 'left' }
				],
				{ duration: 170, easing: 'cubic-bezier(.7,0,.3,1)' }
			);
			await mi.finished;
			if (id !== run) return;
			slot.classList.add('lh-final');
			title.classList.add('lh-open');
			computeCenters();
			A(
				mark,
				[
					{ transform: 'scaleX(1)', transformOrigin: 'right' },
					{ transform: 'scaleX(0)', transformOrigin: 'right' }
				],
				{ duration: 300, easing: 'cubic-bezier(.7,0,.3,1)' }
			);
			A(slot, [{ transform: 'scale(1.22)' }, { transform: 'scale(1)' }], {
				duration: 700,
				easing: EXPO,
				fill: 'none'
			});
			const r = slot.getBoundingClientRect();
			ready = true;
			introRunning = false;
			burst(r.left + r.width / 2, r.top + r.height / 2, 1);

			A(sub, [{ opacity: 0, transform: 'translateY(18px)' }, { opacity: 1, transform: 'translateY(0)' }], {
				duration: 900,
				delay: 260,
				easing: EXPO,
				fill: 'backwards'
			});
		} catch {
			/* перезапуск або unmount — ігноруємо */
		}
	}

	// Юзер почав гортати, поки заголовок ще складається: миттєво доводимо
	// збірку до фіналу, щоб літери одразу могли розвалюватись на скріншот.
	function finishIntro(): void {
		if (!introRunning) return;
		introRunning = false;
		run++; // зупиняє async-послідовність intro()
		for (const a of anims) {
			try {
				a.finish();
			} catch {
				/* анімація вже скасована */
			}
		}
		strike.getAnimations().forEach((a) => a.cancel());
		mark.getAnimations().forEach((a) => a.cancel());
		sw.getAnimations().forEach((a) => a.cancel());
		sw.textContent = 'має';
		sw.style.transform = 'none';
		slot.style.width = measure('має') + 'px';
		slot.classList.add('lh-final');
		title.classList.add('lh-open');
		for (const it of items) it.x = it.y = it.r = it.vx = it.vy = it.vr = 0;
		computeCenters();
		ready = true;
	}

	// ── рекламне інтро на весь екран ──
	let adRun = 0;
	let timers: number[] = [];
	const at = (ms: number, fn: () => void): void => {
		const id = adRun;
		timers.push(
			window.setTimeout(() => {
				if (id === adRun && alive) fn();
			}, ms)
		);
	};
	const mk = (tag: string, cls: string | null, txt: string | null, parent: Element): HTMLElement => {
		const e = document.createElement(tag);
		if (cls) e.className = cls;
		if (txt != null) e.textContent = txt;
		parent.appendChild(e);
		return e;
	};
	const letters = (parent: Element, text: string): HTMLElement[] =>
		[...text].map((ch) => mk('span', 'lh-lt', ch === ' ' ? ' ' : ch, parent));

	function shakeAd(power = 1): void {
		// амплітуда помірна: трус підкреслює удар, але не «трясе» екран
		const k = 8 * power;
		const f: Keyframe[] = [];
		for (let i = 0; i < 6; i++)
			f.push({ transform: `translate(${rnd(-k, k)}px,${rnd(-k, k)}px) rotate(${rnd(-0.6, 0.6) * power}deg)` });
		f.push({ transform: 'none' });
		ad.animate(f, { duration: 260, easing: 'linear' });
	}

	type Enter = 'cut' | 'wipe' | 'circle' | 'up' | 'split';
	function scene(bg: string, enter: Enter = 'cut', ox = 50, oy = 50): HTMLElement {
		const s = mk('div', 'lh-sc', null, ad);
		s.style.background = bg;
		const prev = [...ad.querySelectorAll('.lh-sc')].slice(0, -1);
		const done = (): void => prev.forEach((p) => p.remove());
		const ease = 'cubic-bezier(.7,0,.2,1)';
		let a: Animation | null = null;
		if (enter === 'wipe')
			a = s.animate(
				[
					{ clipPath: 'polygon(0 0,0 0,-40% 100%,-40% 100%)' },
					{ clipPath: 'polygon(0 0,140% 0,100% 100%,-40% 100%)' }
				],
				{ duration: 300, easing: ease }
			);
		else if (enter === 'circle')
			a = s.animate(
				[{ clipPath: `circle(0% at ${ox}% ${oy}%)` }, { clipPath: `circle(150% at ${ox}% ${oy}%)` }],
				{ duration: 380, easing: 'cubic-bezier(.7,0,.3,1)' }
			);
		else if (enter === 'up')
			a = s.animate([{ transform: 'translateY(100%)' }, { transform: 'translateY(0)' }], {
				duration: 280,
				easing: ease
			});
		else if (enter === 'split')
			a = s.animate([{ clipPath: 'inset(50% 0 50% 0)' }, { clipPath: 'inset(0 0 0 0)' }], {
				duration: 260,
				easing: ease
			});
		if (a) a.finished.then(done).catch(() => {});
		else done();
		return s;
	}

	interface SlamOpts {
		delay?: number;
		from?: number;
		rot?: number;
		dur?: number;
		power?: number;
		x?: number;
	}
	function slam(e: HTMLElement, o: SlamOpts = {}): void {
		const { delay = 0, from = 2.6, rot = 0, dur = 300, power = 0.8, x = 0 } = o;
		e.animate(
			[
				{ transform: `translateX(${x}px) scale(${from}) rotate(${rot}deg)`, opacity: 0 },
				{ transform: 'translateX(0) scale(.94) rotate(0)', opacity: 1, offset: 0.62 },
				{ transform: 'scale(1.02)', offset: 0.82 },
				{ transform: 'scale(1)', opacity: 1 }
			],
			{ duration: dur, delay, easing: 'cubic-bezier(.3,0,.2,1)', fill: 'both' }
		);
		if (power) at(delay + dur * 0.6, () => shakeAd(power));
	}
	function pop(e: HTMLElement, delay = 0, rot = 0, dur = 420): void {
		e.animate(
			[
				{ transform: `scale(0) rotate(${rot - 120}deg)` },
				{ transform: `scale(1.18) rotate(${rot + 8}deg)`, offset: 0.6 },
				{ transform: `scale(1) rotate(${rot}deg)` }
			],
			{ duration: dur, delay, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'both' }
		);
	}
	function shapes(s: HTMLElement, n: number, colors: string[], spread = 500): void {
		const kinds = ['circle', 'square', 'ring', 'plus', 'tri', 'half', 'pill'] as const;
		for (let i = 0; i < n; i++) {
			const k = kinds[i % kinds.length];
			const sz = rnd(5, 15);
			const e = mk('div', 'lh-shape', null, s);
			let x: number;
			let y: number;
			do {
				x = rnd(-4, 96);
				y = rnd(-4, 96);
			} while (x > 22 && x < 74 && y > 26 && y < 70);
			Object.assign(e.style, { left: x + '%', top: y + '%', width: sz + 'vmin', height: sz + 'vmin' });
			const c = colors[i % colors.length] ?? P.paper;
			if (k === 'circle') Object.assign(e.style, { background: c, borderRadius: '50%' });
			if (k === 'square') Object.assign(e.style, { background: c, borderRadius: '18%' });
			if (k === 'ring') Object.assign(e.style, { border: `${sz * 0.16}vmin solid ${c}`, borderRadius: '50%' });
			if (k === 'plus')
				Object.assign(e.style, {
					background: c,
					clipPath:
						'polygon(35% 0,65% 0,65% 35%,100% 35%,100% 65%,65% 65%,65% 100%,35% 100%,35% 65%,0 65%,0 35%,35% 35%)'
				});
			if (k === 'tri') Object.assign(e.style, { background: c, clipPath: 'polygon(50% 0,100% 100%,0 100%)' });
			if (k === 'half')
				Object.assign(e.style, { background: c, borderRadius: '999px 999px 0 0', height: sz / 2 + 'vmin' });
			if (k === 'pill')
				Object.assign(e.style, {
					background: c,
					borderRadius: '999px',
					height: sz / 2.6 + 'vmin',
					width: sz * 1.4 + 'vmin'
				});
			pop(e, rnd(0, spread), rnd(-40, 40));
			e.animate([{ translate: '0 0' }, { translate: `${rnd(-30, 30)}px ${rnd(-40, 10)}px` }], {
				duration: 1400,
				easing: 'ease-out',
				fill: 'both'
			});
		}
	}

	function playAd(): void {
		adRun++;
		timers.forEach(clearTimeout);
		timers = [];
		ad.replaceChildren();
		ad.style.opacity = '';
		html.classList.add('lh-ad-on', 'lh-lock');
		skip.hidden = false;
		run++;
		ready = false;
		anims.forEach((a) => a.cancel());
		anims = [];
		scrollTo({ top: 0 });

		// S0 — точка заливає екран
		const s0 = scene(P.ink);
		const dot = mk('div', 'lh-shape', null, s0);
		Object.assign(dot.style, {
			width: '34px',
			height: '34px',
			borderRadius: '50%',
			background: P.violet,
			left: 'calc(50% - 17px)',
			top: 'calc(50% - 17px)'
		});
		dot.animate(
			[
				{ transform: 'scale(0)' },
				{ transform: 'scale(1.25)', offset: 0.35 },
				{ transform: 'scale(1)', offset: 0.5 },
				{ transform: 'scale(1)', offset: 0.62 },
				{ transform: `scale(${Math.hypot(innerWidth, innerHeight) / 30})` }
			],
			{ duration: 620, easing: 'cubic-bezier(.6,0,.4,1)', fill: 'both' }
		);

		// S1 — MyStat і стікери-скарги
		at(600, () => {
			const s = scene(P.violet);
			const t = mk('div', 'lh-t', 'MyStat', s);
			Object.assign(t.style, { fontSize: 'min(16vw,28vh)', color: P.ink });
			slam(t, { from: 3.2, power: 1 });
			const lbls: [string, string, string, string, number, number, number][] = [
				['гальмує', P.paper, P.ink, P.ink, 22, 26, -8],
				['лагає', P.ink, P.paper, P.paper, 58, 18, 6],
				['знову 403', P.coral, P.ink, P.ink, 14, 66, 5],
				['бісить', P.yellow, P.ink, P.ink, 60, 70, -5]
			];
			lbls.forEach(([txt, bg, fg, sh, x, y, r], i) => {
				const l = mk('div', 'lh-lbl', txt, s);
				Object.assign(l.style, {
					left: (innerWidth < 640 ? Math.min(x, 46) : x) + '%',
					top: y + '%',
					background: bg,
					color: fg,
					rotate: r + 'deg',
					// плоска «друкована» тінь — стікер наче наклеєний
					boxShadow: `0.09em 0.11em 0 ${sh === P.paper ? 'rgba(241,239,232,.55)' : 'rgba(10,12,16,.85)'}`
				});
				slam(l, { delay: 220 + i * 120, from: 2, rot: r * 3, dur: 240, power: i === 0 ? 0.3 : 0 });
				// легке погойдування, поки сцена на екрані
				l.animate([{ translate: '0 0' }, { translate: `0 ${i % 2 ? -6 : 6}px` }], {
					duration: 700,
					delay: 480 + i * 120,
					direction: 'alternate',
					iterations: 2,
					easing: 'ease-in-out'
				});
			});
		});

		// S2 — розділи влітають з боків, з плоскою тінню
		at(1500, () => {
			const s = scene(P.coral, 'wipe');
			const st = mk('div', 'lh-t lh-stack', null, s);
			st.style.color = P.paper;
			['Розклад.', 'Домашка.', 'Оцінки.', 'Харчування.'].forEach((w, i) => {
				const e = mk('div', null, w, st);
				e.style.textShadow = i === 3 ? '0.05em 0.05em 0 rgba(241,239,232,.45)' : '0.05em 0.05em 0 rgba(10,12,16,.35)';
				if (i === 3) e.style.color = P.ink;
				slam(e, { delay: i * 150, from: 1.6, x: (i % 2 ? 1 : -1) * innerWidth * 0.6, dur: 280, power: i === 3 ? 0.5 : 0.25 });
			});
			shapes(s, 10, [P.paper, P.ink, P.yellow], 550);
		});

		// S3 — один акаунт: велика «1», літери, фіолетове підкреслення
		at(2350, () => {
			const s = scene(P.yellow, 'circle', 50, 55);
			const one = mk('div', 'lh-t', '1', s);
			Object.assign(one.style, { fontSize: 'min(90vh,120vw)', color: P.paper, position: 'absolute' });
			one.animate(
				[
					{ transform: 'scale(.2) rotate(-200deg)', opacity: 0 },
					{ transform: 'scale(1.08) rotate(8deg)', opacity: 1, offset: 0.7 },
					{ transform: 'scale(1) rotate(0)' }
				],
				{ duration: 520, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'both' }
			);
			const t = mk('div', 'lh-t', null, s);
			Object.assign(t.style, { fontSize: 'min(8vw,13vh)', color: P.ink, position: 'relative', isolation: 'isolate' });
			const ls = letters(t, 'Один акаунт.');
			ls.forEach((l, i) => pop(l, 160 + i * 32, rnd(-12, 12), 360));
			const bar = mk('div', 'lh-uline', null, t);
			bar.style.background = P.violet;
			bar.animate([{ transform: 'scaleX(0)' }, { transform: 'scaleX(1)' }], {
				duration: 320,
				delay: 220 + ls.length * 32,
				easing: 'cubic-bezier(.7,0,.2,1)',
				fill: 'both'
			});
			shapes(s, 6, [P.ink, P.violet, P.coral], 450);
		});

		// S4 — курсор «клацає» по зайвій кнопці, і вона розлітається
		at(3100, () => {
			const s = scene(P.blue, 'up');
			const b = mk('div', 'lh-fakebtn', 'Зайва кнопка', s);
			Object.assign(b.style, { background: P.paper, color: P.ink });
			pop(b, 0, -6, 360);
			const cur = mk('div', 'lh-cursor', null, s);
			cur.innerHTML =
				'<svg viewBox="0 0 24 24" width="100%" height="100%" aria-hidden="true"><path d="M4 2.5l6.8 18.2 2.5-7.3 7.4-2.6z" fill="#0a0c10" stroke="#f1efe8" stroke-width="1.6" stroke-linejoin="round"/></svg>';
			at(300, () => {
				const br = b.getBoundingClientRect();
				const sr = s.getBoundingClientRect();
				const cs = cur.offsetWidth;
				// вістря курсора (≈ 0.17 ширини) — у центр кнопки
				const tx = br.left + br.width * 0.55 - sr.left - cs * 0.17;
				const ty = br.top + br.height * 0.55 - sr.top - cs * 0.1;
				Object.assign(cur.style, { left: tx + 'px', top: ty + 'px', opacity: '1' });
				cur.animate(
					[
						{ transform: `translate(${sr.width * 0.35}px, ${sr.height * 0.3}px)` },
						{ transform: 'translate(0,0)', offset: 0.78 },
						{ transform: 'translate(0,0) scale(.8)', offset: 0.9 },
						{ transform: 'translate(0,0) scale(1)' }
					],
					{ duration: 440, easing: 'cubic-bezier(.3,.7,.2,1)', fill: 'both' }
				);
			});
			at(720, () => {
				const r = b.getBoundingClientRect();
				b.animate([{ transform: 'scale(1,1)' }, { transform: 'scale(1.25,.55)', offset: 0.5 }, { transform: 'scale(0,0)' }], {
					duration: 160,
					easing: 'ease-in',
					fill: 'both'
				});
				cur.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 300, delay: 120, fill: 'both' });
				burst(r.left + r.width / 2, r.top + r.height / 2, 1.1, [P.paper, P.ink, P.yellow]);
				shakeAd(1.1);
				const t = mk('div', 'lh-t lh-wrap', null, s);
				Object.assign(t.style, { fontSize: 'min(9.5vw,14vh)', color: P.paper });
				const zero = mk('span', null, '0', t);
				zero.style.color = P.yellow;
				t.append(' зайвих кнопок.');
				slam(t, { delay: 90, from: 2.4, power: 0.4 });
			});
		});

		// S5 — фон не змінюється (без спалахів): слова по черзі виїжджають
		// знизу у «слоті», кожне зі своєю іконкою. Інтервал ~0.42 с.
		at(4300, () => {
			const s = scene(P.violet, 'split');
			const row = mk('div', 'lh-s5', null, s);
			const ic = mk('div', 'lh-s5-ic', null, row);
			const slot = mk('div', 'lh-s5-slot', null, row);
			const words: [string, 'bolt' | 'off' | 'star'][] = [
				['Швидко.', 'bolt'],
				['Офлайн.', 'off'],
				['Гарно.', 'star']
			];
			// слот одразу під найширше слово: ширина не змінюється — нічого не обрізається
			const probe = mk('span', 'lh-s5-w', null, slot);
			slot.style.width =
				Math.max(
					...words.map(([w]) => {
						probe.textContent = w;
						return probe.offsetWidth;
					})
				) + 'px';
			probe.remove();
			let prevW: HTMLElement | null = null;
			let prevI: HTMLElement | null = null;
			words.forEach(([w, kind], i) => {
				at(i * 420, () => {
					const el = mk('span', 'lh-s5-w', w, slot);
					if (prevW) {
						const old = prevW;
						old.animate([{ transform: 'translateY(0)' }, { transform: 'translateY(-115%)' }], {
							duration: 220,
							easing: 'cubic-bezier(.6,0,1,1)',
							fill: 'both'
						}).finished.then(() => old.remove()).catch(() => {});
					}
					el.animate([{ transform: 'translateY(115%)' }, { transform: 'translateY(0)' }], {
						duration: 380,
						delay: prevW ? 90 : 0,
						easing: EXPO,
						fill: 'both'
					});
					if (prevI) {
						const oi = prevI;
						oi.animate([{ transform: 'scale(1) rotate(0)' }, { transform: 'scale(0) rotate(90deg)' }], {
							duration: 200,
							easing: 'ease-in',
							fill: 'both'
						}).finished.then(() => oi.remove()).catch(() => {});
					}
					const icon = mk('div', `lh-s5-i lh-s5-${kind}`, null, ic);
					if (kind === 'off') mk('div', 'lh-s5-slash', null, icon);
					pop(icon, prevI ? 120 : 0, 0, 420);
					prevW = el;
					prevI = icon;
				});
			});
		});

		// S6 — логотип, удар, FLIP у шапку
		at(5650, () => {
			const s = scene(P.ink, 'circle');
			const t = mk('div', 'lh-t', null, s);
			Object.assign(t.style, { fontSize: 'min(19vw,30vh)', color: P.paper });
			const ls = letters(t, 'M1 ID');
			const one = ls[1];
			if (one) one.style.color = P.violet;
			ls.forEach((l, i) =>
				slam(l, { delay: 120 + i * 70, from: 3, rot: rnd(-25, 25), dur: 260, power: i === 4 ? 1 : 0 })
			);
			at(520, () => {
				const r = t.getBoundingClientRect();
				burst(r.left + r.width / 2, r.top + r.height / 2, 1.4, [P.violet, P.paper, P.coral, P.yellow]);
			});
			at(1150, () => {
				const from = t.getBoundingClientRect();
				const to = brand?.getBoundingClientRect();
				if (to && to.height > 0) {
					const sc = (to.height / from.height) * 1.25;
					const dx = to.left + to.width / 2 - (from.left + from.width / 2);
					const dy = to.top + to.height / 2 - (from.top + from.height / 2);
					t.animate([{ transform: 'none' }, { transform: `translate(${dx}px, ${dy}px) scale(${sc})` }], {
						duration: 520,
						easing: 'cubic-bezier(.7,0,.2,1)',
						fill: 'both'
					});
				}
				at(470, endAd);
			});
		});
	}

	function endAd(): void {
		if (!html.classList.contains('lh-ad-on')) return;
		adRun++;
		timers.forEach(clearTimeout);
		timers = [];
		skip.hidden = true;
		html.classList.remove('lh-lock');
		const f = ad.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 220, fill: 'both' });
		f.finished
			.then(() => {
				html.classList.remove('lh-ad-on');
				ad.replaceChildren();
				f.cancel();
			})
			.catch(() => {});
		void intro();
	}

	// ── вказівник, скрол ──
	const ptr = { x: -9999, y: -9999, nx: 0, ny: 0, active: false };
	const par = { x: 0, y: 0 };
	let p = 0;
	const onMove = (e: PointerEvent): void => {
		ptr.x = e.clientX;
		ptr.y = e.clientY;
		ptr.active = e.pointerType === 'mouse';
		ptr.nx = e.clientX / innerWidth - 0.5;
		ptr.ny = e.clientY / innerHeight - 0.5;
	};
	const onLeave = (): void => {
		ptr.active = false;
		ptr.nx = ptr.ny = 0;
	};
	const onDown = (e: PointerEvent): void => {
		// вибух від кліку — лише мишею: на телефоні дотик = початок скролу
		if (e.pointerType !== 'mouse') return;
		if (!ready || (e.target as Element | null)?.closest('a,button')) return;
		burst(e.clientX, e.clientY, 0.75);
	};
	const onScroll = (): void => {
		const max = root.offsetHeight - innerHeight;
		p = max > 0 ? Math.min(1, Math.max(0, scrollY / max)) : 0;
		if (introRunning && scrollY > 4) finishIntro();
	};

	// ── підписи на скріншоті ──
	let calloutsOn = false;
	let avgRaf = 0;
	function countAvg(): void {
		if (!avg) return;
		cancelAnimationFrame(avgRaf);
		const t0 = performance.now();
		const tick = (t: number): void => {
			const k = Math.min(1, (t - t0) / 900);
			avg.textContent = (10.3 * (1 - Math.pow(1 - k, 3))).toFixed(1);
			if (k < 1) avgRaf = requestAnimationFrame(tick);
		};
		avgRaf = requestAnimationFrame(tick);
	}

	// ── головний цикл ──
	const K = 170;
	const D = 13;
	let last = performance.now();
	let raf = 0;
	function frame(now: number): void {
		const dt = Math.min(0.033, (now - last) / 1000);
		last = now;

		for (let i = pending.length - 1; i >= 0; i--) {
			const pq = pending[i];
			if (pq && now >= pq.t) {
				pq.it.vx += pq.vx;
				pq.it.vy += pq.vy;
				pq.it.vr += pq.vr;
				pending.splice(i, 1);
			}
		}

		par.x += (ptr.nx - par.x) * Math.min(1, dt * 5);
		par.y += (ptr.ny - par.y) * Math.min(1, dt * 5);

		if (ready) {
			const sr = stage.getBoundingClientRect();
			for (const it of items) {
				let ax = -K * it.x - D * it.vx;
				let ay = -K * it.y - D * it.vy;
				let ar = -K * it.r - D * it.vr;
				if (ptr.active && p < 0.03) {
					const dx = sr.left + it.cx + it.x - ptr.x;
					const dy = sr.top + it.cy + it.y - ptr.y;
					const d = Math.hypot(dx, dy);
					const R = 150;
					if (d < R && d > 0.1) {
						const f = (1 - d / R) ** 2 * 5200;
						ax += (dx / d) * f;
						ay += (dy / d) * f;
						ar += (dx / d) * f * 0.02;
					}
				}
				it.vx += ax * dt;
				it.vy += ay * dt;
				it.vr += ar * dt;
				it.x += it.vx * dt;
				it.y += it.vy * dt;
				it.r += it.vr * dt;
				// розвал при скролі: горизонталь лінійно, падіння з прискоренням
				const k = Math.min(1, Math.max(0, (p - it.dl) / 0.42));
				it.el.style.transform = `translate3d(${(it.x + it.sx * k).toFixed(2)}px,${(it.y + it.sy * k * k).toFixed(2)}px,0) rotate(${(it.r + it.sr * k).toFixed(2)}deg)`;
				it.el.style.opacity = k < 0.84 ? '' : Math.max(0, 1 - (k - 0.84) / 0.16).toFixed(3);
				if (k >= 0.86 && !it.landed) {
					it.landed = true;
					const r = it.el.getBoundingClientRect();
					if (r.width) crumble(r.left + r.width / 2, r.top + r.height * 0.8, it.color);
				} else if (k < 0.6) it.landed = false;
			}
			sub.style.translate = `0 ${(-p * 120).toFixed(1)}px`;
			sub.style.opacity = Math.max(0, 1 - p * 3).toFixed(3);
		}

		l1.style.transform = `translate3d(${(-par.x * 10).toFixed(2)}px,${(-par.y * 8).toFixed(2)}px,0)`;
		l2.style.transform = `translate3d(${(par.x * 26).toFixed(2)}px,${(par.y * 18).toFixed(2)}px,0)`;
		l3.style.transform = `translate3d(${(-par.x * 14).toFixed(2)}px,${(-par.y * 10).toFixed(2)}px,0)`;
		l4.style.transform = `translate3d(${(-par.x * 18).toFixed(2)}px,${(-par.y * 12).toFixed(2)}px,0)`;

		// скріншот: у спокої схований під нижнім краєм; щойно юзер гортнув —
		// одразу виїжджає знизу (швидкий старт, плавне гальмування), підіймається
		// під літери, вирівнюється і стає по центру екрана
		const H = stage.clientHeight;
		const sh = shot.offsetHeight;
		const tt = Math.min(1, p / 0.72);
		const t = 1 - Math.pow(1 - tt, 2.6);
		const y0 = H + 8;
		// підписи списком під кадром: телефон (стовпчик) і ноутбук/планшет (рядок)
		const listBelow = innerWidth <= 1100 && innerHeight > 500;
		const reserve = innerWidth <= 760 ? 200 : 110;
		const y1 = listBelow ? Math.max(76, (H - sh - reserve) / 2 + 20) : Math.max(72, (H - sh) / 2 + 24);
		shot.style.transform = `translate(-50%, ${(y0 + (y1 - y0) * t).toFixed(1)}px) perspective(1800px) rotateX(${(28 * (1 - t)).toFixed(2)}deg) scale(${(0.9 + 0.1 * t).toFixed(4)})`;

		// підписи на скріншоті: з'являються, коли він доїхав до центру
		// гістерезис: щоб підписи не блимали, коли прогрес коливається біля порогу
		const on = ready && (calloutsOn ? p > 0.7 : p > 0.76);
		if (on !== calloutsOn) {
			calloutsOn = on;
			shot.classList.toggle('lh-on', on);
			if (on) countAvg();
		}

		shake *= Math.exp(-dt * 9);
		title.style.transform =
			shake > 0.2
				? `translate3d(${((Math.random() - 0.5) * shake).toFixed(2)}px,${((Math.random() - 0.5) * shake).toFixed(2)}px,0)`
				: '';

		if (ctx) drawFx(ctx, dt);
		raf = requestAnimationFrame(frame);
	}

	function drawFx(c: CanvasRenderingContext2D, dt: number): void {
		c.clearRect(0, 0, innerWidth, innerHeight);
		for (let i = flashes.length - 1; i >= 0; i--) {
			const f = flashes[i]!;
			f.t += dt;
			const k = f.t / f.life;
			if (k >= 1) {
				flashes.splice(i, 1);
				continue;
			}
			c.globalAlpha = (1 - k) * 0.55;
			c.fillStyle = C.fg;
			c.beginPath();
			c.arc(f.x, f.y, f.r * (0.6 + k * 0.8), 0, 7);
			c.fill();
		}
		for (let i = rings.length - 1; i >= 0; i--) {
			const r = rings[i]!;
			r.t += dt;
			if (r.t < 0) continue;
			const k = r.t / r.life;
			if (k >= 1) {
				rings.splice(i, 1);
				continue;
			}
			c.globalAlpha = (1 - k) * 0.75;
			c.strokeStyle = r.w > 5 ? C.accent : C.fg;
			c.lineWidth = Math.max(0.5, r.w * (1 - k));
			c.beginPath();
			c.arc(r.x, r.y, r.max * (1 - Math.pow(1 - k, 4)), 0, 7);
			c.stroke();
		}
		for (let i = shards.length - 1; i >= 0; i--) {
			const s = shards[i]!;
			s.t += dt;
			const k = s.t / s.life;
			if (k >= 1) {
				shards.splice(i, 1);
				continue;
			}
			const drag = Math.exp(-3.4 * dt);
			s.vx *= drag;
			s.vy *= drag;
			s.vy += 520 * dt;
			s.x += s.vx * dt;
			s.y += s.vy * dt;
			s.rot += s.vrot * dt;
			c.globalAlpha = 1 - k * k;
			c.fillStyle = s.c;
			c.save();
			c.translate(s.x, s.y);
			if (s.chunk) {
				c.rotate(s.rot);
				const w = s.w * (1 - k * 0.5);
				c.fillRect(-w / 2, -w / 2, w, w);
			} else {
				c.rotate(Math.atan2(s.vy, s.vx));
				const len = 4 + Math.hypot(s.vx, s.vy) * 0.03;
				c.fillRect(-len, -s.w / 2, len, s.w);
			}
			c.restore();
		}
		c.globalAlpha = 1;
	}

	// ── старт ──
	const onSkip = (): void => endAd();
	addEventListener('resize', resize);
	addEventListener('pointermove', onMove, { passive: true });
	document.addEventListener('pointerleave', onLeave);
	stage.addEventListener('pointerdown', onDown);
	addEventListener('scroll', onScroll, { passive: true });
	skip.addEventListener('click', onSkip);
	resize();
	onScroll();

	const start = (): void => {
		if (!alive || raf) return;
		raf = requestAnimationFrame(frame);
		if (html.classList.contains('lh-ad-on') || !html.dataset.lhSeen) {
			html.dataset.lhSeen = '1';
			playAd();
		} else void intro();
	};
	// шрифт міг дозавантажитись уже після старту (або спрацював fallback-таймер):
	// перераховуємо ширину слова в слоті й центри літер
	const onFonts = (): void => {
		layoutRow();
		if (ready) computeCenters();
	};
	document.fonts?.addEventListener('loadingdone', onFonts);
	const fontsReady = document.fonts ? document.fonts.ready : Promise.resolve();
	void fontsReady.then(start);
	const fallback = window.setTimeout(start, 1500);

	return () => {
		alive = false;
		run++;
		adRun++;
		timers.forEach(clearTimeout);
		clearTimeout(fallback);
		cancelAnimationFrame(raf);
		cancelAnimationFrame(avgRaf);
		anims.forEach((a) => a.cancel());
		removeEventListener('resize', resize);
		document.fonts?.removeEventListener('loadingdone', onFonts);
		removeEventListener('pointermove', onMove);
		document.removeEventListener('pointerleave', onLeave);
		stage.removeEventListener('pointerdown', onDown);
		removeEventListener('scroll', onScroll);
		skip.removeEventListener('click', onSkip);
		html.classList.remove('lh-anim', 'lh-ad-on', 'lh-lock');
	};
}
