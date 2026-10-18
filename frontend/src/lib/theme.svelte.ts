/**
 * M1 ID · система тем v3 — два незалежних виміри:
 *  1) РЕЖИМ оформлення (Темна / Світла / Неон) — поверхні, текст, скло, фон;
 *  2) АКЦЕНТ (12 кольорів) — кнопки, чіпи, посилання, плями Aurora.
 * Будь-яка комбінація працює. Усе живе на CSS-змінних :root,
 * вибір — у localStorage як {mode, accent}.
 */

import { Moon, Sun, Zap } from '@lucide/svelte';
import { api } from '$lib/api/client';

export type ModeKey = 'dark' | 'light' | 'neon';

export type ModeDef = {
	key: ModeKey;
	name: string;
	icon: typeof Moon;
	base: ThemeBase;
};

/** Стиль появи елементів (віджети, картки, розклад) */
export type AnimKey = 'off' | 'fade' | 'rise' | 'slide' | 'pop';

export type AnimDef = {
	key: AnimKey;
	name: string;
};

export const ANIMS: AnimDef[] = [
	{ key: 'off', name: 'Вимк' },
	{ key: 'fade', name: 'Плавно' },
	{ key: 'rise', name: 'Знизу' },
	{ key: 'slide', name: 'Зсув' },
	{ key: 'pop', name: 'Сплив' }
];

export type AccentDef = {
	key: string;
	name: string;
	/** основний акцент (кнопки, чіпи, посилання) */
	accent: string;
	/** вторинний колір -> --cyan */
	sec: string;
	/** три кольори плям Aurora */
	aur: [string, string, string];
};

export type ThemeBase = {
	scheme: 'light' | 'dark';
	bg: string;
	surface: string;
	surface2: string;
	text: string;
	textDim: string;
	textFaint: string;
	glassBg: string;
	glassBgHover: string;
	glassBorder: string;
	scrollThumb: string;
	scrollThumbHover: string;
	/** blend плям Aurora ('screen' світиться на темному, 'normal' — м'яка пастель на світлому) */
	aurBlend: string;
	aurOp: number;
};

/* --- утиліти кольору --- */

function hexToRgb(hex: string): [number, number, number] {
	const h = hex.replace('#', '');
	const v =
		h.length === 3
			? h
					.split('')
					.map((c) => c + c)
					.join('')
			: h;
	return [
		parseInt(v.slice(0, 2), 16),
		parseInt(v.slice(2, 4), 16),
		parseInt(v.slice(4, 6), 16)
	];
}

/** rgba з hex з альфою — для --accent-soft */
function rgba(hex: string, a: number): string {
	const [r, g, b] = hexToRgb(hex);
	return `rgba(${r}, ${g}, ${b}, ${a})`;
}

/** освітлити до білого (для hover-відтінку кнопки) */
function lighten(hex: string, t: number): string {
	const [r, g, b] = hexToRgb(hex);
	const m = (x: number) => Math.round(x + (255 - x) * t);
	return `rgb(${m(r)}, ${m(g)}, ${m(b)})`;
}

/* --- бази поверхонь --- */

/* Чистий сучасний стиль: спокійні суцільні поверхні, тонкі межі, без скла. */
const DARK_BASE: ThemeBase = {
	scheme: 'dark',
	bg: '#0b0c0f',
	surface: '#131519',
	surface2: '#1a1d23',
	text: '#eceef2',
	textDim: '#9aa1ad',
	textFaint: '#6f7684',
	glassBg: '#131519',
	glassBgHover: '#1a1d23',
	glassBorder: 'rgba(255, 255, 255, 0.08)',
	scrollThumb: '#22262e',
	scrollThumbHover: '#2e333d',
	aurBlend: 'screen',
	aurOp: 0.28
};

const LIGHT_BASE: ThemeBase = {
	scheme: 'light',
	bg: '#f5f6f8',
	surface: '#ffffff',
	surface2: '#f0f2f5',
	text: '#0f172a',
	textDim: '#475569',
	textFaint: '#64748b',
	glassBg: '#ffffff',
	glassBgHover: '#f0f2f5',
	glassBorder: 'rgba(15, 23, 42, 0.09)',
	scrollThumb: '#cfd5de',
	scrollThumbHover: '#b6bfcc',
	aurBlend: 'normal',
	aurOp: 0.22
};

const NEON_BASE: ThemeBase = {
	scheme: 'dark',
	bg: '#07060c',
	surface: '#110f1a',
	surface2: '#181526',
	text: '#f1eeff',
	textDim: '#a59fc4',
	textFaint: '#75709a',
	glassBg: '#110f1a',
	glassBgHover: '#181526',
	glassBorder: 'rgba(255, 255, 255, 0.10)',
	scrollThumb: '#241f38',
	scrollThumbHover: '#312a4d',
	aurBlend: 'screen',
	aurOp: 0.45
};

/* --- режими оформлення --- */

export const MODES: ModeDef[] = [
	{ key: 'dark', name: 'Темна', icon: Moon, base: DARK_BASE },
	{ key: 'light', name: 'Світла', icon: Sun, base: LIGHT_BASE },
	{ key: 'neon', name: 'Неон', icon: Zap, base: NEON_BASE }
];

/* --- акценти (12) --- */

export const ACCENTS: AccentDef[] = [
	{
		// колір слова «має» з заголовка лендінгу — дефолт панелі
		key: 'violet',
		name: 'Лаванда',
		accent: '#9d8cff',
		sec: '#22d3ee',
		aur: ['#9d8cff', '#22d3ee', '#6c5cff']
	},
	{
		key: 'indigo',
		name: 'Індиго',
		accent: '#6c7cff',
		sec: '#22d3ee',
		aur: ['#6c7cff', '#22d3ee', '#8b5cf6']
	},
	{
		key: 'ocean',
		name: 'Океан',
		accent: '#0ea5e9',
		sec: '#34d399',
		aur: ['#0369a1', '#0ea5e9', '#22d3ee']
	},
	{
		key: 'teal',
		name: 'Бірюза',
		accent: '#14b8a6',
		sec: '#38bdf8',
		aur: ['#0f766e', '#14b8a6', '#38bdf8']
	},
	{
		key: 'mint',
		name: "М'ята",
		accent: '#10b981',
		sec: '#a3e635',
		aur: ['#059669', '#10b981', '#a3e635']
	},
	{
		key: 'sun',
		name: 'Соняшник',
		accent: '#f59e0b',
		sec: '#fbbf24',
		aur: ['#d97706', '#f59e0b', '#ef4444']
	},
	{
		key: 'coral',
		name: 'Корал',
		accent: '#fb7185',
		sec: '#f97316',
		aur: ['#e11d48', '#fb7185', '#f59e0b']
	},
	{
		key: 'fire',
		name: 'Вогонь',
		accent: '#ef4444',
		sec: '#fb923c',
		aur: ['#b91c1c', '#ef4444', '#f97316']
	},
	{
		key: 'orchid',
		name: 'Орхідея',
		accent: '#d946ef',
		sec: '#a78bfa',
		aur: ['#a21caf', '#d946ef', '#7c3aed']
	},
	{
		key: 'amethyst',
		name: 'Аметист',
		accent: '#8b5cf6',
		sec: '#e879f9',
		aur: ['#7c3aed', '#8b5cf6', '#ec4899']
	},
	{
		key: 'rose',
		name: 'Руж',
		accent: '#ec4899',
		sec: '#c084fc',
		aur: ['#be185d', '#ec4899', '#a855f7']
	},
	{
		key: 'magenta',
		name: 'Маджента',
		accent: '#ff36c7',
		sec: '#00ffc8',
		aur: ['#ff2ea6', '#00ffc8', '#7c3aed']
	}
];

/* --- чорнило чипів оцінок (MarksChipsCard): пастель читається на
   темному, але «гасне» на білому -> світла тема отримує глибокі тони.
   apply() розкладає це в --mk-{violet|blue|yellow|orange|rose|salad|green} */
const MK_INKS_DARK: Record<string, string> = {
	violet: '#aab4ff',
	blue: '#7ce4f4',
	yellow: '#ffd27a',
	orange: '#ffab80',
	rose: '#f9a8d4',
	salad: '#c9ef85',
	green: '#7cebc0'
};

const MK_INKS_LIGHT: Record<string, string> = {
	violet: '#4f46e5',
	blue: '#0891b2',
	yellow: '#b45309',
	orange: '#c2410c',
	rose: '#db2777',
	salad: '#4d7c0f',
	green: '#047857'
};

const LS_KEY = 'm1id.theme.v1';
const LS_HOVER = 'm1id.theme.hoverglow';
const LS_AURORA = 'm1id.theme.aurora';
const LS_ANIM = 'm1id.theme.anim';

/* --- хмара (як у cloud widgets): debounce PUT /api/appearance усією
   картою; при логіні pullCloud() — сервер «останнє слово». */
let serverTimer: ReturnType<typeof setTimeout> | null = null;

function scheduleServerPush(): void {
	if (serverTimer) clearTimeout(serverTimer);
	serverTimer = setTimeout(() => {
		api.appearancePut(theme.snapshot()).catch(() => {
			/* офлайн / 401 — локальний вибір живе далі; пушне пізніше */
		});
	}, 1200);
}
const DEFAULT_MODE: ModeKey = 'dark';
const DEFAULT_ACCENT = 'violet';

/** карта базових змінних для apply() */
const BASE_VARS: Record<
	keyof Omit<ThemeBase, 'scheme' | 'aurOp'>,
	string
> & { aurOp: string } = {
	bg: '--bg',
	surface: '--surface',
	surface2: '--surface-2',
	text: '--text',
	textDim: '--text-dim',
	textFaint: '--text-faint',
	glassBg: '--glass-bg',
	glassBgHover: '--glass-bg-hover',
	glassBorder: '--glass-border',
	scrollThumb: '--scroll-thumb',
	scrollThumbHover: '--scroll-thumb-hover',
	aurBlend: '--aur-blend',
	aurOp: '--aur-op'
};

class ThemeStore {
	/** активний режим і акцент (реактивні) */
	mode = $state<ModeKey>(DEFAULT_MODE);
	accent = $state<string>(DEFAULT_ACCENT);
	/** акцентна обвідка карток при наведенні (за замовчуванням вимк) */
	hoverGlow = $state(false);
	/** фон «Північне сяйво» (за замовчуванням вимк) */
	aurora = $state(false);
	/** стиль появи віджетів/карток (за замовчуванням «Знизу») */
	anim = $state<AnimKey>('rise');

	readonly modes: ModeDef[] = MODES;
	readonly accents: AccentDef[] = ACCENTS;
	readonly anims: AnimDef[] = ANIMS;

	get curMode(): ModeDef {
		return this.modes.find((m) => m.key === this.mode) ?? this.modes[0];
	}

	get curAccent(): AccentDef {
		return this.accents.find((t) => t.key === this.accent) ?? this.accents[0];
	}

	/** відновити збережений вибір (викликається в layout до рендера) */
	restore(): void {
		if (typeof localStorage === 'undefined') return;
		let raw: string | null = null;
		try {
			raw = localStorage.getItem(LS_KEY);
		} catch {
			/* приватний режим — ок */
		}
		// обвідка при наведенні (окремий ключ, за замовчуванням off)
		try {
			this.hoverGlow = localStorage.getItem(LS_HOVER) === '1';
		} catch {
			/* ignore */
		}
		try {
			this.aurora = localStorage.getItem(LS_AURORA) === '1';
		} catch {
			/* ignore */
		}
		try {
			const a = localStorage.getItem(LS_ANIM) as AnimKey | null;
			if (a && ANIMS.some((x) => x.key === a)) this.anim = a;
		} catch {
			/* ignore */
		}
		this.applyHover();
		this.applyAnim();

		let mode: ModeKey = DEFAULT_MODE;
		let accent = DEFAULT_ACCENT;

		if (raw) {
			try {
				if (raw.startsWith('{')) {
					// новий формат {mode, accent}
					const j = JSON.parse(raw) as { mode?: string; accent?: string };
					if (MODES.some((m) => m.key === j.mode)) mode = j.mode as ModeKey;
					if (ACCENTS.some((t) => t.key === j.accent)) accent = j.accent!;
				} else {
					// легасі v1/v2: одиночний ключ теми
					if (raw === 'arctic') {
						mode = 'light';
						accent = 'ocean';
					} else if (raw === 'neon') {
						mode = 'neon';
						accent = 'magenta';
					} else if (ACCENTS.some((t) => t.key === raw)) {
						accent = raw;
					}
				}
			} catch {
				/* битий JSON — дефолти */
			}
		}
		this.mode = mode;
		this.accent = accent;
		this.apply(false);
	}

	setMode(key: ModeKey): void {
		this.mode = key;
		this.apply(true);
		this.persist();
		scheduleServerPush();
	}

	setAccent(key: string): void {
		if (!ACCENTS.some((t) => t.key === key)) return;
		this.accent = key;
		this.apply(true);
		this.persist();
		scheduleServerPush();
	}

	/** увімк/вимк акцентну обвідку при наведенні */
	setHoverGlow(v: boolean): void {
		this.hoverGlow = v;
		this.applyHover();
		try {
			localStorage.setItem(LS_HOVER, v ? '1' : '0');
		} catch {
			/* ignore */
		}
		scheduleServerPush();
	}

	/** увімк/вимк анімований фон «Північне сяйво» */
	setAurora(v: boolean): void {
		this.aurora = v;
		try {
			localStorage.setItem(LS_AURORA, v ? '1' : '0');
		} catch {
			/* ignore */
		}
		scheduleServerPush();
	}

	/** вибір стилю появи елементів */
	setAnim(key: AnimKey): void {
		if (!ANIMS.some((x) => x.key === key)) return;
		this.anim = key;
		this.applyAnim();
		try {
			localStorage.setItem(LS_ANIM, key);
		} catch {
			/* ignore */
		}
		scheduleServerPush();
	}

	/** знімок для хмари (PUT /api/appearance) */
	snapshot(): {
		mode: ModeKey;
		accent: string;
		anim: AnimKey;
		hoverGlow: boolean;
		aurora: boolean;
	} {
		return {
			mode: this.mode,
			accent: this.accent,
			anim: this.anim,
			hoverGlow: this.hoverGlow,
			aurora: this.aurora
		};
	}

	/** Merge з сервера: сервер ПЕРЕВИЖАЄ (як у widgets.applyRemote).
	 *  Застосовує значення одразу + пише локальні сховища. */
	applyRemote(remote: unknown): void {
		if (!remote || typeof remote !== 'object') return;
		const r = remote as Record<string, unknown>;
		let touched = false;
		if (
			typeof r.mode === 'string' &&
			MODES.some((m) => m.key === r.mode) &&
			r.mode !== this.mode
		) {
			this.mode = r.mode as ModeKey;
			touched = true;
		}
		if (
			typeof r.accent === 'string' &&
			ACCENTS.some((t) => t.key === r.accent) &&
			r.accent !== this.accent
		) {
			this.accent = r.accent;
			touched = true;
		}
		if (
			typeof r.anim === 'string' &&
			ANIMS.some((a) => a.key === r.anim) &&
			r.anim !== this.anim
		) {
			this.anim = r.anim as AnimKey;
			try {
				localStorage.setItem(LS_ANIM, r.anim);
			} catch {
				/* ignore */
			}
			touched = true;
		}
		if (
			typeof r.hoverGlow === 'boolean' &&
			r.hoverGlow !== this.hoverGlow
		) {
			this.hoverGlow = r.hoverGlow;
			try {
				localStorage.setItem(LS_HOVER, r.hoverGlow ? '1' : '0');
			} catch {
				/* ignore */
			}
			touched = true;
		}
		if (typeof r.aurora === 'boolean' && r.aurora !== this.aurora) {
			this.aurora = r.aurora;
			try {
				localStorage.setItem(LS_AURORA, r.aurora ? '1' : '0');
			} catch {
				/* ignore */
			}
			touched = true;
		}
		if (!touched) return;
		this.applyHover();
		this.applyAnim();
		this.apply(true);
		this.persist();
	}

	/** Фонове підтягування з сервера (без локу UI). */
	async syncFromServer(): Promise<void> {
		try {
			const res = await api.appearanceGet();
			if (res?.pref) this.applyRemote(res.pref);
		} catch {
			/* офлайн — працюємо з локальним вибором */
		}
	}

	/** Одноразова синхронізація після логіна: сервер — «останнє слово». */
	async pullCloud(): Promise<void> {
		await this.syncFromServer();
	}

	private applyAnim(): void {
		if (typeof document === 'undefined') return;
		document.documentElement.setAttribute('data-anim', this.anim);
	}

	private applyHover(): void {
		if (typeof document === 'undefined') return;
		document.documentElement.classList.toggle('no-hover-glow', !this.hoverGlow);
	}

	private persist(): void {
		try {
			localStorage.setItem(
				LS_KEY,
				JSON.stringify({ mode: this.mode, accent: this.accent })
			);
		} catch {
			/* ignore */
		}
	}

	private apply(animate: boolean): void {
		if (typeof document === 'undefined') return;
		const m = this.curMode;
		const t = this.curAccent;
		const b = m.base;
		const r = document.documentElement.style;

		// акценти
		r.setProperty('--accent', t.accent);
		r.setProperty('--accent-strong', lighten(t.accent, 0.14));
		r.setProperty('--accent-soft', rgba(t.accent, 0.16));
		r.setProperty('--cyan', t.sec);
		r.setProperty('--aur-1', t.aur[0]);
		r.setProperty('--aur-2', t.aur[1]);
		r.setProperty('--aur-3', t.aur[2]);

		// база поверхонь
		for (const k of Object.keys(BASE_VARS) as (keyof typeof BASE_VARS)[]) {
			if (k === 'aurOp') r.setProperty(BASE_VARS.aurOp, String(b.aurOp));
			else r.setProperty(BASE_VARS[k], b[k] as string);
		}
		r.colorScheme = b.scheme;
		// перекриваємо інлайн-фон, виставлений pre-paint скриптом у app.html
		r.backgroundColor = b.bg;
		document.documentElement.dataset.scheme = b.scheme;

		// плоскі rgba-кольори поверхонь. try: помилка тут не має
		// вбивати решту змінних теми
		try {
			r.setProperty('--surface-a65', rgba(b.surface, 0.65));
			r.setProperty('--surface-a86', rgba(b.surface, 0.86));
			r.setProperty('--surface-a94', rgba(b.surface, 0.94));
			r.setProperty('--bg-a85', rgba(b.bg, 0.85));
		} catch (e) {
			console.error('[theme] flat surfaces failed:', e);
		}

		// чорнила чипів оцінок за режимом
		const inks = b.scheme === 'light' ? MK_INKS_LIGHT : MK_INKS_DARK;
		for (const k of Object.keys(inks)) r.setProperty(`--mk-${k}`, inks[k]);

		// PWA статус-бар під фон теми
		document
			.querySelector('meta[name="theme-color"]')
			?.setAttribute('content', b.bg);

		if (animate) {
			const el = document.documentElement;
			el.classList.add('theming');
			window.setTimeout(() => el.classList.remove('theming'), 650);
		}
	}
}

export const theme = new ThemeStore();
