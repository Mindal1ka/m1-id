/** Кеш представлень на акаунт: пам'ять + localStorage (повний офлайн)
 *  + freshness (5 хвилин) для банера «дані з кешу — оновлюємо». */
import {
	api,
	type ActivityItem,
	type Dashboard,
	type HomeworkView,
	type LeaderboardView,
	type MarksView,
	type NewsView,
	type ScheduleView,
	type ShopView,
	type SnapshotMeta
} from '$lib/api/client';

export const FRESH_MS = 5 * 60_000; // 5 хвилин
const LS_PREFIX = 'm1id.cache.';
/** Ключі пер-акаунтного кешу, які містять ДАНІ КОРИСТУВАЧА (H7):
 *  видаляються при logout, щоб інший користувач на тому ж пристрої
 *  не стартував на кеші попереднього. */
const PER_ACCOUNT_KEYS = ['m1id.accounts', 'm1id.lastAccount'];
/** Префікс клієнтського кешу меню їдальні (api.nutritionMenu). */
const FS_MENU_PREFIX = 'fs_menu_';

/** H7: очистити ВЕСЬ пер-акаунтний кеш з localStorage (m1id.cache.*,
 *  fs_menu_*, m1id.accounts, m1id.lastAccount) та in-memory слоти стора.
 *  Викликається з logout() у +layout.svelte. */
export function clearPerAccountCache(): void {
	try {
		const doomed: string[] = [];
		for (let i = 0; i < localStorage.length; i++) {
			const k = localStorage.key(i);
			if (
				k &&
				(k.startsWith(LS_PREFIX) || k.startsWith(FS_MENU_PREFIX) || PER_ACCOUNT_KEYS.includes(k))
			) {
				doomed.push(k);
			}
		}
		for (const k of doomed) localStorage.removeItem(k);
	} catch {
		/* ignore */
	}
	store.clearAllSlots();
}

export interface AccountCache {
	dash?: Dashboard;
	hw?: HomeworkView;
	sched: Record<string, ScheduleView>;
	marks: Record<string, MarksView>;
	snapshots?: SnapshotMeta[];
	news?: NewsView;
	shop?: ShopView;
	/** Лідерборд для віджета на Головній (без «Оновити» — авто кожні 5 хв). */
	leaderboard?: LeaderboardView;
	activity?: {
		items: ActivityItem[];
		page: number;
		has_more: boolean;
		loading: boolean;
	};
	prefetched: boolean;
	ts: {
		dash?: number;
		hw?: number;
		sched: Record<string, number>;
		marks: Record<string, number>;
		news?: number;
		shop?: number;
		board?: number;
	};
}

export function weekMonday(d = new Date()): string {
	const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
	const dow = x.getDay(); // 0=Нд
	x.setDate(x.getDate() - dow + (dow === 0 ? -6 : 1));
	return toIsoLocal(x);
}

/** ISO-дата з ЛОКАЛЬНИХ компонентів: toISOString() дає UTC-дату й
 *  у північ–03:00 при UTC+3 з'їжджає на день назад (криві ключі кешу). */
export function toIsoLocal(d: Date): string {
	const p = (n: number) => String(n).padStart(2, '0');
	return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** Поточний місяць YYYY-MM за локальним часом. */
export function currentMonthKey(d = new Date()): string {
	return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function readLS(accountId: number): Partial<AccountCache> | null {
	try {
		const raw = localStorage.getItem(LS_PREFIX + accountId);
		return raw ? (JSON.parse(raw) as Partial<AccountCache>) : null;
	} catch {
		return null;
	}
}

	function writeLS(accountId: number, slot: AccountCache): void {
		try {
			localStorage.setItem(
				LS_PREFIX + accountId,
				JSON.stringify({
					dash: slot.dash,
					hw: slot.hw,
					sched: slot.sched,
					marks: slot.marks,
					snapshots: slot.snapshots,
					news: slot.news,
					shop: slot.shop,
					leaderboard: slot.leaderboard,
					activity: slot.activity,
					ts: slot.ts
				})
			);
		} catch {
			/* quota/приватний режим — кеш у пам'яті все одно працює */
		}
	}

class AppStore {
	private map = $state<Record<number, AccountCache>>({});
	/** F6: in-flight дедуплікація — паралельні виклики (віджет +
	 *  вкладка + сторож) ділять ОДИН запит на ключ. */
	private inflight = new Map<string, Promise<unknown>>();
	/** Debounce записів у localStorage (LOW): серія тиків → один write.
	 *  Ключ — accountId, значення — таймер відкладеного writeLS. */
	private persistTimers = new Map<number, ReturnType<typeof setTimeout>>();

	/** F6: дедуплікація однакових запитів за ключем. */
	private dedupe<T>(key: string, run: () => Promise<T>): Promise<T> {
		const existing = this.inflight.get(key);
		if (existing) return existing as Promise<T>;
		const p = run().finally(() => this.inflight.delete(key));
		this.inflight.set(key, p);
		return p;
	}

	/** H7: повністю очистити in-memory слоти (при logout). */
	clearAllSlots(): void {
		this.map = {};
		for (const [, t] of this.persistTimers) clearTimeout(t);
		this.persistTimers.clear();
		for (const [, p] of this.inflight) {
			p.catch(() => {}); // не залишаємо unhandledrejection
		}
		this.inflight.clear();
	}

	/** Отримати/створити слот акаунта. */
	private slot(accountId: number): AccountCache {
		const existing = this.map[accountId];
		if (existing) return existing;
		const fresh: AccountCache = {
			sched: {},
			marks: {},
			prefetched: false,
			ts: { sched: {}, marks: {} }
		};
		this.map[accountId] = fresh;
		return fresh;
	}

	/** Відновити кеш цього акаунта з localStorage. true — якщо щось є. */
	restore(accountId: number): boolean {
		const raw = readLS(accountId);
		if (!raw) return false;
		const slot = this.slot(accountId);
		if (raw.dash) slot.dash = raw.dash;
		if (raw.hw) slot.hw = raw.hw;
		if (raw.sched) slot.sched = raw.sched;
		if (raw.marks) slot.marks = raw.marks;
		if (raw.snapshots) slot.snapshots = raw.snapshots;
		if (raw.news) slot.news = raw.news;
		if (raw.shop) slot.shop = raw.shop;
		if (raw.activity)
			slot.activity = { ...raw.activity, loading: false };
		slot.ts = {
			dash: raw.ts?.dash,
			hw: raw.ts?.hw,
			sched: raw.ts?.sched ?? {},
			marks: raw.ts?.marks ?? {},
			// раніше втрачались: після перезавантаження freshness новин/
			// магазину/лідерборду скидалася і летіли зайві запити
			news: raw.ts?.news,
			shop: raw.ts?.shop,
			board: raw.ts?.board
		};
		return Boolean(slot.dash);
	}

	/** Debounced persist (LOW): writeLS максимум раз на 500 мс на акаунт —
	 *  серія швидких оновлень не гоняє JSON.stringify у localStorage. */
	private persist(accountId: number): void {
		const existing = this.persistTimers.get(accountId);
		if (existing) clearTimeout(existing);
		this.persistTimers.set(
			accountId,
			setTimeout(() => {
				this.persistTimers.delete(accountId);
				writeLS(accountId, this.slot(accountId));
			}, 500)
		);
	}

	/** Чи головні дані свіжі (< 5 хв). */
	isFresh(accountId: number): boolean {
		const t = this.map[accountId]?.ts.dash;
		return t !== undefined && Date.now() - t < FRESH_MS;
	}

	dash(accountId: number): Dashboard | undefined {
		return this.map[accountId]?.dash;
	}

	/** Слоти для авто-тиків +page (без зайвих запитів — з кешу стора). */
	marksCache(accountId: number): MarksView | undefined {
		return this.map[accountId]?.marks['year'];
	}

	newsCache(accountId: number): NewsView | undefined {
		return this.map[accountId]?.news;
	}

	leaderboardCache(accountId: number): LeaderboardView | undefined {
		return this.map[accountId]?.leaderboard;
	}
	/** Слоти для авто-тиків +page (без зайвих запитів — з кешу стора):
	 *  домашка/розклад/магазин для синку активної вкладки після
	 *  фонового revalidateAll (раніше вкладка показувала старе). */
	hwCache(accountId: number): HomeworkView | undefined {
		return this.map[accountId]?.hw;
	}

	schedCache(accountId: number, key: string): ScheduleView | undefined {
		return this.map[accountId]?.sched[key];
	}

	shopCache(accountId: number): ShopView | undefined {
		return this.map[accountId]?.shop;
	}

	async loadDashboard(accountId: number, force = false): Promise<Dashboard> {
		return this.dedupe(`dash:${accountId}:${force}`, async () => {
			const slot = this.slot(accountId);
			if (!force && slot.dash) return slot.dash;
			const d = await api.dashboard(accountId, force);
			slot.dash = d;
			slot.ts.dash = Date.now();
			this.persist(accountId);
			this.prefetchRest(accountId);
			return d;
		});
	}

	/** Реальне оновлення: ігнорує КЛІЄНТСЬКИЙ кеш, але поважає TTL бекенда
	 *  (використовується фоновим stale-while-revalidate). */
	async revalidateDashboard(accountId: number): Promise<Dashboard> {
		const slot = this.slot(accountId);
		const d = await api.dashboard(accountId, false);
		slot.dash = d;
		slot.ts.dash = Date.now();
		this.persist(accountId);
		return d;
	}

	/** Авто-рефреш (кожні 5 хв): тихо перечитує ВСІ основні розділи,
	 *  а не тільки дашборд — лідерборд/новини/дедлайни/магазин не можуть
	 *  відставати на години, доки вкладка відкрита. Кожен запит м'яко
	 *  валиться в .catch — помилка одного розділу не ламає решту.
	 *  Бекенд сам вирішує по TTL снапшотів, що тягнути з mapi.
	 *  → { ok, dashOk }: ok = ВСІ розділи оновились; dashOk = головні
	 *  дані (дашборд) свіжі. Раніше будь-який збій (напр. новини)
	 *  кидав partial_revalidate_failure → фронт вічно показував
	 *  баннер «оновлюємо» і тригерив force-перезачитування вкладок
	 *  кожні 30с, хоча дашборд був ОК. */
	async revalidateAll(accountId: number): Promise<{ ok: boolean; dashOk: boolean }> {
		// F6/F7: подвійний виклик (сторож + 5хв таймер + «Оновити») →
		// один спільний цикл оновлення, а не два паралельні.
		return this.dedupe(`reval:${accountId}`, async () => {
		const slot = this.slot(accountId);
		let dashOk = false;
		const jobs: Promise<void>[] = [
			api.dashboard(accountId, false)
				.then((d) => {
					slot.dash = d;
					slot.ts.dash = Date.now();
					dashOk = true;
				}),
			api.homework(accountId, false).then((v) => {
				slot.hw = v;
				slot.ts.hw = Date.now();
			}),
			api.schedule(accountId, 'week').then((v) => {
				const key = `week:${weekMonday()}`;
				slot.sched[key] = v;
				slot.ts.sched[key] = Date.now();
			}),
			api.marks(accountId, 'year', false).then((v) => {
				slot.marks['year'] = v;
				slot.ts.marks['year'] = Date.now();
			}),
			api.news(accountId, false).then((v) => {
				slot.news = v;
				slot.ts.news = Date.now();
			}),
			api.leaderboard(accountId, false).then((v) => {
				slot.leaderboard = v;
				slot.ts.board = Date.now();
			}),
			// магазин теж живе у віджетах/вкладці — без нього «неповне
			// оновлення»: баланси купленого не сходились із каталогом
			api.shop(accountId, false).then((v) => {
				slot.shop = v;
				slot.ts.shop = Date.now();
			}),
			// «Останні нарахування»: раніше стрічка бралась один раз і жила
			// в кеші вічно (в т.ч. у localStorage) — нові нарахування
			// з'являлись лише після ручного «Оновити»
			this.activityRefresh(accountId)
		];
		const out = await Promise.allSettled(jobs);
		this.persist(accountId);
		const ok = out.every((r) => r.status === 'fulfilled');
		return { ok, dashOk };
		});
	}

	private prefetchRest(accountId: number): void {
		const slot = this.slot(accountId);
		if (slot.prefetched) return;
		slot.prefetched = true;

		api.homework(accountId)
			.then((v) => {
				slot.hw = v;
				slot.ts.hw = Date.now();
				this.persist(accountId);
			})
			.catch(() => {});
		api.schedule(accountId, 'week')
			.then((v) => {
				slot.sched[`week:${weekMonday()}`] = v;
				slot.ts.sched[`week:${weekMonday()}`] = Date.now();
				this.persist(accountId);
			})
			.catch(() => {});
		api.marks(accountId, 'year')
			.then((v) => {
				slot.marks['year'] = v;
				slot.ts.marks['year'] = Date.now();
				this.persist(accountId);
			})
			.catch(() => {});
		this.activityFirst(accountId).catch(() => {});
	}

	async homework(accountId: number, force = false): Promise<HomeworkView> {
		return this.dedupe(`hw:${accountId}:${force}`, async () => {
			const slot = this.slot(accountId);
			if (force || !slot.hw) {
				slot.hw = await api.homework(accountId, force);
				slot.ts.hw = Date.now();
				this.persist(accountId);
			}
			return slot.hw!;
		});
	}

	async schedule(
		accountId: number,
		kind: 'week' | 'month',
		date?: string,
		force = false
	): Promise<ScheduleView> {
		const key =
			kind === 'week'
				? `week:${date ?? weekMonday()}`
				: `month:${date ?? currentMonthKey()}`;
		return this.dedupe(`sched:${accountId}:${key}:${force}`, async () => {
			const slot = this.slot(accountId);
			if (force || !slot.sched[key]) {
				slot.sched[key] = await api.schedule(accountId, kind, date, force);
				slot.ts.sched[key] = Date.now();
				this.persist(accountId);
			}
			return slot.sched[key]!;
		});
	}

	async marks(accountId: number, period: 'month' | 'year', force = false): Promise<MarksView> {
		return this.dedupe(`marks:${accountId}:${period}:${force}`, async () => {
			const slot = this.slot(accountId);
			if (force || !slot.marks[period]) {
				slot.marks[period] = await api.marks(accountId, period, force);
				slot.ts.marks[period] = Date.now();
				this.persist(accountId);
			}
			return slot.marks[period]!;
		});
	}

	/** Новини: стрічка для Головної й модалки. */
	async news(accountId: number, force = false): Promise<NewsView> {
		return this.dedupe(`news:${accountId}:${force}`, async () => {
			const slot = this.slot(accountId);
			if (force || !slot.news) {
				slot.news = await api.news(accountId, force);
				slot.ts.news = Date.now();
				this.persist(accountId);
			}
			return slot.news!;
		});
	}

	/** Лідерборд (віджет Головної + вкладка «Лідери»). Раніше методу
	 *  не було: force-оновлення тягнуло лідерборд лише побічно через
	 *  revalidateAll, а UI не отримував свіжі дані одразу. */
	async leaderboard(accountId: number, force = false): Promise<LeaderboardView> {
		return this.dedupe(`board:${accountId}:${force}`, async () => {
			const slot = this.slot(accountId);
			if (force || !slot.leaderboard) {
				slot.leaderboard = await api.leaderboard(accountId, force);
				slot.ts.board = Date.now();
				this.persist(accountId);
			}
			return slot.leaderboard!;
		});
	}

	/** Магазин: каталог + замовлення. */
	async shop(accountId: number, force = false): Promise<ShopView> {
		return this.dedupe(`shop:${accountId}:${force}`, async () => {
			const slot = this.slot(accountId);
			if (force || !slot.shop) {
				slot.shop = await api.shop(accountId, force);
				slot.ts.shop = Date.now();
				this.persist(accountId);
			}
			return slot.shop!;
		});
	}

	/** Після покупки/скасування: свіжі замовлення + баланс. */
	async shopRefresh(accountId: number): Promise<ShopView> {
		const slot = this.slot(accountId);
		const [shopV, dashV] = await Promise.all([
			api.shop(accountId, true),
			api.dashboard(accountId, true)
		]);
		slot.shop = shopV;
		slot.dash = dashV;
		slot.ts.shop = Date.now();
		slot.ts.dash = Date.now();
		this.persist(accountId);
		return shopV;
	}

	/** Скинути кеші розділів (після «Оновити»): hw/sched/marks/news/shop.
	 *  dash НЕ чіпаємо — екран не блимає, його оновлює refresh() з force.
	 *  Раніше store-кеш (пам'ять + localStorage) переживав «Оновити»
	 *  нескінченно: LeaderTab/ShopTab/PaymentsTab/ContactsTab показували
	 *  дані тижневої давнини навіть після натискання. */
	invalidate(accountId: number): void {
		const slot = this.map[accountId];
		if (!slot) return;
		slot.hw = undefined;
		slot.news = undefined;
		slot.shop = undefined;
		slot.sched = {};
		slot.marks = {};
		slot.ts.hw = undefined;
		slot.ts.news = undefined;
		slot.ts.shop = undefined;
		slot.ts.sched = {};
		slot.ts.marks = {};
		this.persist(accountId);
	}

	async snapshots(accountId: number): Promise<SnapshotMeta[]> {
		const slot = this.slot(accountId);
		if (!slot.snapshots) slot.snapshots = await api.snapshots(accountId);
		return slot.snapshots;
	}

	activity(accountId: number) {
		return this.map[accountId]?.activity;
	}

	async activityFirst(accountId: number): Promise<NonNullable<AccountCache['activity']>> {
		const slot = this.slot(accountId);
		if (slot.activity) return slot.activity;
		const p = await api.activity(accountId, 1);
		slot.activity = {
			items: p.items,
			page: p.page,
			has_more: p.has_more,
			loading: false
		};
		this.persist(accountId);
		return slot.activity;
	}

	/** Фонове оновлення стрічки: свіжа 1-ша сторінка зливається з уже
	 *  завантаженими (нові зверху, без дублів за id); глибші сторінки,
	 *  які юзер підгрузив скролом, не чіпаємо. Немає кешу — як activityFirst. */
	async activityRefresh(accountId: number): Promise<void> {
		const slot = this.slot(accountId);
		const act = slot.activity;
		if (!act) {
			await this.activityFirst(accountId);
			return;
		}
		const p = await api.activity(accountId, 1);
		const fresh = new Set(p.items.map((i) => i.id));
		const rest = act.items.filter((i) => !fresh.has(i.id));
		act.items = [...p.items, ...rest];
		// ще не гортали далі 1-ї сторінки → has_more бере свіжа відповідь
		if (act.page <= 1) act.has_more = p.has_more;
		this.persist(accountId);
	}

	async activityNext(accountId: number): Promise<void> {
		const act = this.map[accountId]?.activity;
		if (!act?.has_more || act.loading) return;
		act.loading = true;
		try {
			const p = await api.activity(accountId, act.page + 1);
			const seen = new Set(act.items.map((i) => i.id));
			act.items.push(...p.items.filter((i) => !seen.has(i.id)));
			act.page = p.page;
			act.has_more = p.has_more;
			this.persist(accountId);
		} finally {
			act.loading = false;
		}
	}

	/** Скинути кеш активності (наступний activityFirst піде в мережу). */
	activityReset(accountId: number): void {
		const slot = this.map[accountId];
		if (slot) slot.activity = undefined;
	}

	async snapshotPayload(accountId: number, section: string): Promise<unknown> {
		return api.snapshot(accountId, section);
	}

	invalidateAll(accountId: number): void {
		delete this.map[accountId];
		try {
			localStorage.removeItem(LS_PREFIX + accountId);
		} catch {
			/* ignore */
		}
	}
}

export const store = new AppStore();
