<script lang="ts">
	import { flushSync, untrack } from 'svelte';
	import { enterContent, replayEnter, motionOK, ease, canHover, smoothWheel, type VTDir } from '$lib/motion';
	import { replay } from '$lib/motion/replay.svelte';
	import { hoverCard } from '$lib/app/hovercards.svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { pushUrl, replaceUrl, queryParam } from '$lib/url-state';
	import {
		api,
		ApiError,
		type AccountOut,
		type Dashboard,
		type HomeworkView,
		type HwItem,
		type MarksView,
		type LeaderboardView,
		type NewsView,
		type ScheduleView,
		type ShopView,
		type SnapshotMeta,
		type SyncState
	} from '$lib/api/client';
	import { auth } from '$lib/stores/auth.svelte';
	import { store, toIsoLocal, weekMonday, currentMonthKey } from '$lib/stores/appStore.svelte';
	import { MONTHS_UK } from '$lib/sections';
	import { mondayOf, type SchedLesson, type Tab } from '$lib/app/helpers';
	import { device } from '$lib/device.svelte';
	import { openSyncWs } from '$lib/api/sync_ws';
	import { widgets } from '$lib/widgets.svelte';
	import { fx } from '$lib/fx.svelte';
	import { theme } from '$lib/theme.svelte';
	import { dev } from '$lib/devmode.svelte';
	import { friendlyError, isNetworkError } from '$lib/errors';
	// каркас і вигляди вкладок (вся логіка завантаження лишається тут)
	import AppBoot from '$lib/components/app/AppBoot.svelte';
	import AppSidebar from '$lib/components/app/AppSidebar.svelte';
	import AppTopbar from '$lib/components/app/AppTopbar.svelte';
	import AppBottomNav from '$lib/components/app/AppBottomNav.svelte';
	import OtherMenu from '$lib/components/app/OtherMenu.svelte';
	import ProfileMenu from '$lib/components/app/ProfileMenu.svelte';
	import HoverCards from '$lib/components/app/HoverCards.svelte';
	import HomeView from '$lib/components/app/HomeView.svelte';
	import ScheduleScreen from '$lib/components/app/ScheduleView.svelte';
	import HomeworkScreen from '$lib/components/app/HomeworkView.svelte';
	import MarksScreen from '$lib/components/app/MarksView.svelte';
	import ActivityView from '$lib/components/app/ActivityView.svelte';
	import DataView from '$lib/components/app/DataView.svelte';
	import LazyComponent from '$lib/components/app/LazyComponent.svelte';
	import StaleBanner from '$lib/components/StaleBanner.svelte';
	import ServerStatus from '$lib/components/ServerStatus.svelte';
	import { Button, EmptyState, ErrorState } from '$lib/ui';
	import {
		BookOpen,
		CalendarDays,
		Database,
		Gift,
		GraduationCap,
		Home,
		LogIn,
		NotebookPen,
		Phone,
		Puzzle,
		RotateCw,
		Send,
		ShoppingBag,
		Sparkles,
		Star,
		TrendingUp,
		Trophy,
		Utensils,
		Wallet
	} from '@lucide/svelte';


	const TABS: { key: Tab; icon: typeof Home; label: string }[] = [
		{ key: 'home', icon: Home, label: 'Головна' },
		{ key: 'schedule', icon: CalendarDays, label: 'Розклад' },
		{ key: 'homework', icon: BookOpen, label: 'Домашка' },
		{ key: 'marks', icon: GraduationCap, label: 'Оцінки' },
		{ key: 'shop', icon: ShoppingBag, label: 'Магазин' },
		{ key: 'nutrition', icon: Utensils, label: 'Харчування' },
		{ key: 'payments', icon: Wallet, label: 'Платежі' },
		// КЛУБИ ВИМКНЕНІ (бік: CLUBS_ENABLED=False у sync_engine.py).
		// Повернути: розкоментувати рядок нижче і поставити CLUBS_ENABLED=True.
		// { key: 'clubs', icon: Dumbbell, label: 'Клуби' },
		{ key: 'contacts', icon: Phone, label: 'Контакти' },
		{ key: 'notes', icon: NotebookPen, label: 'Нотатки' },
		{ key: 'board', icon: Trophy, label: 'Лідери' },
		{ key: 'awards', icon: Gift, label: 'Нагороди' },
		{ key: 'progress', icon: TrendingUp, label: 'Прогрес' },
		{ key: 'activity', icon: Sparkles, label: 'Нарахування' },
		{ key: 'telegram', icon: Send, label: 'Telegram' },
		{ key: 'plugins', icon: Puzzle, label: 'Плагіни' },
		// «Додаткові» - сокет + Автооцінювання (і майбутні фічі)
		{ key: 'extras', icon: Star, label: 'Додаткові' },
		// «Дані» - технічна вкладка: видима лише в режимі розробника
		// (налаштування → Режим розробника).
		{ key: 'data', icon: Database, label: 'Дані' }
	];

	let accounts = $state<AccountOut[]>([]);
	let activeId = $state<number | null>(null);
	let dash = $state.raw<Dashboard | null>(null);
	let hw = $state.raw<HomeworkView | null>(null);
	let sched = $state.raw<ScheduleView | null>(null);
	let marksData = $state.raw<MarksView | null>(null);
	let homeMarks = $state.raw<MarksView | null>(null);
	let newsData = $state.raw<NewsView | null>(null);
	/** Хмарні розкладки віджетів: зміна класу пристрою в рантаймі →
	 * тихо підвантажуємо версію нового класу. */
	let layoutClsSeen = 0;
	let newsOpen = $state(false);
	let shopData = $state.raw<ShopView | null>(null);
	let boardMini = $state.raw<LeaderboardView | null>(null);
	let editHome = $state(false);
	let contentEl = $state<HTMLElement | null>(null);
	/** Вміст прокручено > 8px: топбар отримує тінь і стискає заголовок. */
	let contentScrolled = $state(false);

	/** Cooldown «зараз скролимо»: від останньої scroll-події тримаємо
	 *  прапорець ще 160мс — на цей час сітка плиток отримує клас
	 *  .scrolling і клік/hover по картках фізично не проходить. */
	let scrolling = $state(false);
	let scrollT = 0;

	function markScrolling(): void {
		scrolling = true;
		clearTimeout(scrollT);
		scrollT = window.setTimeout(() => (scrolling = false), 160);
	}
	/** Віджет «Лідери»: власні перемикачі (як у MyStat). Періоди
	 *  динамічні з view.scopes: школа - місяць/семестр/рік, академія -
	 *  місяць/за весь час, невідома гілка - англійські підписи. */
	let bScope = $state<string>('');
	let bPeriod = $state<string>('');
	let snapshots = $state<SnapshotMeta[]>([]);
	let sectionPayload = $state<unknown>(null);
	let openSection = $state<string | null>(null);

	let tab = $state<Tab>('home');
	let homeKept = $state(false);
	let homeEl = $state<HTMLElement | null>(null);
	$effect(() => { if (tab === 'home') homeKept = true; });
	let busyTab = $state<string>('');

	// URL ↔ стан: «Назад/Вперед» у браузері відкриває/закриває вкладки
	// та модалку домашки. БЕЗ перезавантаження (нативний popstate).
	const VALID_TABS = new Set<string>(TABS.map((x) => x.key));
	$effect(() => {
		const onPop = (): void => {
			const t = queryParam('tab');
			if (t && VALID_TABS.has(t) && t !== tab) {
				// popstate: URL уже правильний — лише стан, без push
				void openTab(t as Tab, false, false);
				return; // openTab сам синхронізує ?hw=
			}
			if (!t && tab !== 'home') {
				void openTab('home', false, false);
				return;
			}
			const hwParam = Number(queryParam('hw')) || null;
			if (detailsOpen && detailsHw && detailsHw.id !== hwParam) {
				// назад із модалки → закриваємо, історію не чіпаємо
				detailsOpen = false;
			} else if (!detailsOpen && hwParam && hw?.items?.length) {
				const item = hw.items.find((x) => Number(x.id) === hwParam);
				if (item) {
					detailsHw = item;
					detailsOpen = true; // вперед → знову відкриваємо
				}
			}
		};
		window.addEventListener('popstate', onPop);
		return () => window.removeEventListener('popstate', onPop);
	});
	let err = $state('');
	let needRelogin = $state(false);
	/** Форма повторного входу в MyStat інлайн на сторінці бута (не
	 *  відправляємо на /accounts): новий .token_key після рестарту
	 *  робить збережені токени нечитабельними → needs_relogin. */
	let relogLogin = $state('');
	let relogPass = $state('');
	let relogBusy = $state(false);
	let relogErr = $state('');

	// Автопідстановка логіна: бекенд зберігає mystat_login акаунта —
	// користувач вводить лише пароль (логін можна підправити руками).
	$effect(() => {
		if (!needRelogin || relogLogin) return;
		const acc = accounts.find((a) => a.id === activeId);
		relogLogin = acc?.login ?? '';
	});
	let booting = $state(true);
	let bootNote = $state('Ми готуємо все для вас…');
	/** Прогрес бут-лоадера (0..1) з syncStatus бекенда: реальні
	 *  done/total кроків синхронізації. null → брусок ховаємо
	 *  (дані з снапшотів, синхронізувати нічого). */
	let bootProgress = $state<number | null>(null);
	/** Живий стан синку сервера (пігулка внизу): опитуємо syncStatus
	 *  ПОСТІЙНО, поки відкритий застосунок — не лише під час бута.
	 *  Тож юзер завжди бачить, що саме робить сервер (снапшоти/синк). */
	let syncState = $state<SyncState | null>(null);
	let started = $state(false);
	let stale = $state(false);
	let refreshing = $state(false);
	/** F1: чесний guard — лічильник активних refresh-циклів (refresh +
	 * refreshSilent + сторож). Прапорець скидається лише коли ЦЕЙ цикл
	 * останній, а не «чийсь» finally раніше часу. */
	let refreshDepth = 0;
	/** Акаунт, для якого стартував останній refresh-цикл: refreshSilent
	 *  пропускається лише коли вже летить оновлення ТОГО Ж акаунта. */
	let refreshAccId: number | null = null;
	/** Лічильник поколінь refreshSilent: результат застарілого циклу
	 *  (після switchAccount, навіть A→B→A) ігноруємо. */
	let silentGen = 0;
	function beginRefresh(accId: number | null = activeId): void {
		refreshDepth++;
		refreshAccId = accId;
		refreshing = true;
	}
	function endRefresh(): void {
		refreshDepth = Math.max(0, refreshDepth - 1);
		if (refreshDepth === 0) refreshing = false;
	}
	let settingsOpen = $state(false);
	let sessionsOpen = $state(false);
	let m1AllOpen = $state(false);
	let bannerClosed = $state(false);
	let profileOpen = $state(false);
	let profileEdit = $state(false);
	let menuOpen = $state(false);

	/** Мобільне «Інше»: вкладки, що не влізають у нижнє меню.
	 *  Головна / Розклад / Домашка / Магазин / Профіль — у барі,
	 *  все інше тут. Нові розділи автоматично потрапляють сюди. */
	const MAIN_TABS: ReadonlySet<Tab> = new Set([
		'home',
		'schedule',
		'homework',
		'shop'
	]);
	/** Видимі вкладки: «Дані» - лише в режимі розробника (за замовчуванням
	 *  вимкнений, вмикається в налаштуваннях). */
	/** ЕКСПЕРИМЕНТАЛЬНІ ВКЛАДКИ («Нагороди», «Прогрес»): фіча готова, але
	 *  ховаємо до аудиту. ПОВЕРНУТИ: поставити true — вкладки самі з'являться
	 *  в меню «Інші розділи», нічого більше міняти не треба. Пізніше тут
	 *  стане перемикач «Керування вкладками» із налаштувань (per-user). */
	const EXPERIMENTAL_TABS = false;
	const HIDDEN_EXPERIMENTAL: ReadonlySet<Tab> = EXPERIMENTAL_TABS
		? new Set()
		: new Set(['awards', 'progress']);
	// ПЛАГІНИ: тимчасово видимі ЛИШЕ юзеру №1 (адміну) — іншим ховаємо.
	// Повернути: поставити false тут (і guard у openTab зніметься сам).
	const PLUGINS_ADMIN_ONLY = true;
	const isPluginsAdmin = $derived(
		!PLUGINS_ADMIN_ONLY || auth.user?.id === 1);
	const visibleTabs = $derived(
		dev.enabled
			? TABS.filter((t) => !HIDDEN_EXPERIMENTAL.has(t.key)
				&& (t.key !== 'plugins' || isPluginsAdmin))
			: TABS.filter((t) => t.key !== 'data'
				&& !HIDDEN_EXPERIMENTAL.has(t.key)
				&& (t.key !== 'plugins' || isPluginsAdmin))
	);
	const OTHER_TABS = $derived(
		visibleTabs.filter((t) => !MAIN_TABS.has(t.key))
	);
	let otherOpen = $state(false);
	const isOther = $derived(OTHER_TABS.some((t) => t.key === tab));
	let hwType = $state<string>('all');
	let hwSubject = $state<string>('all');
	let hwStatus = $state<'all' | '3' | '2' | '1'>('all');
	let hwSort = $state<'deadline_asc' | 'deadline_desc' | 'new' | 'old'>(
		'deadline_asc');
	let submitOpen = $state(false);
	let submitHw: HwItem | null = $state(null);
	let detailsOpen = $state(false);
	let detailsHw: HwItem | null = $state(null);

	function openDetails(h: HwItem): void {
		detailsHw = h;
		detailsOpen = true;
		// URL-стан: модалка домашки має власну адресу ?hw=<id> —
		// посилання можна копіювати, «Назад» закриває модалку.
		if (Number(queryParam('hw')) !== Number(h.id)) {
			pushUrl({ hw: String(h.id) });
		}
	}

	/** Закриття деталей із UI (хрестик/клік повз): прибираємо ?hw= тихо,
	 *  щоб «Назад» після цього не «відкривав» закриту модалку. */
	function closeDetails(): void {
		detailsOpen = false;
		if (queryParam('hw') !== null) replaceUrl({ hw: null });
	}

	/** З модалки деталей просять здати/перездати — відкриваємо здачу. */
	let submitMode: 'submit' | 'resubmit' = $state('submit');

	function startSubmit(kind: 'submit' | 'resubmit'): void {
		submitMode = kind;
		submitHw = detailsHw;
		detailsOpen = false;
		// з модалки переходимо у модалку здачі: ?hw= тихо прибираємо
		// (запис «модалка деталей» лишається в історії — назад → деталі)
		if (queryParam('hw') !== null) replaceUrl({ hw: null });
		submitOpen = true;
	}

	/** Здати можна лише «до виконання» та «ретейк». */
	function canSubmit(h: HwItem): boolean {
		return h.status === 3 || h.status === 5;
	}

	function openSubmit(h: HwItem): void {
		submitHw = h;
		submitOpen = true;
	}


	// свіжий список + оновлені лічильники на Головній
	async function onHwSubmitted(): Promise<void> {
		if (!activeId) return;
		try {
			hw = await store.homework(activeId, true);
			await store.revalidateDashboard(activeId);
			dash = store.dash(activeId) ?? dash;
			stale = false;
		} catch {
			/* тихо: список оновиться при наступному відкритті */
		}
	}

	// навігація розкладу
	let schedKind = $state<'week' | 'month'>('week');
	// ЯКІР ТИЖНЯ — ЗАВЖДИ ПОНЕДІЛОК: раніше тут було new Date() (сьогодні),
	// а заголовки колонок = weekAnchor + i без нормалізації → при відкритті
	// у четвер колонка «Пн» підписувалась датою четверга і ВСІ дати
	// з'їжджали на (день_тижня − 1) днів (дані стояли правильно по днях
	// тижня, але підписи брехали). Тепер anchor нормалізується тут і в
	// усіх місцях присвоєння (Сьогодні / пікер дати / стрибок).
	let weekAnchor = $state<Date>(mondayOf(new Date()));
	let monthAnchor = $state<Date>(new Date());
	let schedLoading = $state(false);
	/** F2: sequence token проти гонки тижнів — під час await може бути
	 *  запущено нове завантаження; старе НЕ чіпає sched/schedLoading. */
	let schedSeq = 0;
	let browserOnline = $state(true);
	let backendUp = $state(true);
	const offline = $derived(!browserOnline || !backendUp);

	const account = $derived(accounts.find((a) => a.id === activeId) ?? null);
	const tabTitle = $derived(TABS.find((t) => t.key === tab)?.label ?? '');

	function openProfile(): void {
		menuOpen = false;
		// спочатку перегляд із кнопкою «Редагувати», не одразу редагування
		profileEdit = false;
		profileOpen = true;
	}

	function iso(d: Date): string {
		return toIsoLocal(d);
	}

	function shiftWeek(delta: number): void {
		weekAnchor = new Date(weekAnchor.setDate(weekAnchor.getDate() + delta * 7));
		void loadSchedule();
	}

	function shiftMonth(delta: number): void {
		monthAnchor = new Date(monthAnchor.setMonth(monthAnchor.getMonth() + delta));
		void loadSchedule();
	}

	function schedToday(): void {
		weekAnchor = mondayOf(new Date());
		monthAnchor = new Date();
		sched = null;
		void loadSchedule();
	}

	$effect(() => {
		if (auth.restored && !auth.isAuthed) goto('/login');
	});

	// єдиний лоадер: чекаємо відновлення сесії → вантажим рівно один раз
	$effect(() => {
		if (!auth.restored) return; // сесія ще відновлюється з localStorage
		if (!auth.isAuthed) {
			goto('/login');
			return;
		}
		if (!started) {
			started = true;
			void load().then(() => void handleDeepLink());
		}
	});
	// Хмарні розкладки віджетів: старт із класу поточного пристрою
	// (рендер одразу з локального кешу ВСІХ класів), потім тягнемо
	// сервер у фоні — якщо там свіжіша карта, мержимо.
	device.start();
	widgets.initFrom(device.cls);
	if (auth.isAuthed) void widgets.pullCloud();
	// Хмарні налаштування оформлення: та сама схема — сервер у фоні,
	// сервер переважає локальний вибір (theme.syncFromServer → applyRemote).
	if (auth.isAuthed) void theme.pullCloud();

	// Зміна класу пристрою БЕЗ перезавантаження (поворот планшета,
	// ноутбук-трансформер, звуження вікна): тихо підвантажуємо збережену
	// розкладку потрібного класу (модалку-попередження прибрано на прохання власника).
	$effect(() => {
		const v = device.version;
		if (v === layoutClsSeen) return;
		layoutClsSeen = v;
		if (v === 0) return; // стартовий init
		const cls = device.cls;
		untrack(() => {
			widgets.switchTo(cls);
			// сервер може мати свіжішу карту цього класу — тягнемо тихо
			void widgets.syncFromServer();
		});
	});


	$effect(() => {
		browserOnline = navigator.onLine;
		const on = () => {
			browserOnline = true;
			// мережа повернулась — тихо оновлюємо дані
			if (dash) void refreshSilent();
		};
		const off = () => (browserOnline = false);
		window.addEventListener('online', on);
		window.addEventListener('offline', off);
		return () => {
			window.removeEventListener('online', on);
			window.removeEventListener('offline', off);
		};
	});

	const ACC_LS_KEY = 'm1id.accounts';

	function saveAccountsCache(list: AccountOut[]): void {
		try {
			localStorage.setItem(ACC_LS_KEY, JSON.stringify(list));
		} catch {
			/* приватний режим */
		}
	}

	function readAccountsCache(): AccountOut[] {
		try {
			return JSON.parse(localStorage.getItem(ACC_LS_KEY) ?? '[]') as AccountOut[];
		} catch {
			return [];
		}
	}

	/** Тиха звірка після миттєвого старту: свіжий список акаунтів +
	 *  ревалідація дашборда (refreshSilent сам оновить backendUp/stale). */
	async function bootSilent(): Promise<void> {
		try {
			const list = await api.accountsList();
			backendUp = true;
			saveAccountsCache(list);
			if (activeId && !list.some((a) => a.id === activeId)) return;
			accounts = list;
		} catch {
			/* офлайн / бекенд лежить — вже малюємо з кешу */
			backendUp = false;
		} finally {
			void refreshSilent();
		}
	}

	/** Відновлення вкладки з URL при буті (reload, шарення посилання).
	 *  Невідомий/прихований tab → openTab м'яко поверне на Головну.
	 *  Deep-link з ?hw=: вкладку відкриє handleDeepLink — але шелл
	 *  рендериться лише з dash, тому тут тихо вантажимо Головну
	 *  (для холодного старту), hw-параметр не чіпаємо. */
	async function bootTab(): Promise<void> {
		const t = queryParam('tab');
		// Шелл рендериться лише з dash — тому при буті Головну вантажимо
		// ПЕРШОЮ (навіть коли ?tab= вказує на іншу вкладку). Раніше
		// reload на ?tab=schedule вантажив лише розклад, dash лишався
		// null і кубик «Майже готово» висів, поки dash не з'явився
		// звідкись ще (у гіршому разі — назавжди).
		if (!dash) await openTab('home', false, false);
		if (t && VALID_TABS.has(t) && t !== 'home') {
			await openTab(t as Tab, false, false);
		}
	}

	/** Офлайн без кешу: openTab мовчки ковтає мережеву помилку, dash лишається
	 *  null → вічний BootCube. Показуємо екран помилки з кнопкою «Спробувати знову». */
	function bootOfflineGuard(): void {
		if (dash || needRelogin || err) return;
		if (!backendUp || !browserOnline || stale) {
			err = friendlyError(new ApiError('network_error', '', 'network'));
			booting = false;
		}
	}

	async function load() {
		booting = true;
		bootNote = 'Ми готуємо все для вас…';
		err = '';
		needRelogin = false;
		stale = false;
		bannerClosed = false;

		// ── МИТТЄВИЙ СТАРТ (до мережі): є клієнтський кеш акаунта →
		//    малюємо UI просто зараз, сервер смикаємо тихою звіркою у фоні.
		const wanted0 = Number(page.url.searchParams.get('account')) || null;
		const cand =
			wanted0 ?? (Number(localStorage.getItem('m1id.lastAccount')) || null);
		if (cand && store.restore(cand) && store.dash(cand)) {
			activeId = cand;
			try {
				localStorage.setItem('m1id.lastAccount', String(cand));
			} catch {
				/* приватний режим / quota — не критично */
			}
			dash = store.dash(activeId)!;
			const cachedAccs = readAccountsCache();
			accounts = cachedAccs.length
				? cachedAccs
				: ([{ id: cand }] as unknown as AccountOut[]);
			booting = false;
			stale = !store.isFresh(activeId);
			void bootSilent();
			await bootTab();
			return;
		}

		try {
			accounts = await api.accountsList();
			saveAccountsCache(accounts);
			const wanted = Number(page.url.searchParams.get('account')) || null;
			activeId =
				wanted && accounts.some((a) => a.id === wanted)
					? wanted
					: (accounts[0]?.id ?? null);
			if (!activeId) {
				dash = null;
				return;
			}
			try {
				localStorage.setItem('m1id.lastAccount', String(activeId));
			} catch {
				/* приватний режим / quota — не критично */
			}

			// ── офлайн-first: миттєво з кешу, потім тихе оновлення ──
			const hadCache = store.restore(activeId);
			if (hadCache && store.dash(activeId)) {
				dash = store.dash(activeId)!;
				booting = false;
				stale = !store.isFresh(activeId);
				void refreshSilent();
				await bootTab();
				return;
			}

			bootNote = 'Майже готово...';
			backendUp = true;
			// старт: вкладку беремо з URL (?tab=, reload / шарення),
			// інакше Головна; ?hw= не чіпаємо — ним керує handleDeepLink
			await bootTab();
			bootOfflineGuard();
		} catch (ex) {
			console.error('[app] load:', ex);
			// мережа/бекенд недоступні → пробуємо офлайн-режим за останнім акаунтом
			if (ex instanceof ApiError && ex.code === 'network') {
				backendUp = false;
				const last =
					Number(localStorage.getItem('m1id.lastAccount')) || null;
				if (last && store.restore(last) && store.dash(last)) {
					activeId = last;
					dash = store.dash(last)!;
					stale = true;
					booting = false;
					return;
				}
			}
			err = friendlyError(ex);
			if (ex instanceof ApiError && ex.code === 'account_needs_relogin') {
				needRelogin = true;
			}
		} finally {
			booting = false;
		}
	}

	/** Повторний вхід у MyStat ПРЯМО зі сторінки бута. Бекенд (/link)
	 *  повторно використовує той самий акаунт (за logbook_id): новий
	 *  токен шифрується чинним .token_key, дані/налаштування/TG-лінки
	 *  лишаються на місці. Після успіху — безшовний перезапуск бута
	 *  (миттєвий старт з клієнтського кешу + тихий свіжий синк). */
	async function doRelogin(e: SubmitEvent): Promise<void> {
		e.preventDefault();
		if (relogBusy) return;
		relogBusy = true;
		relogErr = '';
		try {
			await api.accountLink(relogLogin, relogPass);
			needRelogin = false;
			relogPass = '';
			err = '';
			booting = true;
			bootNote = 'Відновлюємо дані…';
			await load();
		} catch (ex) {
			relogErr = friendlyError(ex);
		} finally {
			relogBusy = false;
		}
	}

	/** Тихе фонове оновлення (stale-while-revalidate): дашборд мимо
	 *  клієнтського кешу, з повагою TTL бекенду. */
	async function refreshSilent(): Promise<void> {
		if (!activeId) return;
		// оновлення цього ж акаунта вже летить — не дублюємо; інший акаунт
		// (після switchAccount) стартує свій цикл, старий буде проігноровано
		if (refreshing && refreshAccId === activeId) return;
		const id = activeId;
		const gen = ++silentGen;
		beginRefresh(id);
		try {
			const res = await store.revalidateAll(id);
			if (id !== activeId || gen !== silentGen) return; // акаунт змінився під час await
			backendUp = true;
			dash = store.dash(id) ?? dash;
			homeMarks = store.marksCache(id) ?? homeMarks;
			newsData = store.newsCache(id) ?? newsData;
			boardMini = store.leaderboardCache(id) ?? boardMini;
			// stale — ЛИШЕ коли дашборд не оновився: падіння новин/магазину
			// не повинне тримати баннер «оновлюємо» і смикати вкладки
			stale = !res.dashOk;
			if (!res.ok) {
				console.warn('[app] partial revalidate (non-critical)');
			}
			syncTabFromStore(id);
			// компоненти вкладок тихо перечитають слоти стора (без мережі,
			// без скелета, без скидання відкритих діалогів)
			dataTick++;
		} catch (ex) {
			console.warn('[app] silent refresh failed (offline?)', ex);
			if (id === activeId && gen === silentGen) {
				if (ex instanceof ApiError && ex.code === 'network') backendUp = false;
				stale = true;
			}
		} finally {
			endRefresh();
		}
	}

	/** Підтягнути ЛОКАЛЬНИЙ стан активної вкладки зі стору: revalidateAll
	 *  оновлює слоти стора, але locальні hw/sched/marksData/shopData
	 *  лишались старими → вкладка показувала вчорашній список, хоча
	 *  дані в сторі вже свіжі («обновляється, але не повністю»). */
	function syncTabFromStore(accId: number): void {
		if (accId !== activeId) return;
		if (tab === 'homework') {
			hw = store.hwCache(accId) ?? hw;
		} else if (tab === 'schedule') {
			// оновлюємо лише поточний тиждень/місяць — навігацію користувача
			// не перебиваємо (ключ інший → кешу просто немає)
			const key = schedKind === 'week'
				? `week:${weekMonday()}`
				: `month:${currentMonthKey()}`;
			sched = store.schedCache(accId, key) ?? sched;
		} else if (tab === 'marks') {
			marksData = store.marksCache(accId) ?? marksData;
		} else if (tab === 'shop') {
			shopData = store.shopCache(accId) ?? shopData;
		}
	}

	// F7: ОДИН таймер для сторожа (30с) і авто-оновлення (5 хв): раніше
	// два незалежні setInterval могли одночасно тягнути revalidateAll
	// (подвійні повні оновлення). Тепер — один тік: раз на 30с перевіряємо
	// свіжість (сторож), раз на 5 хв — повне авто-оновлення.
	$effect(() => {
		if (!activeId || !auth.isAuthed) return;
		// ЗАХОПЛЕННЯ реального accountId: хендл setInterval — це просто число
		// (1, 2, 3…), ним не можна ходити в API (__account=<номер таймера>).
		const accId = activeId;
		let lastAuto = Date.now();
		const id = setInterval(() => {
			if (document.visibilityState !== 'visible') return;
			if (refreshing) return;
			const autoDue = Date.now() - lastAuto >= 5 * 60_000;
			if (autoDue) {
				lastAuto = Date.now();
				// 5 хв: повне тихе оновлення всіх розділів (dash + домашка +
				// оцінки + розклад + новини + лідерборд + магазин) мимо
				// клієнтського кешу, але з повагою TTL бекенду.
				void store
					.revalidateAll(accId)
					.then((res) => {
						if (activeId === accId) {
							backendUp = true;
							dash = store.dash(accId) ?? dash;
							homeMarks = store.marksCache(accId) ?? homeMarks;
							boardMini = store.leaderboardCache(accId) ?? boardMini;
							newsData = store.newsCache(accId) ?? newsData;
							stale = !res.dashOk;
							syncTabFromStore(accId);
							dataTick++; // таб-компоненти тихо перечитають слоти стора
						}
					})
					.catch(() => {});
				return;
			}
			// СТОРОЖ 30с: якщо дані старші за 5 хв (store.isFresh) або висить
			// stale — тихе оновлення. При нестабільній мережі повтор був ЛИШЕ
			// при помилці → «нескінченне оновлення»; таймаут у client.ts
			// обриває зависання, сторож сам дотягує свіжість у фоні.
			if (!stale && store.isFresh(accId)) return;
			void refreshSilent();
		}, 30_000);
		return () => clearInterval(id);
	});

	$effect(() => {
		const onVis = () => {
			// повернення у вкладку: оновлюємо якщо stale АБО даним >5 хв
			// (раніше після успішного refresh stale скидався, і повернення
			// у відкриту вкладку не оновлювало нічого до наступного тика)
			if (document.visibilityState === 'visible' && !refreshing
				&& activeId && (stale || !store.isFresh(activeId))) {
				void refreshSilent();
			}
		};
		document.addEventListener('visibilitychange', onVis);
		return () => document.removeEventListener('visibilitychange', onVis);
	});

	// сторож: якщо завантаження зависло — показуємо діагностику, а не скелет.
	// Стежимо НЕ лише за booting: бут може завершитись, а dash так і не
	// з'явитись (раніше тоді кубик «Майже готово» висів вічно без жодної
	// помилки). Тепер будь-який стан «dash немає» через 12с чесно
	// перетворюється на екран помилки з кнопкою «Спробувати знову».
	$effect(() => {
		if (dash || needRelogin) return;
		let alive = true;
		let timer: ReturnType<typeof setTimeout>;
		const check = (): void => {
			if (!alive) return;
			// синк живий і щось робить → даємо йому ще 10с, не лякаємо юзера
			if (syncState?.status === 'running') {
				timer = setTimeout(check, 10_000);
				return;
			}
			if (!dash && !needRelogin) {
				if (!err) err = 'Сервер не відповідає. Спробуйте пізніше.';
				booting = false;
			}
		};
		timer = setTimeout(check, 12_000);
		return () => {
			alive = false;
			clearTimeout(timer);
		};
	});

	// Застосування стану синку: годує І пігулку «що робить сервер»,
	// І бут-прогрес кубика (реальні done/total, поки dash немає).
	function applySyncState(st: SyncState): void {
		syncState = st;
		bootProgress =
			!dash && st.status === 'running' && st.progress && st.progress.total > 0
				? Math.min(1, st.progress.done / st.progress.total)
				: !dash && st.status === 'done'
					? 1
					: null;
	}

	// Живий пуш через WS /api/ws/sync: сервер САМ пушить зміни стану
	// синку — нуль постійних запитів від клієнта. Обрив → автореконект
	// із бекофом усередині openSyncWs.
	let wsSyncOk = $state(false);
	$effect(() => {
		const id = activeId;
		if (!id) {
			syncState = null;
			bootProgress = null;
			return;
		}
		const h = openSyncWs(
			(seq, st) => {
				if (seq === id) applySyncState(st);
			},
			(ok) => {
				wsSyncOk = ok;
			}
		);
		return () => h.close();
	});

	// Фолбек: доки WS не підключений (проксі без WS, рестарт бекенда) —
	// адаптивний полінг: running 1с / спокій 5с / фонові вкладки 30с.
	$effect(() => {
		const id = activeId;
		if (!id || wsSyncOk) return;
		let stop = false;
		let t: ReturnType<typeof setTimeout>;
		const schedule = (ms: number): void => {
			if (!stop) t = setTimeout(() => void tick(), ms);
		};
		const tick = async (): Promise<void> => {
			try {
				const st = await api.syncStatus(id);
				if (stop) return;
				applySyncState(st);
				// фонові (згорнуті) вкладки практично сплять: 30с
				const hidden = typeof document !== 'undefined' && document.hidden;
				schedule(st.status === 'running' && !hidden ? 1_000
					: hidden ? 30_000 : 5_000);
			} catch {
				if (stop) return;
				bootProgress = null;
				schedule(5_000);
			}
		};
		void tick();
		return () => {
			stop = true;
			clearTimeout(t);
		};
	});

	/** ПОВНЕ оновлення — ОДИН паралельний залп по всіх розділах.
	 *  Раніше: спершу чекали дашборд, і лише потім «різко» тягнули
	 *  решту (плюс тихий revalidateAll зверху — подвійні запити).
	 *  Тепер усі запити стартують разом, і кожен розділ, щойно прийшов,
	 *  ОДРАЗУ оновлює свій UI. Помилка одного розділу (allSettled)
	 *  не ламає решту; дашборд сам знімає баннер «оновлюємо». */
	async function refresh(force = true) {
		const id = activeId;
		if (!id) return;
		bannerClosed = false;
		stale = true;
		beginRefresh();
		try {
			// скидаємо стор-кеші розділів: Shop/Leader/Payments/Contacts
			// перечитають свої дані з force після uiTick; activity — свій $effect
			store.invalidate(id);
			store.activityReset(id);
			homeMarks = null;
			boardAsked = false;

			// поточний ключ розкладу НЕ змінюємо (навігацію юзера зберігаємо)
			const schedKey = schedKind === 'week' ? weekMonday() : undefined;

			const jobs: Promise<unknown>[] = [
				store.loadDashboard(id, force).then((d) => {
					if (id !== activeId) return;
					dash = d;
					backendUp = true;
					stale = false;
					fx.celebrate('sync');
					// Головна: екстрас (оцінки-чіпи, новини, лідерборд-віджет)
					homeMarks = null;
					loadHomeExtras(true);
				}),
				store.homework(id, true).then((v) => {
					if (id === activeId) hw = v;
				}),
				store.schedule(id, schedKind, schedKey, true).then((v) => {
					if (id === activeId) sched = v;
				}),
				store.marks(id, 'year', true).then((m) => {
					if (id === activeId) marksData = m;
				}),
				store.news(id, true).then((v) => {
					if (id === activeId) newsData = v;
				}),
				store.leaderboard(id, true).then((v) => {
					if (id === activeId) boardMini = v;
				}),
				store.shop(id, true).then((s) => {
					if (id === activeId) shopData = s;
				})
			];

			// чекаємо ВСІХ: локальні змінні вкладок (hw/sched/…) не «зникають»
			// під час оновлення — кожен .then підмінює їх лише свіжим значенням
			const out = await Promise.allSettled(jobs);
			if (id !== activeId) return; // акаунт змінили — його стан не чіпаємо

			// дашборд — головний: його успіх знімає баннер «оновлюємо»
			stale = out[0]!.status !== 'fulfilled';
			for (const r of out) {
				if (r.status === 'fulfilled') continue;
				const ex = r.reason as unknown;
				console.warn('[app] refresh section failed:', ex);
				if (ex instanceof ApiError && ex.code === 'network') backendUp = false;
			}
			// тик для таб-компонентів (Shop/Leader/Payments/Contacts):
			// вони перечитують слоти стора з force=true
			uiTick++;
		} finally {
			endRefresh();
		}
	}

	async function handleDeepLink(): Promise<void> {
		// Deep-link з Telegram: /app?account=N&hw=ID&lb=<logbook> → вкладка
		// «Домашка» + модалка завдання. Параметри прибираємо з URL, щоб
		// перезавантаження сторінки не перевідкривало модалку.
		const hwParam = Number(page.url.searchParams.get('hw')) || null;
		if (!hwParam || !activeId) return;
		// Перевірка «свій акаунт?»: бот додає lb=<logbook_id>. Шукаємо акаунт
		// з таким logbook серед СВОЇХ: якщо знайшли — перемикаємось на нього
		// і відкриваємо; немає такого акаунта — помилка, чужі дані не показуємо.
		const lbParam = page.url.searchParams.get('lb');
		if (lbParam) {
			const match = accounts.find(
				(a) => String(a.logbook_id) === lbParam);
			if (!match) {
				err =
					'⚠ Це посилання на завдання акаунта, якого немає серед ваших. Спочатку додайте його у M1 ID.';
				void goto('/app', { replaceState: true });
				return;
			}
			if (match.id !== activeId) await switchAccount(match.id);
		}
		try {
			await openTab('homework');
			const list = hw ?? (await store.homework(activeId, false));
			const item = (list?.items ?? []).find(
				(x) => Number(x.id) === hwParam);
			if (item) {
				openDetails(item);
				return;
			}
			// завдання немає в загальному списку (напр. статус схований) -
			// пробуємо ще раз через повне оновлення стору з force
			const fresh = await store.homework(activeId, true);
			const item2 = (fresh?.items ?? []).find(
				(x) => Number(x.id) === hwParam);
			if (item2) openDetails(item2);
		} catch (ex) {
			console.warn('[app] deep-link hw:', ex);
		} finally {
			if (page.url.searchParams.get('hw')) {
				goto('/app', { replaceState: true });
			}
		}
	}

	async function switchTo(e: Event) {
		await switchAccount(Number((e.currentTarget as HTMLSelectElement).value));
	}

	/** Перемикання активного акаунта: URL, lastAccount, скидання стану. */
	async function switchAccount(id: number): Promise<void> {
		goto(`/app?account=${id}`, { replaceState: true });
		activeId = id;
		try {
			localStorage.setItem('m1id.lastAccount', String(id));
		} catch {
			/* приватний режим / quota — не критично */
		}
		err = '';
		stale = false;
		bannerClosed = false;
		dash = null;
		hw = null;
		sched = null;
		marksData = null;
		homeMarks = null;
		newsData = null;
		shopData = null;
		boardMini = null;
		boardAsked = false;
		snapshots = [];
		// як при повному завантаженні: якщо у акаунта є клієнтський кеш —
		// малюємо його одразу, а свіжі дані тягнемо тихою звіркою
		if (!store.dash(id)) store.restore(id);
		const cachedDash = store.dash(id);
		if (cachedDash) {
			dash = cachedDash;
			stale = !store.isFresh(id);
			void refreshSilent();
		} else if (tab !== 'home') {
			// кешу немає, а openTab тягне дашборд лише для Головної → без цього
			// dash лишався null і через 12с сторож показував «Сервер не відповідає»
			void store.loadDashboard(id).then(
				(d) => {
					if (activeId === id) dash = d;
				},
				(ex) => {
					if (activeId !== id) return;
					if (isNetworkError(ex)) {
						backendUp = false;
						stale = true;
					} else {
						err = friendlyError(ex);
						if (ex instanceof ApiError && ex.code === 'account_needs_relogin') needRelogin = true;
					}
				}
			);
		}
		// зміна акаунта вже зробила replaceState — не плодимо запис.
	// Поточну вкладку зберігаємо (record=false → replace, без запису
	// історії): перехід між акаунтами не скидає юзера на Головну.
	// Приховані/адмінські вкладки openTab сам м'яко поверне на 'home'.
		await openTab(tab, false, false);
	}

	/** `dir` — напрям View Transition: за замовчуванням за індексом вкладки
	 *  (record=false, тобто popstate/відновлення, — 'fade'); 'up' для меню «Інше». */
	async function openTab(t: Tab, force = false, record = true, dir?: VTDir): Promise<void> {
		hoverCard.close();
		if (!activeId) return;
		// «Дані» - технічна вкладка тільки для режиму розробника
		if (t === 'data' && !dev.enabled) t = 'home';
		// Плагіни тимчасово лише для адміна (юзер №1): deep-link/стара URL
		// не відкриє приховану вкладку — м'яко повертаємо на Головну
		if (t === 'plugins' && !isPluginsAdmin) t = 'home';
		// Сховані експериментальні вкладки (аудит): deep-link/стара URL
		// не повинні відкривати приховане — м'яко повертаємо на Головну
		if (HIDDEN_EXPERIMENTAL.has(t)) t = 'home';
		const prevTab = tab;
		const applyTab = (): void => {
			// flushSync: DOM оновлюється синхронно, анімація стартує вже на новому вмісті
			try {
				flushSync(() => {
					tab = t;
					busyTab = t;
				});
			} catch {
				// flushSync заборонений усередині effect — просто присвоюємо
				tab = t;
				busyTab = t;
			}
			contentEl?.scrollTo({ top: 0 });
			contentScrolled = false;
		};
		if (t !== prevTab && dash && contentEl) {
			let d: VTDir = dir ?? 'fade';
			if (!dir && record) {
				const from = visibleTabs.findIndex((x) => x.key === prevTab);
				const to = visibleTabs.findIndex((x) => x.key === t);
				d = from < 0 || to < 0 ? 'fade' : to > from ? 'forward' : 'back';
			}
			// живий DOM + легка анімація контейнера (без знімків View Transitions)
			applyTab();
			enterContent(contentEl, d);
		} else {
			tab = t;
			busyTab = t;
		}
		// URL-стан: адреса міняється при кожній вкладці (без reload,
		// «Назад» повертає попередню вкладку). На старті (record=false)
		// — лише replace, щоб не народжувати зайвий запис історії.
		if (record) pushUrl({ tab: t, hw: null });
		else replaceUrl({ tab: t, hw: null });
		// фіксуємо акаунт на вході: після await activeId може змінитися
		// (гонка «хто останній вирішиться» — на екрані дані чужого акаунта)
		const id = activeId;
		try {
			if (t === 'home') {
				const d = await store.loadDashboard(id, force);
				if (id !== activeId) return;
				dash = d;
			} else if (t === 'schedule') await loadSchedule();
			else if (t === 'homework') {
				const v = await store.homework(id);
				if (id !== activeId) return;
				hw = v;
			} else if (t === 'marks') {
				const v = await store.marks(id, 'year');
				if (id !== activeId) return;
				marksData = v;
			} else if (t === 'shop') {
				const v = await store.shop(id);
				if (id !== activeId) return;
				shopData = v;
			} else if (t === 'activity') await store.activityFirst(id);
			else if (t === 'data') {
				const v = await store.snapshots(id);
				if (id !== activeId) return;
				snapshots = v;
			}
		} catch (ex) {
			// запит старого акаунта (юзер вже перемкнувся) — не помилка нового
			if (id !== activeId) return;
			console.warn('[app] openTab:', t, ex);
			if (isNetworkError(ex)) {
				// офлайн / бекенд недоступний: про це каже StaleBanner,
				// вкладка лишається з кешем (або спокійним порожнім станом)
				backendUp = false;
				stale = true;
			} else {
				err = friendlyError(ex);
				if (ex instanceof ApiError && ex.code === 'account_needs_relogin') {
					needRelogin = true;
				}
			}
		} finally {
			if (id === activeId) busyTab = '';
		}
	}

	// чіпи оцінок на Головній: підтягуємо самі, бо офлайн-first бут із кеша
	// минає openTab('home') → інакше карточка вічно показує скелет.
	// loadHomeExtras(force): «Оновити» викликає з force=true — раніше
	// homeMarks/news/лідерборд-віджет ніколи не форсувались (тижневий кеш).
	function loadHomeExtras(force = false): void {
		const id = activeId;
		if (!id || !dash) return;
		void store.marks(id, 'year', force)
			.then((m) => {
				if (activeId === id) homeMarks = m; // перегони при switch акаунта
			})
			.catch(() => {});
		// новини для картки на Головній — так само, з кеша стора
		void store.news(id, force)
			.then((n) => {
				if (activeId === id) newsData = n;
			})
			.catch(() => {});
		if (widgets.isOn('board')) ensureBoard(force);
	}

	$effect(() => {
		const id = activeId;
		if (!id || !dash) return;
		loadHomeExtras(false);
	});

	/** Дозавантажити лідерборд для віджета (один раз на акаунт;
	 *  force=true з «Оновити» — перечитуємо незважаючи на boardAsked). */
	let boardAsked = false;
	let qrOpen = $state(false);
	/** Тик «Оновити» для таб-компонентів: bump → Shop/Leader/Payments/
	 *  Contacts перечитують свої дані з force=true (раніше mount-load
	 *  без force показував localStorage-кеш будь-якої давнини). */
	let uiTick = $state(0);
	/** Тихий сигнал «слоти стора оновились у фоні» (refreshSilent / авто-
	 *  оновлення): вкладки перечитують кеш БЕЗ мережі, скелета й скидання
	 *  локального UI (діалог підтвердження покупки тощо). Відрізняється
	 *  від uiTick, який міняється лише на явне «Оновити». */
	let dataTick = $state(0);
	function ensureBoard(force = false): void {
		const id = activeId;
		if (!id) return;
		if (boardAsked && !force) return;
		boardAsked = true;
		void api.leaderboard(id, force)
			.then((v) => {
				if (activeId === id) boardMini = v;
			})
			.catch(() => {
				if (!force) boardAsked = false;
			});
	}

	async function loadSchedule(force = false): Promise<void> {
		if (!activeId) return;
		// F2: sequence token — переможець гонки тільки найновіший запит
		const seq = ++schedSeq;
		schedLoading = true;
		// фіксуємо акаунт/вид/якір на вході: швидке гортання тижнів або
		// зміна акаунта під час await → на екрані дані іншого тижня
		const id = activeId;
		const kind = schedKind;
		const anchorIso = kind === 'week' ? iso(weekAnchor)
			: iso(monthAnchor).slice(0, 7);
		try {
			if (kind === 'week') {
				const v = await store.schedule(id, 'week', anchorIso, force);
				if (seq !== schedSeq || id !== activeId) return;
				sched = v;
			} else {
				const v = await store.schedule(id, 'month',
					anchorIso, force);
				if (seq !== schedSeq || id !== activeId) return;
				sched = v;
			}
		} catch (ex) {
			if (seq !== schedSeq || id !== activeId) return; // прострочений запит — без err
			console.warn('[app] schedule:', ex);
			if (isNetworkError(ex)) {
				backendUp = false;
				stale = true;
			} else {
				err = friendlyError(ex);
			}
		} finally {
			if (seq === schedSeq) schedLoading = false;
		}
	}

	/** Стрибок по календарю (input date/month). */
	function onDatePick(e: Event): void {
		const v = (e.currentTarget as HTMLInputElement).value;
		if (!v) return;
		if (schedKind === 'week') {
			// будь-яка обрана дата → її ПОНЕДІЛОК (інакше заголовки
			// колонок з'їжджали на (день_тижня − 1) днів)
			weekAnchor = mondayOf(new Date(`${v}T12:00:00`));
		} else {
			monthAnchor = new Date(`${v}-01T12:00:00`);
		}
		sched = null;
		void loadSchedule();
	}

	function jumpTo(dateIso: string): void {
		if (schedKind === 'week') {
			// → понеділок тижня цієї дати (див. коментар до weekAnchor)
			weekAnchor = mondayOf(new Date(`${dateIso}T12:00:00`));
		} else {
			monthAnchor = new Date(`${dateIso.slice(0, 7)}-01T12:00:00`);
		}
		sched = null;
		void loadSchedule();
	}

	function onKeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape') {
			menuOpen = false;
			newsOpen = false;
			editHome = false;
			return;
		}
		if (tab !== 'schedule') return;
		if (e.key === 'ArrowLeft')
			schedKind === 'week' ? shiftWeek(-1) : shiftMonth(-1);
		if (e.key === 'ArrowRight')
			schedKind === 'week' ? shiftWeek(1) : shiftMonth(1);
	}

	// мобільний режим «один день» + сітка 7 колонок для десктопа
	let schedSel = $state('');

	// спливне вікно уроку — спільний HoverCard (hover на десктопі, тап на телефоні)
	function cellEnter(e: MouseEvent, l: SchedLesson): void {
		const a = e.currentTarget as HTMLElement | null;
		if (!a) return;
		const key = `lesson|${l.start}|${l.end}|${l.subject}|${l.room}|${l.theme ?? ''}`;
		const data = { kind: 'lesson' as const, l };
		if (e.type === 'mouseenter') {
			// на дотик mouseenter приходить разом із тапом — його обробляє click
			if (canHover()) hoverCard.hover(a, key, data, e.clientX);
			return;
		}
		if (canHover()) hoverCard.show(a, key, data, e.type === 'click' ? e.clientX : null);
		else hoverCard.toggle(a, key, data);
	}

	function cellLeave(): void {
		hoverCard.unhover();
	}

	$effect(() => {
		const days = sched?.days ?? [];
		if (!days.length) {
			schedSel = '';
			return;
		}
		const t = iso(new Date());
		schedSel = days.some((d) => d.date === t) ? t : days[0].date;
	});

	// свайп по розкладу
	let touchX = $state<number | null>(null);
	function tstart(e: TouchEvent) {
		touchX = e.touches[0]?.clientX ?? null;
	}
	function tend(e: TouchEvent) {
		if (touchX === null || tab !== 'schedule') return;
		const dx = (e.changedTouches[0]?.clientX ?? 0) - touchX;
		touchX = null;
		if (Math.abs(dx) <= 60) return;
		// на телефоні свайп гортає дні, на десктопі — тижні/місяці
		if (window.matchMedia('(max-width: 860px)').matches
				&& schedKind === 'week') {
			const days = sched?.days ?? [];
			const i = days.findIndex((d) => d.date === schedSel);
			const ni = i + (dx < 0 ? 1 : -1);
			if (ni >= 0 && ni < days.length) schedSel = days[ni].date;
			return;
		}
		schedKind === 'week' ? shiftWeek(dx < 0 ? 1 : -1)
			: shiftMonth(dx < 0 ? 1 : -1);
	}

	async function show(section: string) {
		if (!activeId) return;
		sectionPayload = await store.snapshotPayload(activeId, section);
		openSection = section;
	}

	// нескінченний скрол ленти нарахувань
	const activity = $derived(activeId ? store.activity(activeId) : undefined);

	// «Останні нарахування» (віджет і вкладка): підтягуємо, щойно є
	// дашборд і ще немає кешу активності. Офлайн/помилка — мовчки,
	// стейл-банер і ручний refresh headline
	$effect(() => {
		if (!dash || !activeId) return;
		if (!store.activity(activeId)) {
			store.activityFirst(activeId).catch(() => {
				/* офлайн — спробуємо пізніше через refresh */
			});
		}
	});

	/** Поява оболонки після бут-екрана: сайдбар, топбар і нижня панель
	 *  випливають із легким зсувом (вміст має власний каскад появи). */
	function shellIn(node: HTMLElement): void {
		if (!motionOK()) return;
		const parts: [string, string][] = [
			['.side', 'translateX(-16px)'],
			['.topbar', 'translateY(-12px)'],
			['.bottombar', 'translateY(16px)']
		];
		parts.forEach(([sel, from], i) => {
			node.querySelector<HTMLElement>(sel)?.animate(
				[{ opacity: 0, transform: from }, { opacity: 1, transform: 'none' }],
				{ duration: 520, delay: 120 + i * 50, easing: ease('spring'), fill: 'backwards' }
			);
		});
	}

	// Модалка відкрита → нижню панель примусово показуємо (модалки над нею
	// рахують висоту з урахуванням --nav-total, див. SubmitModal/HomeworkDetailsModal).
	const modalOpen = $derived(
		submitOpen || detailsOpen || newsOpen || qrOpen || profileOpen ||
			settingsOpen || sessionsOpen || m1AllOpen
	);

	// Автоховання нижньої панелі: вниз > 12px — ховаємо, вгору / верх / низ списку — показуємо.
	let navHidden = $state(false);
	let navLastTop = 0;
	let navAccum = 0;

	function onContentScroll(e: Event): void {
		markScrolling();
		contentScrolled = (e.currentTarget as HTMLElement).scrollTop > 8;
		{
			const s = e.currentTarget as HTMLElement;
			const top = s.scrollTop;
			const d = top - navLastTop;
			navLastTop = top;
			if (top <= 24 || top + s.clientHeight >= s.scrollHeight - 40) {
				navAccum = 0;
				navHidden = false;
			} else {
				if (d * navAccum < 0) navAccum = 0;
				navAccum += d;
				if (navAccum > 12) navHidden = true;
				else if (navAccum < -6) navHidden = false;
			}
		}
		if (tab !== 'activity' || !activeId) return;
		const el = e.currentTarget as HTMLElement;
		if (el.scrollTop + el.clientHeight >= el.scrollHeight - 420) {
			void store.activityNext(activeId);
		}
	}
</script>

{#snippet tabPage(load: () => Promise<any>, props: Record<string, unknown>)}
	<!-- без .m1-enter: контейнер уже анімує enterContent (інакше дві анімації разом) -->
	<section class="tab-page">
		<LazyComponent {load} {props} />
	</section>
{/snippet}

<svelte:head><title>M1 ID</title><meta name="robots" content="noindex, nofollow" /></svelte:head>
<svelte:window onkeydown={onKeydown} onscroll={markScrolling} />

{#if !dash}
	<AppBoot
		{needRelogin}
		{err}
		noAccounts={accounts.length === 0 && !booting}
		{bootNote}
		{bootProgress}
		bind:relogLogin
		bind:relogPass
		{relogBusy}
		{relogErr}
		{doRelogin}
		onretry={() => {
			err = '';
			void load().then(() => void handleDeepLink());
		}}
	/>
{:else}
	<div class="shell" use:shellIn>
		<StaleBanner
			show={(stale || refreshing) && !bannerClosed && !!dash}
			offline={offline}
			refreshing={refreshing && !offline}
			onclose={() => (bannerClosed = true)}
		/>
		<!-- пігулка «що робить сервер»: з'являється лише під час реального
			синку/помилки; у стані спокою місця не займає -->
		<ServerStatus state={syncState} />
		<AppSidebar tabs={visibleTabs} {tab} bind:menuOpen onopen={openTab} />

		<main class="main" onscroll={markScrolling}>
			<AppTopbar
				title={tabTitle}
				{tab}
				{offline}
				{accounts}
				{activeId}
				busy={busyTab !== ''}
				scrolled={contentScrolled}
				bind:editHome
				{switchTo}
				onrefresh={() => refresh()}
			/>

			<section
				bind:this={contentEl}
				class="content"
				use:smoothWheel
				class:padded={tab !== 'home'}
				aria-label="Вміст розділу"
				ontouchstart={tstart}
				ontouchend={tend}
				onscroll={onContentScroll}
			>
				{#if err}
					<div class="fatal m1-enter">
						<ErrorState title="Не вдалося завантажити дані" description={err}>
							{#snippet action()}
								{#if needRelogin}
									<Button href="/accounts" icon={LogIn}>Увійти знову</Button>
								{:else}
									<Button variant="secondary" icon={RotateCw} onclick={() => refresh()}>Спробувати ще</Button>
								{/if}
							{/snippet}
						</ErrorState>
					</div>
				{/if}

				<OtherMenu
					bind:otherOpen
					{tab}
					tabs={OTHER_TABS}
					onopen={(t) => openTab(t, false, true, 'up')}
				/>

				{#if (tab === 'home' || homeKept) && dash}
					<div bind:this={homeEl} style:display={tab === 'home' ? 'contents' : 'none'}>
					<HomeView
						{dash}
						{activeId}
						{contentEl}
						{scrolling}
						bind:editHome
						bind:bScope
						bind:bPeriod
						{activity}
						{newsData}
						{homeMarks}
						{boardMini}
						{openTab}
						{openDetails}
						{cellEnter}
						{cellLeave}
						{ensureBoard}
						onnews={() => (newsOpen = true)}
					/>
					</div>
				{/if}
				{#if tab === 'schedule'}
					<ScheduleScreen
						{sched}
						{schedKind}
						{schedLoading}
						busy={busyTab === 'schedule'}
						{weekAnchor}
						{monthAnchor}
						bind:schedSel
						{shiftWeek}
						{shiftMonth}
						{schedToday}
						{onDatePick}
						ontogglekind={() => {
							schedKind = schedKind === 'week' ? 'month' : 'week';
							sched = null;
							void loadSchedule();
						}}
						{jumpTo}
						{cellEnter}
						{cellLeave}
					/>
				{:else if tab === 'homework'}
					<HomeworkScreen
						{hw}
						busy={busyTab === 'homework'}
						bind:hwType
						bind:hwSubject
						bind:hwStatus
						bind:hwSort
						onopen={openDetails}
						onm1={() => (m1AllOpen = true)}
					/>
				{:else if tab === 'marks'}
					<MarksScreen {marksData} />
				{:else if tab === 'shop'}
					{@render tabPage(() => import('$lib/components/ShopTab.svelte'), { account_id: activeId ?? 0, refreshTick: uiTick, dataTick })}
				{:else if tab === 'nutrition' && account && account.branch_alias.toLowerCase() !== 'pl'}
					<!-- FoodStep працює лише для філії pl (Полтава) -->
					<EmptyState
						icon={Utensils}
						title="Ваша філія не підтримується"
						description="Харчування (FoodStep) доступне лише для студентів філії Полтава."
					/>
				{:else if tab === 'nutrition'}
					{@render tabPage(() => import('$lib/components/NutritionTab.svelte'), { refreshTick: uiTick })}
				{:else if tab === 'payments'}
					{@render tabPage(() => import('$lib/components/PaymentsTab.svelte'), { account_id: activeId ?? 0, refreshTick: uiTick, dataTick })}
				{:else if tab === 'clubs'}
					{@render tabPage(() => import('$lib/components/ClubsTab.svelte'), { account_id: activeId ?? 0, refreshTick: uiTick, dataTick })}
				{:else if tab === 'contacts'}
					{@render tabPage(() => import('$lib/components/ContactsTab.svelte'), { account_id: activeId ?? 0, refreshTick: uiTick, dataTick })}
				{:else if tab === 'notes'}
					{@render tabPage(() => import('$lib/components/NotesTab.svelte'), { account_id: activeId ?? 0 })}
				{:else if tab === 'board'}
					{@render tabPage(() => import('$lib/components/LeaderTab.svelte'), { account_id: activeId ?? 0, refreshTick: uiTick, dataTick, my_fio: dash?.user?.fio ?? null })}
				{:else if tab === 'awards'}
					{@render tabPage(() => import('$lib/components/AwardsTab.svelte'), { account_id: activeId ?? 0, refreshTick: uiTick, dataTick })}
				{:else if tab === 'progress'}
					{@render tabPage(() => import('$lib/components/ProgressTab.svelte'), { account_id: activeId ?? 0, refreshTick: uiTick, dataTick })}
				{:else if tab === 'telegram'}
					{@render tabPage(() => import('$lib/components/TelegramPanel.svelte'), { active: tab === 'telegram' })}
				{:else if tab === 'plugins'}
					{@render tabPage(() => import('$lib/components/PluginsPanel.svelte'), { active: tab === 'plugins' })}
				{:else if tab === 'extras'}
					{@render tabPage(() => import('$lib/components/ExtrasPanel.svelte'), { active: tab === 'extras' })}
				{:else if tab === 'activity'}
					<ActivityView
						{activeId}
						balances={dash.balances.items}
						{activity}
						busy={busyTab === 'activity'}
					/>
				{:else}
					<DataView {snapshots} {openSection} {sectionPayload} onshow={show} />
				{/if}
			</section>
		</main>

		<AppBottomNav
			tabs={visibleTabs}
			mainTabs={MAIN_TABS}
			{tab}
			{isOther}
			bind:menuOpen
			onopen={openTab}
			onother={() => (otherOpen = !otherOpen)}
			hidden={navHidden}
			{otherOpen}
			forceShow={modalOpen}
		/>

		<ProfileMenu
			bind:menuOpen
			user={dash.user}
			onprofile={openProfile}
			onsettings={() => (settingsOpen = true)}
			onsessions={() => (sessionsOpen = true)}
		/>
	</div>
{/if}

<!-- спільне спливне вікно (уроки, оцінки): на верхньому рівні, щоб працював
     і з віджета «Сьогодні» на Головній (tab = home) -->
<HoverCards
	onall={() => {
		hoverCard.close();
		void openTab('homework');
	}}
/>

<LazyComponent
	now={settingsOpen}
	load={() => import('$lib/components/SettingsModal.svelte')}
	props={{ open: settingsOpen, onclose: () => (settingsOpen = false) }}
/>

<LazyComponent
	now={sessionsOpen}
	load={() => import('$lib/components/SessionsModal.svelte')}
	props={{ open: sessionsOpen, onclose: () => (sessionsOpen = false) }}
/>

<LazyComponent
	now={m1AllOpen}
	load={() => import('$lib/components/M1LinkModal.svelte')}
	props={{ open: m1AllOpen, account: activeId ?? 0, onclose: () => (m1AllOpen = false) }}
/>

<LazyComponent
	now={profileOpen}
	load={() => import('$lib/components/ProfileModal.svelte')}
	props={{
		open: profileOpen,
		editMode: profileEdit,
		account,
		user: dash?.user ?? null,
		onclose: () => (profileOpen = false),
		onqr: () => {
			profileOpen = false;
			qrOpen = true;
		}
	}}
/>

<LazyComponent
	now={submitOpen}
	load={() => import('$lib/components/SubmitModal.svelte')}
	props={{
		open: submitOpen,
		hw: submitHw,
		account: activeId ?? 0,
		mode: submitMode,
		onclose: () => (submitOpen = false),
		onsubmitted: onHwSubmitted
	}}
/>

<LazyComponent
	now={detailsOpen}
	load={() => import('$lib/components/HomeworkDetailsModal.svelte')}
	props={{
		open: detailsOpen,
		hw: detailsHw,
		account: activeId ?? 0,
		onclose: () => closeDetails(),
		onsubmitrequest: startSubmit,
		onchanged: onHwSubmitted
	}}
/>

{#if newsOpen}
	<LazyComponent
		load={() => import('$lib/components/NewsModal.svelte')}
		props={{ account_id: activeId ?? 0, onclose: () => (newsOpen = false) }}
	/>
{/if}

{#if qrOpen}
	<LazyComponent
		load={() => import('$lib/components/QrModal.svelte')}
		props={{
			open: qrOpen,
			account_id: activeId ?? 0,
			fio: dash?.user?.fio,
			onclose: () => (qrOpen = false)
		}}
	/>
{/if}

<style>
	/* ================= шелл ================= */

	.shell {
		display: flex;
		height: 100dvh;
		overflow: hidden;
		background: var(--color-bg);
	}

	.main {
		flex: 1;
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	/* Контент: центрується до --content-max через бічні відступи
	   (скрол-контейнер лишається на всю ширину), враховує safe-area. */
	.content {
		min-height: 0;
		flex: 1;
		overflow-y: auto;
		overscroll-behavior: contain;
		padding: var(--space-6)
			max(
				var(--space-6),
				calc((100% - var(--content-max)) / 2),
				env(safe-area-inset-right)
			)
			var(--space-10)
			max(
				var(--space-6),
				calc((100% - var(--content-max)) / 2),
				env(safe-area-inset-left)
			);
	}

	/* Нейтральна сторінка вкладки: без поверхні, картки малює сам вигляд */
	.tab-page {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		min-width: 0;
	}

	.fatal {
		margin-bottom: var(--space-4);
		border-radius: var(--radius-lg);
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		box-shadow: var(--shadow-sm);
	}

	@media (max-width: 900px) {
		.shell {
			flex-direction: column;
			/* жорсткий шелл на всю висоту viewport: сторінка ВЗАГАЛІ
			не скролиться — скролиться лише .content всередині.
			Тоді контент домашки (найдовший таб) не може «виштовхати»
			нижню панель за екран на жодному браузері. */
			height: 100vh;
			height: 100dvh;
			overflow: hidden;
		}

		/* КРИТИЧНО: .main - flex-елемент КОЛОНКОВОГО .shell. Без
		min-height: 0 автоматичний мінімум (min-height: auto) дорівнює
		висоті контенту → .main не стискається до viewport, .content
		ніколи не переповнюється і НЕ СКРОЛИТЬСЯ (на десктопі працювало,
		бо там головна вісь - ширина, а min-width: 0 стоїть). */
		.main {
			min-height: 0;
			overflow: hidden;
		}

		.content {
			min-height: 0;
			overflow-y: auto;
			-webkit-overflow-scrolling: touch;
			/* інерційний скрол iOS + без прокидання скрола на сторінку */
			overscroll-behavior: contain;
			/* місце під нижню навігацію (+ safe-area айфонів) */
			padding: var(--space-4) max(var(--space-4), env(safe-area-inset-right))
				calc(var(--nav-total, 76px) + var(--space-4))
				max(var(--space-4), env(safe-area-inset-left));
		}
	}

	/* під час перетягування віджетів вимикаємо виділення тексту */
	:global(body.w-noselect),
	:global(body.w-noselect *) {
		user-select: none !important;
		-webkit-user-select: none !important;
	}
</style>
