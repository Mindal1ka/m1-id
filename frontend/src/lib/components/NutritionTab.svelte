<script lang="ts">
	/** Вкладка «Харчування» (FoodStep): меню з фото → кошик → дати
	 *  (календар у поповері) → замовлення. Плюс пароль, варіації, автозамовлення.
	 *  Стилістика — та сама, що в усьому додатку (glass, seg, switch із налаштувань). */
	import { onMount, onDestroy } from 'svelte';
	import { fade, slide, type TransitionConfig } from 'svelte/transition';
	import { backOut, cubicOut } from 'svelte/easing';
	import { AnimatedNumber, blurFade, motionOK, pop, pressable, stagger } from '$lib/motion';
	import { confirm, SmartImage } from '$lib/ui';
	import { Utensils, Save, Trash2, ChevronDown, KeyRound,
		ShoppingCart, X, Camera, Minus, Plus,
		ClipboardList, Repeat, CookingPot, Landmark } from '@lucide/svelte';
	import {
		api,
		ApiError,
		type FsConfig,
		type FsMenu,
		type FsOrder
	} from '$lib/api/client';
	import { nutritionImgUrl, releaseNutritionImgs } from '$lib/api/client';
	import { friendlyError } from '$lib/errors';
	import { fx } from '$lib/fx.svelte';
	import { focusTrap } from '$lib/actions/focusTrap';
	import { showToast } from '$lib/stores/toast.svelte';
	import NutritionCalendar from './NutritionCalendar.svelte';

	// uiTick із +page.svelte: збільшується кнопкою «Оновити» у topbar
	let { refreshTick = 0 }: { refreshTick?: number } = $props();

	const SUPPLIERS = [
		{ slug: 'dumpling', title: 'Галушки', icon: CookingPot },
		{ slug: 'provinces', title: 'Провінція', icon: Landmark }
	];

	let sub = $state<'menu' | 'orders' | 'auto'>('menu');
	let cfg = $state<FsConfig | null>(null);
	let menu = $state<FsMenu | null>(null);
	let menuSupplier = $state('dumpling');
	let menuBusy = $state(false);
	let err = $state('');

	// режим «створення варіації»: те саме меню, але замість календаря — «Створити»
	let varMode = $state(false);
	let varName = $state('');
	// модалка вибору часу автозамовлення
	let timePickerOpen = $state(false);
	let tpH = $state(8);
	let tpM = $state(0);

	// кошик
	let basket = $state<Record<number, number>>({});
	// дати
	let selectedDates = $state<string[]>([]);
	let ordered = $state<Record<string, { total: number; supplier: string }>>({});
	let cancelled = $state<Record<string, { total: number; supplier: string }>>({});
	let orders = $state<FsOrder[]>([]);

	// поповер календаря
	let calOpen = $state(false);
	// кошик згорнуто (клік по шапці кошика); розгортається при додаванні страви
	let cartCollapsed = $state(false);

	// пароль
	let pwdInput = $state('');
	let pwdOpen = $state(false);
	let pwdBusy = $state(false);

	// автозамовлення
	const dishById = $derived.by(() => {
		const m: Record<number, { title: string; price: number; image?: string | null }> = {};
		for (const d of menu?.dishes ?? []) m[d.id] = d;
		return m;
	});

	const cartCount = $derived(
		Object.values(basket).reduce((a, b) => a + b, 0));
	const total = $derived.by(() => {
		let t = 0;
		for (const [id, c] of Object.entries(basket)) {
			t += (dishById[Number(id)]?.price ?? 0) * c;
		}
		return t;
	});

	// свіже обчислення при кожному виклику (не кешувати при ініті:
	// вкладка може бути відкрита через 9:00)
	const afterNine = () => new Date().getHours() >= 9;

	async function loadMenu(slug: string, force = false): Promise<void> {
		menuBusy = true;
		err = '';
		try {
			menu = await api.nutritionMenu(slug, force);
			menuSupplier = slug;
		} catch (e) {
			err = 'Меню недоступне: FoodStep не відповідає або сайт змінився.';
			menu = null;
		} finally {
			menuBusy = false;
		}
	}

	// вже завантажені місяці журналу — щоб не спамити API на кожен клік
	let loadedMonths = new Set<string>();

	async function loadCalendar(month?: string): Promise<void> {
		const d = new Date();
		if (selectedDates.length) {
			d.setTime(new Date(selectedDates[0] + 'T00:00:00').getTime());
		}
		const key = month ?? `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
		if (loadedMonths.has(key)) return;
		try {
			const res = await api.nutritionCalendar(key);
			ordered = { ...ordered, ...res.ordered };
			cancelled = { ...cancelled, ...(res.cancelled ?? {}) };
			loadedMonths = new Set([...loadedMonths, key]);
		} catch { /* не критично */ }
	}

	async function loadOrders(): Promise<void> {
		try {
			orders = (await api.nutritionOrders(30)).orders;
		} catch (e) {
			note(friendlyError(e));
		}
	}

	async function loadConfig(): Promise<void> {
		try {
			cfg = await api.nutritionConfig();
		} catch { /* не критично */ }
	}

	onMount(() => {
		void loadConfig();
		void loadMenu('dumpling');
		void loadOrders();
		void loadCalendar();
	});

	/** Кнопка «Оновити» (topbar): force — мимо і localStorage-кеша,
	 *  і серверного TTL (бекенд пере-парсить foodstep.online), плюс
	 *  свіжі журнал/конфіг. */
	let lastTick = $state(0); // 0 = перший рендер, ще не було натискань
	$effect(() => {
		if (refreshTick === lastTick) return;
		lastTick = refreshTick;
		if (refreshTick <= 0) return;
		void hardRefresh();
	});

	async function hardRefresh(): Promise<void> {
		loadedMonths = new Set();
		ordered = {};
		cancelled = {};
		await Promise.all([
			loadMenu(menuSupplier, true),
			loadConfig(),
			loadOrders(),
			loadCalendar()
		]);
	}

	onDestroy(releaseNutritionImgs);

	function bump(id: number, delta: number): void {
		// авто-відкриття кошика лише у вкладці «Меню»: в автозаказі
		// додавання страв не повинно розгортати панель замовлення
		if (delta > 0 && sub === 'menu') cartCollapsed = false;
		const v = (basket[id] ?? 0) + delta;
		if (v <= 0) delete basket[id];
		else basket[id] = Math.min(v, 20);
		basket = { ...basket };
	}

	function toggleDate(iso: string): void {
		// клік по замовленій майбутній даті = пропозиція скасувати
		if (ordered[iso]) {
			const today = new Date();
			const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
			if (iso < todayIso) return;
			ask(`Скасувати замовлення на ${iso.slice(8, 10)}.${iso.slice(5, 7)}?`,
				() => void cancelOrder(iso));
			return;
		}
		if (selectedDates.includes(iso))
			selectedDates = selectedDates.filter((d) => d !== iso);
		else selectedDates = [...selectedDates, iso].sort();
		// журнал вантажимо саме для місяця, який переглядають у календарі
		void loadCalendar(iso.slice(0, 7));
	}

	async function cancelOrder(iso: string): Promise<void> {
		try {
			const res = await api.nutritionCancelOrder(iso);
			showToast(res.note || 'Замовлення скасовано');
			loadedMonths = new Set([...loadedMonths].filter((m) => m !== iso.slice(0, 7)));
			await Promise.all([loadOrders(), loadCalendar()]);
		} catch (e) {
			note(friendlyError(e));
		}
	}

	function hasTodaySelected(): boolean {
		const t = new Date();
		const iso = `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`;
		return selectedDates.includes(iso);
	}

	let submitting = $state(false);

	async function submitOrder(): Promise<void> {
		if (!selectedDates.length || !cartCount) return;
		if (afterNine() && hasTodaySelected()) {
			ask('Після 9:00 замовлення на сьогодні може не виконатися (дедлайн пройшов). Все одно продовжити?',
				() => void doSubmit());
			return;
		}
		await doSubmit();
	}

	async function doSubmit(): Promise<void> {
		submitting = true;
		err = '';
		try {
			const items = Object.entries(basket).map(([id, count]) => ({
				id: Number(id),
				count
			}));
			const res = await api.nutritionOrder({
				supplier: menuSupplier,
				dates: selectedDates,
				items
			});
			const okN = res.results.filter((r) => r.ok).length;
			// кожен результат — окремий тост у верхньому барі
			for (const r of res.results) {
				const d = r.date.slice(8, 10) + '.' + r.date.slice(5, 7);
				if (r.status === 'already') showToast(`${d} — уже замовлено`);
				else if (r.ok) showToast(`${d} — замовлено, ${r.total ?? 0} грн`);
				else showToast(`${d} — не замовлено: ${r.message || r.status}`);
			}
			if (okN > 0) fx.celebrate('order');
			selectedDates = [];
			basket = {};
			calOpen = false;
			cartCollapsed = false;
			await Promise.all([loadOrders(), loadCalendar()]);
		} catch (e) {
			if (e instanceof ApiError && e.code === 'foodstep_password_not_set') {
				err = 'Спершу задай пароль FoodStep (значок 🔑 у шапці).';
				pwdOpen = true;
			} else {
				note(friendlyError(e));
			}
		} finally {
			submitting = false;
		}
	}

	async function savePassword(): Promise<void> {
		if (pwdInput.length < 4) {
			note('Пароль — мінімум 4 символи.');
			return;
		}
		pwdBusy = true;
		try {
			await api.nutritionPassword(pwdInput);
			pwdInput = '';
			pwdOpen = false;
			note('Пароль збережено (шифрується на сервері).');
			cfg = await api.nutritionConfig();
		} catch (e) {
			note(friendlyError(e));
		} finally {
			pwdBusy = false;
		}
	}

	/** Підтвердження через спільний confirm(): після згоди виконує дію. */
	function ask(msg: string, act: () => void): void {
		void confirm({ title: 'Підтвердження', message: msg, confirmText: 'Продовжити' }).then((ok) => {
			if (ok) act();
		});
	}

	/** Тихе збереження конфіга — без повідомлень (для перемикачів). */
	async function saveAutoQuiet(): Promise<void> {
		if (!cfg) return;
		try {
			await api.nutritionSaveConfig({
				enabled: cfg.auto.enabled,
				mode: cfg.auto.mode,
				fixed_variation_id: cfg.auto.fixed_variation_id,
				order_time: cfg.auto.order_time,
				notify_minutes: cfg.auto.notify_minutes,
				allow_weekends: cfg.auto.allow_weekends,
				supplier: cfg.supplier
			});
		} catch (e) {
			err = friendlyError(e);
		}
	}

	let varBusy = $state(false);
	async function saveVariation(): Promise<void> {
		if (varBusy) return;
		if (!varName.trim() || !cartCount) {
			note('Обери страви і дай варіації назву.');
			return;
		}
		varBusy = true;
		try {
			await api.nutritionAddVariation({
				name: varName.trim(),
				supplier: menuSupplier,
				items: Object.entries(basket).map(([id, count]) => ({
					id: Number(id),
					count
				}))
			});
			varName = '';
			note('Варіацію збережено.');
			basket = {};
			varMode = false;
			sub = 'auto';
			cfg = await api.nutritionConfig();
		} catch (e) {
			note(friendlyError(e));
		} finally {
			varBusy = false;
		}
	}

	async function delVariation(id: number): Promise<void> {
		try {
			await api.nutritionDelVariation(id);
			cfg = await api.nutritionConfig();
		} catch (e) {
			note(friendlyError(e));
		}
	}

	/** Зміна постачальника у вкладці «Меню»: ЛИШЕ перемикає меню,
	 *  нічого не пише в БД (POST-запитів на кожен клік нема).
	 *  Глобальний постачальник для автозамовлення зберігається
	 *  окремо — у вкладці «Автозамовлення». */
	async function pickSupplier(slug: string): Promise<void> {
		if (menuSupplier === slug && menu) return;
		// страви різних постачальників не змішувати: id збігаються неправильно.
		// Перед зміною попереджаємо, що кошик буде очищено.
		if (cartCount > 0) {
			ask('У кошику страви іншого постачальника. Після зміни кошик буде очищено. Продовжити?',
				() => {
					basket = {};
					void loadMenu(slug);
				});
			return;
		}
		await loadMenu(slug);
	}

	/** Повідомлення — у верхній бар (тост на 3с), не в тіло вкладки. */
	function note(msg: string): void {
		showToast(msg);
	}

	/** Перемикання підвкладок: з «Меню» виходимо з кошиком —
	 *  попереджаємо і скидаємо кошик + дати. */
	function switchSub(next: 'menu' | 'orders' | 'auto'): void {
		if (sub === next) return;
		if (sub === 'menu' && (cartCount > 0 || selectedDates.length > 0)) {
			ask('При виході з «Меню» кошик і вибрані дати буде скинуто. Продовжити?',
				() => {
					basket = {};
					selectedDates = [];
					varMode = false;
					calOpen = false;
					cartCollapsed = false;
					sub = next;
				});
			return;
		}
		sub = next;
	}

	/** «Додати варіацію»: ті саме меню-картки, але внизу — «Створити». */
	function startVariation(): void {
		basket = {};
		selectedDates = [];
		varMode = true;
		sub = 'menu';
		// кошик за замовчуванням ЗГОРНУТИЙ — розгорнеться при додаванні страви
		cartCollapsed = true;
	}

	function datesLabel(): string {
		return selectedDates
			.map((d) => d.slice(8, 10) + '.' + d.slice(5, 7))
			.join(', ');
	}

	/** Кошик-бар: пружинно виїжджає знизу (transform зберігає центрування). */
	function cartUp(node: Element, { leave = false }: { leave?: boolean } = {}): TransitionConfig {
		if (!motionOK()) return { duration: 0 };
		return {
			duration: leave ? 220 : 480,
			easing: leave ? cubicOut : backOut,
			css: (t, u) =>
				`opacity:${Math.min(1, t * 2)};transform:translateX(-50%) translateY(${u * 120}%)`
		};
	}

	/** Пульс елемента при монтуванні (разом із {#key} — при кожній зміні значення). */
	function popIn(node: HTMLElement, scale = 1.25): void {
		pop(node, scale);
	}

	/** Портал: виносимо кошик у <body>, щоб position:fixed працював
	 *  відносно viewport — .glass-предок з backdrop-filter інакше
	 *  робить фіксований елемент «застряглим» всередині картки. */
	function portal(node: HTMLElement): { destroy(): void } {
		document.body.appendChild(node);
		return {
			destroy() {
				node.remove();
			}
		};
	}
</script>

<div class="toolbar">
	<h2 class="inline"><Utensils size={18} /> Харчування</h2>
	<div class="flex-sp"></div>
	<button class="icon-btn" title="Пароль FoodStep"
		class:warn-ring={cfg && !cfg.password_set}
		onclick={() => (pwdOpen = true)}>
		<KeyRound size={16} />
	</button>
	<div class="seg subseg">
		<button class:on={sub === 'menu'} onclick={() => switchSub('menu')}>
			<Utensils size={14} /> Меню
		</button>
		<button class:on={sub === 'orders'} onclick={() => switchSub('orders')}>
			<ClipboardList size={14} /> Замовлення
		</button>
		<button class:on={sub === 'auto'} onclick={() => switchSub('auto')}>
			<Repeat size={14} /> Автозамовлення
		</button>
	</div>
</div>

{#if pwdOpen}
	<div class="overlay" use:portal
		transition:fade={{ duration: 150 }}
		onclick={(e) => e.target === e.currentTarget && (pwdOpen = false)}
		role="presentation">
		<div class="pwd-modal glass" transition:fade={{ duration: 150 }}
			role="dialog" aria-modal="true" aria-label="Пароль FoodStep">
			<header>
				<h2>Пароль FoodStep</h2>
				<button class="x" onclick={() => (pwdOpen = false)} aria-label="Закрити">
					<X size={18} strokeWidth={2} />
				</button>
			</header>
			<label class="field">
				<span>Пароль від foodstep.online</span>
				<input type="password" bind:value={pwdInput}
					onkeydown={(e) => e.key === 'Enter' && savePassword()} />
			</label>
			{#if cfg?.password_set}
				<p class="note ok">Зараз: задано ✅</p>
			{:else}
				<p class="note err">Зараз: не задано ❌</p>
			{/if}
			<p class="small dim">Шифрується на сервері, ніде не показується. Потрібен і на сайті, і в Telegram-боті.</p>
			<div class="pwd-actions">
				<button class="ghost-btn" onclick={() => (pwdOpen = false)}>Скасувати</button>
				<button class="primary-btn" disabled={pwdBusy} onclick={savePassword}>
					<KeyRound size={15} /> Зберегти
				</button>
			</div>
		</div>
	</div>
{/if}

{#if err}<p class="msg err">{err}</p>{/if}

{#if sub === 'menu'}
	<div in:blurFade={{ duration: 300, amount: 0 }}>
		<!-- постачальник -->
		<div class="seg wide suppliers">
			{#each SUPPLIERS as s (s.slug)}
				<button class:on={menuSupplier === s.slug}
					onclick={() => pickSupplier(s.slug)}>
					<s.icon size={14} /> {s.title}
				</button>
			{/each}
		</div>

		<!-- меню з фото -->
		{#key menuBusy}
		<div in:blurFade={{ duration: 340, amount: 0, y: 6 }}>
		{#if menuBusy}
			<div class="fs-grid">
				{#each Array(8) as _, i (i)}
					<div class="fs-card skel"></div>
				{/each}
			</div>
		{:else if menu}
			{#each menu.categories as cat (cat.name)}
				{#if cat.name}<h3 class="sec-title">{cat.name}</h3>{/if}
				<div class="fs-grid" use:stagger={{ step: 30, max: 12, scale: true }}>
					{#each cat.dishes as d (d.id)}
						<div role="button" tabindex="0"
							class="fs-card"
							use:pressable={{ scale: 0.97 }}
							class:picked={!!basket[d.id]}
							onclick={() => bump(d.id, 1)}
							onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && bump(d.id, 1)}>
							<div class="fs-photo">
								{#if d.image}
									<SmartImage src={d.image} alt={d.title} loader={nutritionImgUrl} fit="cover" />
								{:else}
									<span class="fs-noimg"><Camera size={22} /></span>
								{/if}
								{#if d.weight}
									<span class="fs-weight">{d.weight}</span>
								{/if}
							</div>
							<div class="fs-card-body">
								<span class="fs-title">{d.title}</span>
								<span class="fs-price">{d.price} грн</span>
							</div>
							{#if basket[d.id]}
								<!-- компактний степер к-сті прямо на картці -->
								<div class="fs-qty"
									onclick={(e) => e.stopPropagation()}
									onkeydown={(e) => e.stopPropagation()}>
									<button title="менше" onclick={(e) => { e.stopPropagation(); bump(d.id, -1); }}>
										<Minus size={13} />
									</button>
									{#key basket[d.id]}<b use:popIn>{basket[d.id]}</b>{/key}
									<button title="більше" onclick={(e) => { e.stopPropagation(); bump(d.id, 1); }}>
										<Plus size={13} />
									</button>
								</div>
							{/if}
						</div>
					{/each}
				</div>
			{/each}
		{/if}
		</div>
		{/key}
	</div>
{/if}

<!-- кошик: портал у body, приклеєний до низу екрана.
     На мобільному — над нижньою панеллю навігації, щоб її не перекривати. -->
{#if sub === 'menu' && cartCount > 0}
	<div class="cartbar" use:portal in:cartUp out:cartUp={{ leave: true }}>
		<button class="cartbar-head"
			onclick={() => (varMode ? (cartCollapsed = !cartCollapsed) : (calOpen = !calOpen))}>
			{#key cartCount}<span class="cart-ic" use:popIn={1.3}><ShoppingCart size={17} /></span>{/key}
			<span><b><AnimatedNumber value={cartCount} duration={450} /></b> шт · <b><AnimatedNumber value={total} duration={450} /></b> грн</span>
			<span class="cartbar-dates">
				{varMode ? '✎ нова варіація' : selectedDates.length ? `📅 ${datesLabel()}` : '📅 обери дати'}
			</span>
			<span class="flex-sp"></span>
			<span class="chev" class:flip={varMode ? !cartCollapsed : calOpen}><ChevronDown size={16} /></span>
		</button>

		{#if !cartCollapsed && (calOpen || varMode)}
			<div class="cartbar-body" transition:slide={{ duration: 150 }}>
				{#if varMode}
					<!-- режим створення варіації: тільки список + назва -->
					<div class="cart-items">
						{#each Object.entries(basket) as [id, c] (id)}
							<div class="cart-row">
								{#if dishById[Number(id)]?.image ?? false}
									<span class="cart-thumb"><SmartImage src={dishById[Number(id)]?.image} loader={nutritionImgUrl} fit="cover" radius="8px" iconSize={14} /></span>
								{:else}
									<span class="cart-thumb ph"><Camera size={14} /></span>
								{/if}
								<span class="cart-title">{dishById[Number(id)]?.title ?? '#' + id}</span>
								<span class="cart-price">{dishById[Number(id)]?.price ?? 0} грн</span>
								<div class="cart-ctl">
									<button title="менше" onclick={() => bump(Number(id), -1)}><Minus size={13} /></button>
									{#key c}<b use:popIn>{c}</b>{/key}
									<button title="більше" onclick={() => bump(Number(id), 1)}><Plus size={13} /></button>
									<button class="x" title="видалити" onclick={() => bump(Number(id), -c)}>
										<X size={12} />
									</button>
								</div>
							</div>
						{/each}
					</div>
					<input class="var-name" placeholder='назва варіації («Стандарт»)'
						bind:value={varName} maxlength="64" />
					<button class="primary-btn big" disabled={submitting || !cartCount}
						onclick={saveVariation}>
						<Save size={15} /> Створити
					</button>
					<button class="ghost-btn" onclick={() => { varMode = false; basket = {}; sub = 'auto'; }}>
						Скасувати
					</button>
				{:else}
				<div class="cart-items">
					{#each Object.entries(basket) as [id, c] (id)}
						<div class="cart-row">
							{#if dishById[Number(id)]?.image ?? false}
								<span class="cart-thumb"><SmartImage src={dishById[Number(id)]?.image} loader={nutritionImgUrl} fit="cover" radius="8px" iconSize={14} /></span>
							{:else}
								<span class="cart-thumb ph"><Camera size={14} /></span>
							{/if}
							<span class="cart-title">{dishById[Number(id)]?.title ?? '#' + id}</span>
							<span class="cart-price">{dishById[Number(id)]?.price ?? 0} грн</span>
							<div class="cart-ctl">
								<button title="менше" onclick={() => bump(Number(id), -1)}><Minus size={13} /></button>
								{#key c}<b use:popIn>{c}</b>{/key}
								<button title="більше" onclick={() => bump(Number(id), 1)}><Plus size={13} /></button>
								<button class="x" title="видалити" onclick={() => bump(Number(id), -c)}>
									<X size={12} />
								</button>
							</div>
						</div>
					{/each}
				</div>

				<div class="cal-wrap">
					<NutritionCalendar
						{selectedDates}
						{ordered}
						{cancelled}
						allow_weekends={cfg?.auto.allow_weekends ?? false}
						onToggle={toggleDate}
					/>
				</div>

				<button class="primary-btn big"
					disabled={submitting || !selectedDates.length}
					onclick={submitOrder}>
					{submitting
						? 'Замовляю…'
						: `Замовити на ${selectedDates.length} ${selectedDates.length === 1 ? 'дату' : 'дат'} — ${total} грн`}
				</button>
				{#if !selectedDates.length}
					<p class="small center dim">Обери дати в календарі ⬆️</p>
				{/if}
				{/if}
			</div>
		{/if}
	</div>
{/if}

{#if sub === 'orders'}
	<div in:blurFade={{ duration: 300, amount: 0 }} use:stagger={{ selector: '.fs-o', step: 35, max: 12 }}>
		{#if orders.length === 0}
			<p class="small dim">Ще немає замовлень.</p>
		{:else}
			{#each orders as o, oi (`${o.date}|${o.supplier}|${o.created_at ?? ''}|${oi}`)}
				<div class="fs-o">
					<span class="fs-o-date">{o.date.slice(8, 10)}.{o.date.slice(5, 7)}</span>
					<span class={o.status === 'ok' ? 'ok' : 'err'}>
						{o.status === 'ok' ? '✅' : '❌'} {o.supplier_title}
					</span>
					<span class="small grow dim">
						{o.items.map((i) => `${(i as { title?: string }).title ?? '#' + i.id}×${i.count}`).join(', ')}
					</span>
					<b>{o.total} грн</b>
					<span class="pill">{o.source === 'auto' ? '🤖 авто' : '✍️'}</span>
				</div>
			{/each}
		{/if}
	</div>
{/if}

{#if sub === 'auto' && cfg}
	<div class="fs-auto" in:blurFade={{ duration: 300, amount: 0 }}
		use:stagger={{ selector: ':scope > .sect', step: 70, y: 14, max: 12 }}>
		<!-- ── Автозамовлення ── -->
		<section class="glass sect">
			<div class="row">
				<h4>Автозамовлення щодня</h4>
				<label class="switch">
					<input type="checkbox" checked={cfg.auto.enabled}
						onchange={(e) => {
							cfg!.auto.enabled = e.currentTarget.checked;
							void saveAutoQuiet();
						}} />
					<i></i>
				</label>
			</div>
			<p class="dim small off-note">
				Бот сам замовить обрану варіацію на сьогодні, до дедлайну 9:00.
				За N хвилин до замовлення прийде повідомлення в Telegram — можна змінити або пропустити день.
			</p>

			{#if cfg.auto.enabled}
				<div class="field-grid" transition:slide={{ duration: 300, easing: cubicOut }}>
					<label class="field">
						<span>Час замовлення</span>
						<button type="button" class="time-btn"
							onclick={() => {
								const [h, m] = (cfg!.auto.order_time || '08:00').split(':');
								const H = Number(h);
								tpH = H > 8 ? 8 : H;
								tpM = (H > 8 || (H === 8 && Number(m) > 0)) ? 0 : Number(m);
								timePickerOpen = true;
							}}>
							⏰ {cfg.auto.order_time}
						</button>
					</label>
					<label class="field">
						<span>Попередження в TG за (хв)</span>
						<input type="number" min="0" max="720" step="15"
							value={cfg.auto.notify_minutes}
							onchange={(e) => {
								const n = e.currentTarget.valueAsNumber;
								cfg!.auto.notify_minutes = Number.isFinite(n)
									? Math.min(720, Math.max(0, n))
									: 60;
								void saveAutoQuiet();
							}} />
					</label>
				</div>
			{/if}
		</section>

		<!-- ── Що замовляти ── -->
		<section class="glass sect">
			<h4>Що замовляти</h4>

			<span class="lbl dim small">Режим вибору</span>
			<div class="seg">
				<button class:on={cfg.auto.mode === 'random'}
					onclick={() => {
						cfg!.auto.mode = 'random';
						void saveAutoQuiet();
					}}>Рандом із варіацій</button>
				<button class:on={cfg.auto.mode === 'fixed'}
					onclick={() => {
						cfg!.auto.mode = 'fixed';
						void saveAutoQuiet();
					}}>Фіксована</button>
			</div>

			{#if cfg.auto.mode === 'fixed'}
				<label class="field" transition:slide={{ duration: 260, easing: cubicOut }}>
					<span>Варіація за замовчуванням</span>
					<select value={cfg.auto.fixed_variation_id}
						onchange={(e) => {
							cfg!.auto.fixed_variation_id = Number(e.currentTarget.value);
							void saveAutoQuiet();
						}}>
						{#each cfg.variations as v (v.id)}
							<option value={v.id}>{v.name}</option>
						{/each}
					</select>
				</label>
			{/if}
		</section>

		<!-- ── Варіації ── -->
		<section class="glass sect">
			<div class="row">
				<h4>Варіації ({cfg.variations.length})</h4>
			</div>
			{#each cfg.variations as v (v.id)}
				<div class="var-row">
					<div class="var-info">
						<b>{v.name}</b>
						<span class="small dim">
							{SUPPLIERS.find((s) => s.slug === (v.supplier || cfg?.supplier))?.title ?? v.supplier}
							· {v.items.map((i) => `${dishById[i.id]?.title ?? '#' + i.id}×${i.count}`).join(', ')}
						</span>
					</div>
					<button class="icon-btn" title="видалити" onclick={() => delVariation(v.id)}>
						<Trash2 size={14} />
					</button>
				</div>
			{:else}
				<p class="small dim off-note">Ще немає варіацій. Створи першу кнопкою «Додати» — відкриється меню, обери страви і натисни «Створити».</p>
			{/each}
			<button class="primary-btn" onclick={startVariation}>
				<Plus size={15} /> Додати
			</button>
		</section>
	</div>
{/if}

{#if timePickerOpen && cfg}
	<div class="tp-ovl" role="presentation" use:portal
		transition:fade={{ duration: 150 }}
		onclick={(e) => e.target === e.currentTarget && (timePickerOpen = false)}>
		<div class="tp glass" role="dialog" aria-modal="true" aria-label="Час замовлення"
			tabindex="-1" use:focusTrap
			onkeydown={(e) => e.key === 'Escape' && (timePickerOpen = false)}>
			<h4>Час замовлення</h4>
			<p class="small dim" style="margin:0">Не пізніше 8:00 — дедлайн FoodStep 9:00.</p>
			<div class="tp-cols">
				<div class="tp-col">
					{#each Array(24) as _, h (h)}
						<button class:sel={tpH === h}
							disabled={h > 8}
							class:dis={h > 8}
							onclick={() => (tpH = h)}>{String(h).padStart(2, '0')}</button>
					{/each}
				</div>
				<div class="tp-col">
					{#each Array(12) as _, mi (mi)}
						{@const m = mi * 5}
						<button class:sel={tpM === m}
							disabled={tpH === 8 && m > 0}
							class:dis={tpH === 8 && m > 0}
							onclick={() => (tpM = m)}>{String(m).padStart(2, '0')}</button>
					{/each}
				</div>
			</div>
			<div class="tp-actions">
				<button class="ghost-btn" onclick={() => (timePickerOpen = false)}>Скасувати</button>
				<button class="primary-btn"
					onclick={() => {
						// захист: не пізніше 8:00
						if (tpH > 8 || (tpH === 8 && tpM > 0)) { tpH = 8; tpM = 0; }
						cfg!.auto.order_time =
							`${String(tpH).padStart(2, '0')}:${String(tpM).padStart(2, '0')}`;
						timePickerOpen = false;
						void saveAutoQuiet();
					}}>
					Готово
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
	.flex-sp { flex: 1; }
	.inline { display: inline-flex; align-items: center; gap: 8px; margin: 0; font-family: var(--font-display); }
	.grow { flex: 1; min-width: 140px; }
	.center { text-align: center; }
	.dim { color: var(--text-dim); }
	.small { font-size: 12px; margin: 4px 0; }

	/* --- сегменти: як у налаштуваннях додатку --- */
	.seg { display: flex; gap: 8px; }
	.seg button {
		flex: 1; height: 36px; white-space: nowrap;
		font: inherit; font-size: 13px; font-weight: 600;
		color: var(--text-dim);
		background: var(--glass-bg);
		border: 1.5px solid var(--glass-border);
		border-radius: var(--radius-md);
		cursor: pointer;
		transition: border-color .2s ease, color .2s ease, background .2s ease;
	}
	.seg button.on {
		color: var(--accent);
		border-color: var(--accent);
		background: var(--accent-soft);
	}
	.seg.wide { margin: 0 0 6px; }

	.icon-btn {
		width: 32px; height: 32px;
		display: inline-grid; place-items: center;
		background: var(--glass-bg); color: var(--text-dim);
		border: 1px solid var(--glass-border);
		border-radius: 10px; cursor: pointer; font: inherit;
	}
	.icon-btn.warn-ring { border-color: #e6a23c; color: #e6a23c; }

	.msg { padding: 8px 12px; border-radius: var(--radius-md); white-space: pre-wrap; font: inherit; }
	.msg.err { background: rgba(255, 80, 80, .12); color: #ff6b6b; }

	.sec-title {
		margin: 16px 0 8px; font-size: 12px; font-weight: 700;
		text-transform: uppercase; letter-spacing: .09em;
		color: var(--text-faint);
	}

	/* --- пароль: модалка (патерн ProfileModal) --- */
	.overlay {
		position: fixed; inset: 0; z-index: 90;
		background: rgba(5, 7, 11, 0.6);
		-webkit-backdrop-filter: blur(calc(6px + 0px));
		backdrop-filter: blur(6px);
		display: grid; place-items: center; padding: 18px;
	}
	:global(html[data-perf='lite']) .overlay {
		-webkit-backdrop-filter: none; backdrop-filter: none;
		background: rgba(5, 7, 11, 0.8);
	}
	.pwd-modal {
		width: min(380px, 100%);
		padding: 22px;
		border-radius: var(--radius-lg);
		display: flex; flex-direction: column; gap: 12px;
		position: relative;
	}
	.pwd-modal header {
		display: flex; align-items: center; justify-content: space-between; gap: 12px;
		padding-right: 8px;
	}
	.pwd-modal h2 {
		margin: 0; font-family: var(--font-display); font-size: 18px;
	}
	.pwd-modal .x {
		background: none; border: none; color: var(--text-faint);
		cursor: pointer; display: grid; place-items: center;
		width: 30px; height: 30px; border-radius: 8px; padding: 0;
		transition: background .15s ease, color .15s ease;
	}
	.pwd-modal .x:hover { background: var(--glass-bg); color: var(--text); }
	.pwd-modal .note {
		margin: 0; font-size: 12px;
		padding: 7px 10px; border-radius: var(--radius-md);
	}
	.pwd-modal .note.ok { background: rgba(52, 199, 89, .12); color: #34c759; }
	.pwd-modal .note.err { background: rgba(255, 80, 80, .12); color: #ff6b6b; }
	.pwd-actions { display: flex; justify-content: flex-end; gap: 8px; }
	.pwd-actions .ghost-btn { margin-top: 0; }
	.primary-btn {
		display: inline-flex; align-items: center; justify-content: center; gap: 7px;
		height: 38px; padding: 0 16px;
		font: inherit; font-size: 13px; font-weight: 700;
		color: #fff; background: var(--accent-strong);
		border: none; border-radius: var(--radius-md); cursor: pointer;
		box-shadow: 0 3px 14px color-mix(in srgb, var(--accent) 45%, transparent);
		transition: transform .15s var(--ease-spring, ease), filter .2s ease;
	}
	.primary-btn:hover { transform: translateY(-1px); filter: brightness(1.07); }
	.primary-btn:disabled { opacity: .45; cursor: default; transform: none; box-shadow: none; }
	.primary-btn.big { width: 100%; height: 44px; font-size: 15px; }

	/* --- картки меню --- */
	.fs-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
		gap: 12px;
	}
	.fs-card {
		position: relative;
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-lg);
		overflow: hidden;
		background: var(--glass-bg); color: var(--text); font: inherit;
		cursor: pointer; text-align: left;
		padding: 0;
		content-visibility: auto;
		contain-intrinsic-size: auto 200px;
		transition: transform .15s var(--ease-spring, ease), border-color .15s;
	}
	.fs-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-card, 0 6px 16px rgba(0,0,0,.18)); }
	.fs-card.picked { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent), 0 6px 16px color-mix(in srgb, var(--accent) 25%, transparent); }
	.fs-photo {
		position: relative; aspect-ratio: 4/3;
		background: linear-gradient(135deg, rgba(128,128,128,.15), rgba(128,128,128,.05));
		display: flex; align-items: center; justify-content: center;
	}
	.fs-noimg { opacity: .3; color: var(--text-dim); }
	.fs-weight {
		position: absolute; bottom: 6px; left: 6px;
		background: rgba(0,0,0,.55); color: #fff;
		font-size: 10px; padding: 2px 6px; border-radius: 6px;
	}
	.fs-qty {
		position: absolute; bottom: 6px; right: 6px;
		display: inline-flex; align-items: center; gap: 2px;
		background: rgba(0, 0, 0, .6);
		-webkit-backdrop-filter: blur(calc(6px + 0px));
		backdrop-filter: blur(6px);
		border-radius: 999px; padding: 2px;
	}
	:global(html[data-perf='lite']) .fs-qty {
		-webkit-backdrop-filter: none; backdrop-filter: none;
		background: rgba(0, 0, 0, .78);
	}
	.fs-qty button {
		width: 22px; height: 22px;
		display: inline-grid; place-items: center;
		border: none; border-radius: 50%;
		background: transparent; color: #fff;
		cursor: pointer; font: inherit;
	}
	.fs-qty button:hover { background: rgba(255, 255, 255, .2); }
	.fs-qty b {
		min-width: 16px; text-align: center;
		font-size: 12px; color: #fff;
	}
	.fs-card-body { display: flex; flex-direction: column; gap: 2px; padding: 8px 10px 10px; }
	.fs-title { font-weight: 600; font-size: 13px; line-height: 1.25; }
	.fs-price { font-size: 13px; color: var(--text-dim); }
	.fs-card.skel { height: 190px; opacity: .35; animation: pulse 1.4s infinite; }
	@keyframes pulse { 50% { opacity: .15; } }

	/* ── кошик-бар: ПРИКЛЕЄНИЙ ДО НИЗУ ЕКРАНА ──
	   Портал у <body> (use:portal) — інакше backdrop-filter предка
	   робить fixed всередині картки. На мобільному підіймаємось над
	   нижньою панеллю навігації (bottombar ≈ 78px + safe-area). */
	.cartbar {
		position: fixed;
		left: 50%; transform: translateX(-50%);
		bottom: 16px;
		width: min(680px, calc(100vw - 24px));
		z-index: 45;
		/* --bg-a95 ніде не оголошено → завжди спрацьовував ТЕМНИЙ фолбек, навіть
		   у світлій темі; тепер фон береться від поточного --bg */
		background: color-mix(in srgb, var(--bg) 95%, transparent);
		-webkit-backdrop-filter: blur(calc(14px + 0px));
		backdrop-filter: blur(14px);
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-lg);
		box-shadow: 0 10px 34px rgba(0,0,0,.4);
		overflow: hidden;
	}
	:global(html[data-perf='lite']) .cartbar {
		-webkit-backdrop-filter: none; backdrop-filter: none;
		background: var(--bg);
	}
	:global(html[data-scheme='light']) .cartbar {
		box-shadow: 0 10px 30px rgba(20, 24, 40, .16);
	}
	@media (max-width: 900px) {
		.cartbar {
			bottom: calc(var(--nav-total, 78px) + 8px);
			width: calc(100vw - 20px);
		}
	}
	.cartbar-head {
		display: flex; align-items: center; gap: 10px;
		width: 100%; padding: 12px 16px;
		background: transparent; border: none; color: var(--text);
		cursor: pointer; font: inherit; text-align: left;
	}
	.cartbar-head:hover { background: var(--glass-bg-hover); }
	.cartbar-dates { font-size: 13px; color: var(--text-dim); }
	.chev { transition: transform .2s; display: inline-flex; color: var(--text-dim); }
	.chev.flip { transform: rotate(180deg); }
	.cartbar-body { padding: 0 16px 14px; max-height: min(62vh, 480px); overflow-y: auto; }
	.cart-items { margin-bottom: 10px; }
	.cart-row { display: flex; align-items: center; gap: 8px; padding: 5px 0; }
	.cart-thumb { width: 36px; height: 36px; border-radius: 8px; overflow: hidden; flex: none; }
	.cart-thumb.ph {
		display: inline-grid; place-items: center;
		background: var(--glass-bg-hover); color: var(--text-faint);
	}
	.cart-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }
	.cart-price { font-size: 12px; color: var(--text-dim); white-space: nowrap; }
	.cart-ctl { display: flex; gap: 5px; align-items: center; }
	.cart-ctl button {
		width: 26px; height: 26px; border-radius: 8px;
		border: 1px solid var(--glass-border);
		background: var(--glass-bg); color: var(--text-dim);
		cursor: pointer; font: inherit;
		display: inline-grid; place-items: center;
	}
	.cart-ctl button:hover { color: var(--text); border-color: var(--accent); }
	.cart-ctl b { min-width: 16px; text-align: center; }
	.cal-wrap {
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-md); padding: 10px; margin-bottom: 10px;
	}

	/* --- замовлення --- */
	.fs-o {
		display: flex; gap: 8px; align-items: center; padding: 8px 0; flex-wrap: wrap;
		border-bottom: 1px solid var(--glass-border);
	}
	.fs-o-date { font-weight: 700; min-width: 46px; }
	.fs-o .ok { color: #34c759; }
	.fs-o .err { color: #ff6b6b; }
	.pill {
		font-size: 11px; padding: 2px 8px; border-radius: 999px;
		border: 1px solid var(--glass-border); color: var(--text-dim);
	}

	/* ── автозамовлення: секції в стилі модалки налаштувань ── */
	.fs-auto { display: flex; flex-direction: column; gap: 12px; }
	.sect {
		display: flex; flex-direction: column; gap: 10px;
		padding: 14px 16px;
		border-radius: var(--radius-lg);
	}
	.sect h4 {
		margin: 0; font-size: 12px; font-weight: 700;
		text-transform: uppercase; letter-spacing: .09em;
		color: var(--text-faint);
	}
	.row { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
	.lbl { margin-top: 2px; }
	.off-note { margin: 0; }
	.field-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }
	.field { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--text-dim); }
	.field input, .field select {
		background: var(--glass-bg); color: var(--text); font: inherit;
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-md); padding: 9px 11px; outline: none;
	}
	.field input:focus, .field select:focus { border-color: var(--accent); }

	/* перемикач — такий самий, як у налаштуваннях додатку */
	.switch { position: relative; display: inline-block; width: 44px; height: 25px; cursor: pointer; flex: none; }
	.switch input { opacity: 0; width: 0; height: 0; }
	.switch i {
		position: absolute; inset: 0;
		background: var(--glass-bg-hover);
		border: 1px solid var(--glass-border);
		border-radius: 999px;
		transition: background .2s ease;
	}
	.switch i::before {
		content: '';
		position: absolute; top: 2px; left: 2px;
		width: 19px; height: 19px; border-radius: 50%;
		background: var(--surface-2);
		box-shadow: 0 1px 4px rgba(0,0,0,.3);
		transition: transform .18s var(--ease-spring, ease), background .2s ease;
	}
	.switch input:checked + i { background: var(--accent-soft); }
	.switch input:checked + i::before { transform: translateX(19px); background: var(--accent); }

	.var-row {
		display: flex; align-items: center; gap: 10px;
		padding: 8px 10px;
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-md);
	}
	.var-info { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }

	/* ── підперемикач Меню/Замовлення/Автозамовлення: цільний
	   сегмент-контрол (єдина пігулка, активна частина — акцент) ── */
	.subseg {
		display: inline-flex; gap: 2px;
		padding: 3px;
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-lg);
		margin: 0 0 12px;
	}
	.subseg button {
		flex: 1; min-width: 0; height: 34px;
		display: inline-flex; align-items: center; justify-content: center; gap: 5px;
		padding: 0 4px;
		font: inherit; font-size: 12.5px; font-weight: 600;
		color: var(--text-dim);
		background: transparent; border: none; border-radius: var(--radius-md);
		cursor: pointer;
		transition: background .18s ease, color .18s ease;
	}
	.subseg button:hover { color: var(--text); }
	.subseg button.on {
		color: #fff; background: var(--accent-strong);
		box-shadow: 0 2px 10px color-mix(in srgb, var(--accent) 40%, transparent);
	}
	/* на вузьких екранах пігулка бере весь рядок — текст гарантовано вміщається */
	@media (max-width: 700px) {
		.subseg { width: 100%; }
	}

	.ghost-btn {
		height: 38px; padding: 0 14px; margin-top: 6px;
		font: inherit; font-size: 13px; font-weight: 600;
		color: var(--text-dim);
		background: transparent; border: none; cursor: pointer;
	}
	.ghost-btn:hover { color: var(--text); }

	/* режим варіації у кошику */
	.var-name {
		width: 100%; margin-bottom: 8px;
		background: var(--glass-bg); color: var(--text); font: inherit;
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-md); padding: 9px 12px; outline: none;
	}
	.var-name:focus { border-color: var(--accent); }

	/* кнопка-поле часу (замість <input type=time>) */
	.time-btn {
		width: 100%; text-align: left;
		background: var(--glass-bg); color: var(--text); font: inherit;
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-md); padding: 9px 11px; cursor: pointer;
	}
	.time-btn:hover { border-color: var(--accent); }

	/* ── модалка вибору часу ── */
	.tp-ovl {
		position: fixed; inset: 0; z-index: 90;
		background: rgba(5, 7, 11, 0.6);
		-webkit-backdrop-filter: blur(calc(6px + 0px));
		backdrop-filter: blur(6px);
		display: grid; place-items: center; padding: 16px;
	}
	:global(html[data-perf='lite']) .tp-ovl {
		-webkit-backdrop-filter: none; backdrop-filter: none;
		background: rgba(5, 7, 11, 0.8);
	}
	.tp {
		width: min(320px, 92vw);
		padding: 14px 16px;
		border-radius: var(--radius-lg);
		display: flex; flex-direction: column; gap: 10px;
	}
	.tp h4 {
		margin: 0; font-size: 12px; font-weight: 700;
		text-transform: uppercase; letter-spacing: .09em;
		color: var(--text-faint);
	}
	.tp-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
	.tp-col {
		max-height: 200px; overflow-y: auto;
		display: flex; flex-direction: column; gap: 2px;
		padding: 4px;
		border: 1px solid var(--glass-border); border-radius: var(--radius-md);
	}
	.tp-col button {
		height: 32px; font: inherit; font-size: 14px;
		color: var(--text-dim); background: transparent; border: none;
		border-radius: 8px; cursor: pointer;
	}
	.tp-col button:hover { background: var(--glass-bg-hover); color: var(--text); }
	.tp-col button.sel { background: var(--accent-strong); color: #fff; }
	.tp-col button.dis { opacity: .3; cursor: not-allowed; }
	.tp-actions { display: flex; justify-content: flex-end; gap: 8px; }
	.tp-actions .ghost-btn { margin-top: 0; }
</style>
