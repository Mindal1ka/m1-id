/** Реєстр і стор віджетів Головної: склад, порядок, ширина (span).
 *
 *  Хмарні розкладки (cloud widgets): окрема розкладка на кожен клас
 *  пристрою (phone / tablet / desktop). У localStorage тримаємо ВСІ
 *  класи одночасно (при перезавантаженні рендеримо миттєво з кешу),
 *  а сервер підтягуємо в фоні і мержимо — якщо там є зміни, застосовуємо.
 *  Збереження: debounce-запит PUT /api/widgets/layouts усією картою.
 *
 *  Міграція зі старої версії (v1, один список): копіюємо його в усі
 *  класи, щоб ніхто не втратив свою поточну розкладку.
 */

import { api } from '$lib/api/client';
import type { DeviceClass } from '$lib/device.svelte';

export type WidgetKey =
	| 'stats'
	| 'deadlines'
	| 'lessons'
	| 'marks'
	| 'activity'
	| 'news'
	| 'board';

export interface WidgetCfg {
	key: WidgetKey;
	/** Ширина в колонках 12-колоночної сітки. */
	span: number;
	/** Явна висота картки в px (крок 8). Без неї — автоконтент. */
	h?: number;
}

/** Уся карта розкладок по класах пристроїв. */
export type AllLayouts = Record<DeviceClass, WidgetCfg[]>;

export interface WidgetDef {
	key: WidgetKey;
	label: string;
	desc: string;
	defSpan: number;
}

export const WIDGET_DEFS: WidgetDef[] = [
	{ key: 'stats', label: 'Показники', desc: 'Бали · домашка · баланси', defSpan: 12 },
	{ key: 'deadlines', label: 'Дедлайни', desc: 'Найближчі здачі', defSpan: 7 },
	{ key: 'lessons', label: 'Сьогодні', desc: 'Пари на поточний день', defSpan: 5 },
	{ key: 'marks', label: 'Оцінки', desc: 'Чіпи оцінок по місяцях', defSpan: 7 },
	{ key: 'activity', label: 'Нарахування', desc: 'Останні надходження', defSpan: 5 },
	{ key: 'news', label: 'Новини', desc: 'Стрічка новин', defSpan: 12 },
	{ key: 'board', label: 'Лідери', desc: 'Топ групи і моє місце', defSpan: 12 }
];
/** Розкладка «з коробки» — як буває історична Головна. */

/** Дефолт ПК-версії Головної (знято з живої розкладки автора, 2026-09):
 *  дедлайни / сьогодні / оцінки — три міні-картки в ряд, під ними
 *  нарахування та лідери. Нові юзери з ПК одразу бачать «дорослий» стан. */
export const DEFAULT_DESKTOP: WidgetCfg[] = [
	{ key: 'stats', span: 12 },
	{ key: 'deadlines', span: 4, h: 456 },
	{ key: 'lessons', span: 4, h: 456 },
	{ key: 'marks', span: 4, h: 456 },
	{ key: 'activity', span: 4 },
	{ key: 'news', span: 12 },
	{ key: 'board', span: 8 }
];

/** Розміри віджетів для пікера: назва людською + скільки колонок.
 *  Міні-бари в UI малюються з span (12 сегментів). */
export const WIDGET_SIZES: { span: number; label: string }[] = [
	{ span: 12, label: 'На всю ширину' },
	{ span: 11, label: '11/12' },
	{ span: 10, label: '10/12' },
	{ span: 9, label: '9/12' },
	{ span: 8, label: 'Широка' },
	{ span: 7, label: 'Класична' },
	{ span: 6, label: 'Середня' },
	{ span: 5, label: 'Вузька' },
	{ span: 4, label: 'Міні' }
];

/** Назва розміру для кнопки «Ширина». */
export function sizeName(span: number): string {
	return WIDGET_SIZES.find((s) => s.span === span)?.label ?? `${span}/12`;
}

export const PRESETS: Record<string, { name: string; list: WidgetCfg[] }> = {
	standard: {
		name: 'Стандарт',
		list: [
			{ key: 'stats', span: 12 },
			{ key: 'deadlines', span: 7 },
			{ key: 'lessons', span: 5 },
			{ key: 'marks', span: 7 },
			{ key: 'activity', span: 5 },
			{ key: 'news', span: 12 }
		]
	},
	marks: {
		name: 'Оцінки',
		list: [
			{ key: 'stats', span: 12 },
			{ key: 'marks', span: 12 },
			{ key: 'deadlines', span: 7 },
			{ key: 'lessons', span: 5 },
			{ key: 'board', span: 12 }
		]
	},
	minimal: {
		name: 'Мінімум',
		list: [
			{ key: 'deadlines', span: 7 },
			{ key: 'lessons', span: 5 },
			{ key: 'marks', span: 12 }
		]
	},
	all: {
		name: 'Усе',
		list: WIDGET_DEFS.map((d) => ({ key: d.key, span: d.defSpan }))
	}
};

const LS_KEY = 'm1id.homeWidgets.v2';
/** Стара версія — один список без класів (для міграції). */
const LS_KEY_V1 = 'm1id.homeWidgets.v1';

const KNOWN = new Set(WIDGET_DEFS.map((d) => d.key));

/** Міграція зі старого ключа: один список → усі класи. */
function legacyV1(): WidgetCfg[] | null {
	try {
		const raw = localStorage.getItem(LS_KEY_V1);
		if (!raw) return null;
		const arr = JSON.parse(raw) as WidgetCfg[];
		return Array.isArray(arr) && arr.length ? sanitizeList(arr) : null;
	} catch {
		return null;
	}
}

function sanitizeList(arr: unknown): WidgetCfg[] {
	if (!Array.isArray(arr)) return [];
	const clean = (arr as WidgetCfg[])
		.filter(
			(w) =>
				w &&
				KNOWN.has(w.key) &&
				typeof w.span === 'number' &&
				w.span >= 3 &&
				w.span <= 12
		)
		.map((w) => ({
			...w,
			h:
				typeof w.h === 'number' &&
				// minH «Показників» (stats) — 70: clamp 140 убивав
				// задум «вдвічі менша мінімальна висота»
				w.h >= 70 &&
				w.h <= 1000
					? Math.round(w.h / 8) * 8
					: undefined
		}));
	return clean;
}

function defaultFor(cls: DeviceClass): WidgetCfg[] {
	// телефон — вузькі одноколонкові віджети не мають сенсу: сітка
	// все одно складається в 1 колонку, тож беремо стандарт
	if (cls === 'desktop') return DEFAULT_DESKTOP.map((w) => ({ ...w }));
	const base = PRESETS.standard.list.map((w) => ({ ...w }));
	return base;
}

function loadAll(): AllLayouts {
	const def = (): WidgetCfg[] => defaultFor('phone');
	const map: AllLayouts = { phone: def(), tablet: def(), desktop: def() };
	try {
		const raw = localStorage.getItem(LS_KEY);
		if (raw) {
			const obj = JSON.parse(raw) as Partial<AllLayouts>;
			let any = false;
			for (const cls of ['phone', 'tablet', 'desktop'] as DeviceClass[]) {
				const clean = sanitizeList(obj?.[cls]);
				if (clean.length) {
					map[cls] = clean;
					any = true;
				}
			}
			// немає нічого в v2 → пробуємо міграцію зі старого v1
			if (!any) {
				const leg = legacyV1();
				if (leg) {
					map.phone = leg.map((w) => ({ ...w }));
					map.tablet = leg.map((w) => ({ ...w }));
					map.desktop = leg.map((w) => ({ ...w }));
				}
			}
		} else {
			const leg = legacyV1();
			if (leg) {
				map.phone = leg.map((w) => ({ ...w }));
				map.tablet = leg.map((w) => ({ ...w }));
				map.desktop = leg.map((w) => ({ ...w }));
			}
		}
	} catch {
		/* бите сховище → дефолти */
	}
	return map;
}

let serverTimer: ReturnType<typeof setTimeout> | null = null;

/** Debounce-відправка усієї карти розкладок на сервер. */
function scheduleServerPush(byClass: AllLayouts): void {
	if (serverTimer) clearTimeout(serverTimer);
	serverTimer = setTimeout(() => {
		api.widgetLayoutsPut(byClass).catch(() => {
			/* офлайн / 401 — локальна розкладка живе далі, спроба буде
			 при наступній зміні або наступному старті (merge з сервера) */
		});
	}, 1200);
}

class WidgetStore {
	/** Карта всіх класів — джерело правди. */
	byClass: AllLayouts = loadAll();

	/** Активний клас (перемикається при зміні пристрою). */
	cls = $state<DeviceClass>('desktop');

	/** Поточна розкладка = список активного класу. Присвоєння в
	 *  методах нижче завжди пише в byClass[cls]. */
	list = $state<WidgetCfg[]>([]);

	constructor() {
		this.list = this.byClass[this.cls];
	}

	/** Перемкнути клас пристрою (зміна viewport або вибір юзера). */
	/** Ініціалізація на старті: активний клас із device-детектора. */
	initFrom(cls: DeviceClass): void {
		this.cls = cls;
		this.list = this.byClass[cls];
	}

	switchTo(cls: DeviceClass): void {
		if (this.cls === cls) return;
		this.cls = cls;
		this.list = this.byClass[cls];
	}

	private save(): void {
		this.byClass[this.cls] = this.list;
		try {
			localStorage.setItem(LS_KEY, JSON.stringify(this.byClass));
		} catch {
			/* приватний режим — тримаємо лише в пам'яті */
		}
		scheduleServerPush(this.byClass);
	}

	/** Merge з сервера: по класах, яких немає локально (юзер налаштував
	 *  розкладку на іншому пристрої) — застосовуємо повністю; по класах,
	 *  які є — сервер ПЕРЕВИЖАЄ (захист від старого кешу). Після
	 *  застосування поточний клас перечитується. */
	applyRemote(remote: unknown): void {
		if (!remote || typeof remote !== 'object') return;
		let touched = false;
		for (const cls of ['phone', 'tablet', 'desktop'] as DeviceClass[]) {
			const clean = sanitizeList((remote as AllLayouts)[cls]);
			if (clean.length) {
				this.byClass[cls] = clean;
				touched = true;
			}
		}
		if (!touched) return;
		try {
			localStorage.setItem(LS_KEY, JSON.stringify(this.byClass));
		} catch {
			/* ignore */
		}
		this.list = this.byClass[this.cls];
	}

	/** Фонове підтягування з сервера (без локу UI). */
	async syncFromServer(): Promise<void> {
		try {
			const res = await api.widgetLayoutsGet();
			if (res?.layouts) this.applyRemote(res.layouts);
		} catch {
			/* офлайн — працюємо з локальним кешем */
		}
	}

	/** Один-разова синхронізація після логіна: сервер спершу, потім
	 *  локальний кеш гарантовано відповідає хмарі (або навпаки, якщо
	 *  юзер щойно щось змінив офлайн — його локальна карта піде PUT-ом
	 *  при наступній правці; тут беремо сервер як «останнє слово»). */
	async pullCloud(): Promise<void> {
		await this.syncFromServer();
	}

	isOn(key: WidgetKey): boolean {
		return this.list.some((w) => w.key === key);
	}

	toggle(key: WidgetKey): void {
		if (this.isOn(key)) {
			this.list = this.list.filter((w) => w.key !== key);
		} else {
			const def = WIDGET_DEFS.find((d) => d.key === key);
			this.list = [
				...this.list,
				{ key, span: def?.defSpan ?? 12 }
			];
		}
		this.save();
	}

	remove(key: WidgetKey): void {
		this.list = this.list.filter((w) => w.key !== key);
		this.save();
	}

	/** Пересунути віджет на одну позицію (-1 ліворуч / +1 праворуч). */
	move(key: WidgetKey, dir: -1 | 1): void {
		const i = this.list.findIndex((w) => w.key === key);
		const j = i + dir;
		if (i < 0 || j < 0 || j >= this.list.length) return;
		const next = [...this.list];
		[next[i], next[j]] = [next[j], next[i]];
		this.list = next;
		this.save();
	}

	/** Вільне переміщення: вставити віджет так, щоб перед ним було
	 *  beforeCount інших. Живий виклик із commit=false під час драга —
	 *  порядок фіксує commitResize() на drop. */
	moveTo(key: WidgetKey, beforeCount: number, commit = true): void {
		const i = this.list.findIndex((w) => w.key === key);
		if (i < 0) return;
		const others = this.list.filter((w) => w.key !== key);
		const k = Math.max(0, Math.min(others.length, Math.round(beforeCount)));
		if (k === i) return;
		const next = [...others.slice(0, k), this.list[i], ...others.slice(k)];
		this.list = next;
		if (commit) this.save();
	}

	/** Живе перетягування ширини пари (роздільник між боксами) без
	 *  запису у localStorage; фіксація — commitResize(). */
	resizePair(aKey: WidgetKey, aSpan: number,
			bKey: WidgetKey | null, bSpan: number): void {
		const i = this.list.findIndex((x) => x.key === aKey);
		if (i < 0) return;
		const next = [...this.list];
		next[i] = { ...next[i], span: Math.max(3, Math.min(12, aSpan)) };
		if (bKey) {
			const j = this.list.findIndex((x) => x.key === bKey);
			if (j >= 0)
				next[j] = { ...next[j], span: Math.max(3, Math.min(12, bSpan)) };
		}
		this.list = next;
	}

	commitResize(): void {
		this.save();
	}

	/** Ширина безпосередньо (з візуального пікера), clamp 3..12. */
	setSpan(key: WidgetKey, span: number, commit = true): void {
		const i = this.list.findIndex((x) => x.key === key);
		if (i < 0) return;
		const v = Math.max(3, Math.min(12, Math.round(span)));
		const next = [...this.list];
		next[i] = { ...next[i], span: v };
		this.list = next;
		if (commit) this.save();
	}

	/** Висота картки (нижня ручка): явні px кроком 8, контент
	 *  скролиться всередині. minH — мінімум ПО ВІДЖЕТУ: «Показники»
	 *  мають minH 70 (удвічі менший), інакше clamp 140 убивав задум
	 *  «вдвічі менша мінімальна висота» — 70 клампилося до 140. */
	setH(key: WidgetKey, px: number, commit = true, minH = 140): void {
		const i = this.list.findIndex((w) => w.key === key);
		if (i < 0) return;
		const v = Math.max(minH, Math.min(1000, Math.round(px / 8) * 8));
		const next = [...this.list];
		next[i] = { ...next[i], h: v };
		this.list = next;
		if (commit) this.save();
	}

	preset(name: keyof typeof PRESETS): void {
		const p = PRESETS[name];
		if (!p) return;
		this.list = p.list.map((w) => ({ ...w }));
		this.save();
	}
}

export const widgets = new WidgetStore();