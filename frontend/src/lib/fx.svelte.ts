/**
 * M1 ID · FX-частинки «крити як у майнкрафті» ⭐
 * Зірки (4-променевий спарк) розлітаються з акцентним кольором
 * при приємних подіях. Налаштування — у SettingsModal.
 *
 * Техніка: елементи додаються прямо в document.body (позиція fixed),
 * бо .glass-картки — containing block для fixed і «крали б» координати.
 */

export type FxEvent = 'hw' | 'order' | 'sync' | 'style';

/** людські назви подій для налаштувань */
export const FX_EVENTS: { key: FxEvent; name: string; hint: string }[] = [
	{ key: 'hw', name: 'Здана робота', hint: 'Домашка або перездача успішно відправлена' },
	{ key: 'order', name: 'Замовлення', hint: 'Покупка в магазині пройшла' },
	{ key: 'sync', name: 'Оновлення', hint: 'Дані синхронізовано з MyStat' },
	{ key: 'style', name: 'Зміна стилю', hint: 'Новий режим теми чи акцент' }
];

type FxEvents = Record<FxEvent, boolean>;

const LS_KEY = 'm1id.fx.v1';
const DEFAULTS = {
	enabled: true,
	count: 30,
	palette: 'accent' as 'accent' | 'party',
	events: { hw: true, order: true, sync: true, style: true } as FxEvents
};

/** шлях 4-променевої зірки (viewBox 0 0 100 100) */
const STAR_PATH =
	'M63,37c-6.7-4-4-27-13-27s-6.3,23-13,27-27,4-27,13,20.3,9,27,13,' +
	'4,27,13,27,6.3-23,13-27,27-4,27-13-20.3-9-27-13Z';

class FxStore {
	enabled = $state(true);
	/** скільки зірок за один спалах (4..30) */
	count = $state(DEFAULTS.count);
	/** 'accent' — лише акцент; 'party' — акцент + вторинний + білий */
	palette = $state<'accent' | 'party'>('accent');
	events = $state<FxEvents>({ ...DEFAULTS.events });

	restore(): void {
		if (typeof localStorage === 'undefined') return;
		try {
			const raw = localStorage.getItem(LS_KEY);
			if (!raw) return;
			const j = JSON.parse(raw) as Partial<typeof DEFAULTS>;
			if (typeof j.enabled === 'boolean') this.enabled = j.enabled;
			if (typeof j.count === 'number')
				this.count = Math.min(30, Math.max(4, Math.round(j.count)));
			if (j.palette === 'accent' || j.palette === 'party') this.palette = j.palette;
			if (j.events)
				for (const e of FX_EVENTS)
					if (typeof j.events[e.key] === 'boolean') this.events[e.key] = j.events[e.key]!;
		} catch {
			/* битий JSON — дефолти */
		}
	}

	private save(): void {
		try {
			localStorage.setItem(
				LS_KEY,
				JSON.stringify({
					enabled: this.enabled,
					count: this.count,
					palette: this.palette,
					events: this.events
				})
			);
		} catch {
			/* ignore */
		}
	}

	set(v: Partial<Pick<FxStore, 'enabled' | 'count' | 'palette'>>): void {
		if (v.enabled !== undefined) this.enabled = v.enabled;
		if (v.count !== undefined)
			this.count = Math.min(30, Math.max(4, Math.round(v.count)));
		if (v.palette !== undefined) this.palette = v.palette;
		this.save();
	}

	setEvent(key: FxEvent, on: boolean): void {
		this.events[key] = on;
		this.save();
	}

	/**
	 * Запустити салют події.
	 * @param el елемент, з центру якого полетять зірки (якщо не заданий — центр екрана)
	 * @param force звести навіть якщо подія вимкнена (кнопка «Перевірити»)
	 */
	celebrate(ev: FxEvent, el?: Element | null, force = false): void {
		if (typeof document === 'undefined') return;
		if (!this.enabled) return;
		if (!force && !this.events[ev]) return;

		let cx: number;
		let cy: number;
		if (el) {
			const r = el.getBoundingClientRect();
			cx = r.left + r.width / 2;
			cy = r.top + r.height / 2;
		} else {
			cx = window.innerWidth / 2;
			cy = window.innerHeight * 0.42;
		}
		this.burst(cx, cy);
	}

	private colors(): string[] {
		const cs = getComputedStyle(document.documentElement);
		const acc = cs.getPropertyValue('--accent').trim() || '#6c7cff';
		if (this.palette === 'party') {
			const sec = cs.getPropertyValue('--cyan').trim() || '#22d3ee';
			return [acc, sec, '#ffffff'];
		}
		return [acc, acc, '#ffffff'];
	}

	private burst(x: number, y: number): void {
		const colors = this.colors();
		const n = Math.max(4, Math.min(30, Math.round(this.count)));
		for (let i = 0; i < n; i++) {
			// рівномірний веєр + джиттер
			const ang = (i / n) * Math.PI * 2 + Math.random() * 0.5;
			const dist = 64 + Math.random() * 92;
			this.spawn(
				x,
				y,
				colors[i % colors.length],
				10 + Math.random() * 11,
				Math.cos(ang) * dist,
				Math.sin(ang) * dist + 34 /* гравітація: трохи падають униз */,
				(Math.random() * 420 - 210) | 0,
				650 + Math.random() * 450,
				Math.random() * 110
			);
		}
	}

	private spawn(
		x: number,
		y: number,
		color: string,
		size: number,
		ex: number,
		ey: number,
		rot: number,
		dur: number,
		delay: number
	): void {
		const d = document.createElement('div');
		d.className = 'fx-star';
		d.style.left = `${x}px`;
		d.style.top = `${y}px`;
		d.style.width = `${size}px`;
		d.style.height = `${size}px`;
		d.style.color = color;
		d.style.setProperty('--ex', `${ex.toFixed(1)}px`);
		d.style.setProperty('--ey', `${ey.toFixed(1)}px`);
		d.style.setProperty('--rot', `${rot}deg`);
		d.style.animationDuration = `${dur.toFixed(0)}ms`;
		d.style.animationDelay = `${delay.toFixed(0)}ms`;
		d.innerHTML = `<svg viewBox="0 0 100 100" aria-hidden="true"><path fill="currentColor" d="${STAR_PATH}"/></svg>`;
		d.addEventListener('animationend', () => d.remove(), { once: true });
		document.body.appendChild(d);
		// страховка, якщо animationend загубився (вкладка у фоні)
		window.setTimeout(() => d.remove(), dur + delay + 400);
	}
}

export const fx = new FxStore();
