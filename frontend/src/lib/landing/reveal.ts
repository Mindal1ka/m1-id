// Моушн решти лендінгу (після hero): Svelte-екшени без бібліотек.
//   use:wipe      — кадр відкривається шторкою зі «сканувальною» фіолетовою смугою
//                   (той самий мотив, що й контурний рядок у hero) + повільний zoom-out
//   use:words     — заголовок виїжджає по словах з-під маски
//   use:chars     — те саме по літерах (фінальна кнопка)
//   use:parallax  — елемент рухається повільніше/швидше за скрол
// Усе вимикається при prefers-reduced-motion, контент лишається видимим.

interface ActionResult {
	destroy: () => void;
}

const EXPO = 'cubic-bezier(.16,1,.3,1)';
const AC = '#9d8cff';
const noop: ActionResult = { destroy: () => {} };

const reduced = (): boolean =>
	typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;

function onEnter(node: Element, cb: () => void, threshold = 0.2): () => void {
	const io = new IntersectionObserver(
		(es) => {
			if (!es.some((e) => e.isIntersecting)) return;
			io.disconnect();
			cb();
		},
		{ threshold, rootMargin: '0px 0px -8% 0px' }
	);
	io.observe(node);
	return () => io.disconnect();
}

// ── шторка ──
export type WipeDir = 'left' | 'right' | 'up';

export function wipe(node: HTMLElement, dir: WipeDir = 'left'): ActionResult {
	if (reduced()) return noop;
	const hidden =
		dir === 'left' ? 'inset(0 100% 0 0)' : dir === 'right' ? 'inset(0 0 0 100%)' : 'inset(100% 0 0 0)';
	node.style.clipPath = hidden;
	// спостерігаємо за батьком: Chrome враховує clip-path самого елемента,
	// і повністю «закрита» шторкою ціль ніколи не стає видимою для IO
	const watch = node.parentElement ?? node;
	const stop = onEnter(watch, () => {
		const a = node.animate([{ clipPath: hidden }, { clipPath: 'inset(0 0 0 0)' }], {
			duration: 1100,
			easing: 'cubic-bezier(.7,0,.2,1)'
		});
		node.style.clipPath = '';
		a.finished.then(() => node.classList.add('rv-done')).catch(() => {});

		const img = node.querySelector('img');
		img?.animate([{ transform: 'scale(1.14)' }, { transform: 'scale(1)' }], {
			duration: 1700,
			easing: EXPO
		});

		if (dir !== 'up') {
			// смуга, що «малює» кадр — як у контурному рядку hero
			if (getComputedStyle(node).position === 'static') node.style.position = 'relative';
			const bar = document.createElement('i');
			Object.assign(bar.style, {
				position: 'absolute',
				top: '0',
				bottom: '0',
				width: '4px',
				background: AC,
				zIndex: '3',
				pointerEvents: 'none',
				[dir === 'left' ? 'left' : 'right']: '0'
			});
			node.appendChild(bar);
			const w = node.offsetWidth;
			const sx = dir === 'left' ? w : -w;
			bar
				.animate(
					[
						{ transform: 'translateX(0)', opacity: 1 },
						{ transform: `translateX(${sx}px)`, opacity: 1, offset: 0.96 },
						{ transform: `translateX(${sx}px)`, opacity: 0 }
					],
					{ duration: 1100, easing: 'cubic-bezier(.7,0,.2,1)', fill: 'both' }
				)
				.finished.then(() => bar.remove())
				.catch(() => bar.remove());
		}
	}, 0.18);
	return {
		destroy: () => {
			stop();
			node.style.clipPath = '';
		}
	};
}

// ── поява по словах / літерах ──
function split(node: HTMLElement, by: 'word' | 'char', delay: number, step: number): ActionResult {
	if (reduced()) return noop;
	const text = node.textContent ?? '';
	const label = text.replace(/\s+/g, ' ').trim();
	node.setAttribute('aria-label', label);
	node.textContent = '';
	if (by === 'char') node.style.whiteSpace = 'nowrap';
	const inners: HTMLElement[] = [];
	const parts = by === 'word' ? label.split(' ') : [...label];
	parts.forEach((part, i) => {
		const outer = document.createElement('span');
		outer.setAttribute('aria-hidden', 'true');
		Object.assign(outer.style, {
			display: 'inline-block',
			overflow: 'clip',
			verticalAlign: 'top',
			paddingBottom: '0.12em',
			marginBottom: '-0.12em'
		});
		const inner = document.createElement('span');
		inner.textContent = part === ' ' ? ' ' : part;
		Object.assign(inner.style, { display: 'inline-block', transform: 'translateY(115%)' });
		outer.appendChild(inner);
		node.appendChild(outer);
		if (by === 'word' && i < parts.length - 1) node.appendChild(document.createTextNode(' '));
		inners.push(inner);
	});
	const stop = onEnter(node, () => {
		inners.forEach((el, i) =>
			el.animate(
				[
					{ transform: 'translateY(115%) rotate(4deg)' },
					{ transform: 'translateY(0) rotate(0)' }
				],
				{ duration: 950, delay: delay + i * step, easing: EXPO, fill: 'both' }
			)
		);
	}, 0.3);
	return {
		destroy: () => {
			stop();
			node.textContent = text;
		}
	};
}

export const words = (node: HTMLElement, delay = 0): ActionResult => split(node, 'word', delay, 70);
export const chars = (node: HTMLElement, delay = 0): ActionResult => split(node, 'char', delay, 38);

// ── паралакс (один спільний обробник скролу) ──
interface Plx {
	node: HTMLElement;
	speed: number;
	off: number;
}
const plx = new Set<Plx>();
let plxRaf = 0;
function plxTick(): void {
	plxRaf = 0;
	const vh = innerHeight;
	// на вузьких екранах (одна колонка) паралакс слабший, щоб номери не наїжджали на текст
	const k = innerWidth < 960 ? 0.3 : 1;
	for (const e of plx) {
		const r = e.node.getBoundingClientRect();
		const center = r.top + r.height / 2 - e.off; // позиція без власного зсуву
		if (center < -vh || center > vh * 2) continue;
		e.off = (center - vh / 2) * e.speed * k;
		e.node.style.transform = `translate3d(0, ${e.off.toFixed(1)}px, 0)`;
	}
}
const plxSchedule = (): void => {
	if (!plxRaf) plxRaf = requestAnimationFrame(plxTick);
};

export function parallax(node: HTMLElement, speed = -0.08): ActionResult {
	if (reduced()) return noop;
	const e: Plx = { node, speed, off: 0 };
	if (plx.size === 0) {
		addEventListener('scroll', plxSchedule, { passive: true });
		addEventListener('resize', plxSchedule);
	}
	plx.add(e);
	plxSchedule();
	return {
		destroy: () => {
			plx.delete(e);
			node.style.transform = '';
			if (plx.size === 0) {
				removeEventListener('scroll', plxSchedule);
				removeEventListener('resize', plxSchedule);
			}
		}
	};
}

// ── запасний кадр ──
// Мобільних скрінів (m-*.jpg) може ще не бути (їх знімає tools/shots.mjs --mobile).
// Якщо кадр не завантажився — прибираємо <source> і показуємо ПК-скрін,
// обрізаний під вертикальний екран (клас is-crop, позицію задає CSS/--pos).
export function fallback(img: HTMLImageElement): ActionResult {
	const fail = (): void => {
		img.parentElement?.querySelectorAll('source').forEach((s) => s.remove());
		const fb = img.dataset.fallback;
		if (fb && !img.src.endsWith(fb)) img.src = fb;
		img.classList.add('is-crop');
	};
	if (img.complete && img.naturalWidth === 0 && img.currentSrc) fail();
	img.addEventListener('error', fail, { once: true });
	return { destroy: () => img.removeEventListener('error', fail) };
}

// ── мобільна сцена «айфон» ──
// Звичайна секція (без закріпленого скролу): телефон «вилазить» знизу, коли
// секція доїхала до екрана; розділи перемикаються стрілками ‹ ›, крапками
// або свайпом по екрану телефона. Скріни їдуть вбік, текст зверху — в такт.
export function story(node: HTMLElement): ActionResult {
	const texts = [...node.querySelectorAll<HTMLElement>('.st-txt')];
	const shots = [...node.querySelectorAll<HTMLElement>('.st-shot')];
	const dots = [...node.querySelectorAll<HTMLButtonElement>('.st-dots button')];
	const prev = node.querySelector<HTMLButtonElement>('.st-prev');
	const next = node.querySelector<HTMLButtonElement>('.st-next');
	const screen = node.querySelector<HTMLElement>('.st-screen');
	const N = texts.length;
	let cur = 0;

	const render = (): void => {
		texts.forEach((el, i) => el.classList.toggle('on', i === cur));
		dots.forEach((el, i) => {
			el.classList.toggle('on', i === cur);
			el.setAttribute('aria-current', i === cur ? 'true' : 'false');
		});
		shots.forEach((el, i) => {
			el.style.transform = `translate3d(${(i - cur) * 100}%, 0, 0)`;
		});
	};
	const go = (i: number): void => {
		if (!N) return;
		cur = (i + N) % N; // по колу: після останнього — перший
		render();
	};
	const onPrev = (): void => go(cur - 1);
	const onNext = (): void => go(cur + 1);
	const onDot = (e: Event): void => {
		const i = dots.indexOf(e.currentTarget as HTMLButtonElement);
		if (i >= 0) go(i);
	};

	// свайп: горизонтальний рух пальцем по екрану телефона
	let sx = 0;
	let sy = 0;
	let tracking = false;
	const onDown = (e: PointerEvent): void => {
		tracking = true;
		sx = e.clientX;
		sy = e.clientY;
	};
	const onUp = (e: PointerEvent): void => {
		if (!tracking) return;
		tracking = false;
		const dx = e.clientX - sx;
		const dy = e.clientY - sy;
		if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy) * 1.2) go(cur + (dx < 0 ? 1 : -1));
	};
	const onCancel = (): void => {
		tracking = false;
	};

	// поява телефона, коли секція доїхала до екрана
	let io: IntersectionObserver | null = null;
	if (reduced()) node.classList.add('st-in');
	else {
		io = new IntersectionObserver(
			(es) => {
				if (!es.some((e) => e.isIntersecting)) return;
				node.classList.add('st-in');
				io?.disconnect();
			},
			{ threshold: 0.25 }
		);
		io.observe(node);
	}

	prev?.addEventListener('click', onPrev);
	next?.addEventListener('click', onNext);
	dots.forEach((d) => d.addEventListener('click', onDot));
	screen?.addEventListener('pointerdown', onDown);
	screen?.addEventListener('pointerup', onUp);
	screen?.addEventListener('pointercancel', onCancel);
	render();

	return {
		destroy: () => {
			io?.disconnect();
			prev?.removeEventListener('click', onPrev);
			next?.removeEventListener('click', onNext);
			dots.forEach((d) => d.removeEventListener('click', onDot));
			screen?.removeEventListener('pointerdown', onDown);
			screen?.removeEventListener('pointerup', onUp);
			screen?.removeEventListener('pointercancel', onCancel);
		}
	};
}
