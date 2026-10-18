<script lang="ts">
	import {
		Camera,
		Globe,
		Link2,
		Mail,
		MapPin,
		Phone,
		Play,
		CheckCircle2,
		Send,
		SearchX,
		TriangleAlert
	} from '@lucide/svelte';
	import {
		Dialog, Button, Field, Input, Textarea, Skeleton, ErrorState,
		Avatar, CopyButton, SearchField, EmptyState
	} from '$lib/ui';
	import { api, type ContactsData } from '$lib/api/client';
	import { friendlyError, isNetworkError, OFFLINE_EMPTY } from '$lib/errors';
	import { blurFade, pressable, spotlight, springIn, stagger } from '$lib/motion';
	import type { Component } from 'svelte';
	import type { Action } from 'svelte/action';
	import { mailtoHref, safeUrl, siteHref, telHref } from '$lib/sanitize';
	import { API_BASE } from '$lib/config';
	import { cleanTeacher } from '$lib/app/helpers';

	let {
		account_id,
		/** Тик «Оновити» з +page: змінився → перечитуємо з force=true.
		 *  contacts має TTL 24год на бекенді — без force «Оновити»
		 *  показував старі адреси/телефони філії. */
		refreshTick = 0,
		/** Тихий сигнал «слоти стора оновились у фоні»: контакти не в сторі
		 *  (кеш у api.contacts), тож тут нічого перезавантажувати не треба. */
		dataTick: _dataTick = 0
	}: {
		account_id: number;
		refreshTick?: number;
		dataTick?: number;
	} = $props();

	let data = $state<ContactsData | null>(null);
	let err = $state('');
	let mailOpen = $state(false);
	let mailTarget = $state<'ceo' | 'teach'>('ceo');
	let teacher = $state('');
	let subject = $state('');
	let message = $state('');
	let sending = $state(false);
	let mailErr = $state('');
	let mailSent = $state(false);

	async function load(force = false): Promise<void> {
		// без скелета: поки є дані, помилку мережі не показуємо замість них
		err = '';
		try {
			data = await api.contacts(account_id, force);
		} catch (e) {
			if (isNetworkError(e)) {
				if (!data) err = OFFLINE_EMPTY;
			} else {
				err = friendlyError(e);
			}
		}
	}

	void load();

	// «Оновити» в топбарі: тик змінився → форс-перечитування (мимо кеша).
	$effect(() => {
		if (refreshTick > 0) void load(true);
	});

	async function sendMail(): Promise<void> {
		if (sending) return;
		sending = true;
		mailErr = '';
		try {
			await api.contactsSend(
				account_id,
				subject.trim(),
				message.trim(),
				mailTarget,
				mailTarget === 'teach' ? teacher.trim() : undefined
			);
			subject = '';
			message = '';
			teacher = '';
			mailSent = true;
		} catch (e) {
			mailErr = friendlyError(e);
		} finally {
			sending = false;
		}
	}

	/* ── Попередження перед листом генеральному директору ──
	   Лист іде напряму ген. директору мережі: необдумане звернення може
	   мати наслідки і для студента, і для філії. Тому перед відправкою —
	   окреме вікно, кнопка «Надіслати» заблокована 5 секунд. */
	const WARN_SECONDS = 5;
	let warnOpen = $state(false);
	let warnLeft = $state(0);
	let warnTimer: ReturnType<typeof setInterval> | null = null;

	function stopWarnTimer(): void {
		if (warnTimer) clearInterval(warnTimer);
		warnTimer = null;
	}

	function openWarn(): void {
		stopWarnTimer();
		warnLeft = WARN_SECONDS;
		warnOpen = true;
		warnTimer = setInterval(() => {
			warnLeft = Math.max(0, warnLeft - 1);
			if (warnLeft === 0) stopWarnTimer();
		}, 1000);
	}

	function closeWarn(): void {
		stopWarnTimer();
		warnOpen = false;
	}

	async function confirmCeo(): Promise<void> {
		if (warnLeft > 0 || sending) return;
		closeWarn();
		await sendMail();
	}

	// закрили вікно будь-яким способом (Esc, тло) — таймер теж зупиняємо
	$effect(() => {
		if (!warnOpen) stopWarnTimer();
	});
	$effect(() => () => stopWarnTimer());

	function submitMail(): void {
		if (mailTarget === 'ceo') openWarn();
		else void sendMail();
	}

	/** `teacher` — це id_teach (рядком для Select). Офіційний MyStat шле саме
	 *  числовий id викладача, а не ПІБ: з ПІБ сервер відповідав «Перевірте
	 *  правильність заповнення полів». */
	function openMail(target: 'ceo' | 'teach', whoId: number | string | null = null): void {
		mailTarget = target;
		mailErr = '';
		mailSent = false;
		if (target === 'teach') {
			const first = mailTeachers[0]?.id;
			teacher = whoId != null ? String(whoId) : first != null ? String(first) : '';
		}
		mailOpen = true;
	}

	/** Мінімальні довжини — як у формі офіційного MyStat (minLength 3). */
	const MIN_LEN = 3;
	const subjOk = $derived(subject.trim().length >= MIN_LEN);
	const msgOk = $derived(message.trim().length >= MIN_LEN);

	function strArr(v: unknown): string[] {
		return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [];
	}

	/** Живий mapi віддає посилання на карту як google/maps/embed?pb=… — це
	 *  URL для <iframe>: відкрита в новій вкладці, вона показує урізану
	 *  сторінку. Перетворюємо на звичайне Maps-посилання (official «Maps URLs»):
	 *  1) назва місця з pb (!2z<urlsafe-base64>) → query=<адрес>;
	 *  2) інакше координати (!3d<lat>!2d<lng>) → query=lat,lng;
	 *  3) інакше віддаємо як є. */
	function normalMapsUrl(raw: string): string {
		if (!/google\.[a-z.]+\/maps\/embed/i.test(raw)) return raw;
		try {
			const b = raw.match(/!2z([A-Za-z0-9_-]+)/);
			if (b) {
				const std = b[1].replace(/-/g, '+').replace(/_/g, '/')
					+ '='.repeat((4 - (b[1].length % 4)) % 4);
				const bytes = Uint8Array.from(atob(std), (c) => c.charCodeAt(0));
				const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
				if (text.trim().length >= 4 && !/[\x00-\x08\x0e-\x1f]/.test(text)) {
					return 'https://www.google.com/maps/search/?api=1&query='
						+ encodeURIComponent(text.trim());
				}
			}
		} catch {
			/* не декодувалося — пробуємо координати */
		}
		const lat = raw.match(/!3d(-?\d+(?:\.\d+)?)/);
		const lng = raw.match(/!2d(-?\d+(?:\.\d+)?)/);
		if (lat && lng) {
			return `https://www.google.com/maps/search/?api=1&query=${lat[1]},${lng[1]}`;
		}
		return raw;
	}

	type RawTeacher = Record<string, unknown>;

	function pickStr(o: RawTeacher, keys: string[]): string {
		for (const k of keys) {
			const v = o[k];
			if (typeof v === 'string' && v.trim()) return v.trim();
		}
		return '';
	}

	/** Живий шейп (знято 2026-09, examples/live/contacts.json):
	 *  teach_contacts[] = {id_teach: int, fio_teach: str} — ЛИШЕ id та
	 *  ПІБ, телефонів/пошти у викладачів НЕМАЄ (вони в teach_main /
	 *  learning_tel тощо). Раніше чекали {name, phone, email} → картки
	 *  були порожніми «скелетами», а select модалки падав
	 *  each_key_duplicate (t.name = undefined). Тягнемо fio_teach першим,
	 *  решта — толерантні варіанти на випадок зміни шейпа. */
	type Teacher = {
		id: number | string | null;
		name: string;
		phone: string;
		email: string;
		/** Фото з нашої бази (бекенд: services/teacher_photos.py) або null. */
		photo: string | null;
	};

	/** Шлях бекенду (/api/...) → повний URL (API може жити на mapi.<домен>). */
	function apiUrl(p: unknown): string | null {
		if (typeof p !== 'string' || !p) return null;
		return p.startsWith('/') ? `${API_BASE}${p}` : safeUrl(p) || null;
	}

	/** Ключ злиття: нижній регістр, стиснуті пробіли, ё→е. */
	function mergeKey(name: string): string {
		return name.toLowerCase().replace(/ё/g, 'е').replace(/\s+/g, ' ').trim();
	}

	/** У викладача часто два акаунти: «ПІБ» і «ПІБ School». Показуємо одну
	 *  картку: ім'я без приписки, лист — на звичайний акаунт (School — лише
	 *  якщо звичайного немає), фото/id/телефон/пошта — з будь-якого, де вони є.
	 *  Запис, де ім'я — лише «School», не зливаємо ні з ким (ключ — його id). */
	function mergeSchool(list: (Teacher & { school: boolean; lone?: boolean })[]): Teacher[] {
		const by = new Map<string, Teacher & { school: boolean }>();
		let n = 0;
		for (const t of list) {
			const key = t.lone ? `#lone:${t.id ?? n}:${n}` : mergeKey(t.name);
			n++;
			const prev = by.get(key);
			if (!prev) {
				by.set(key, t);
				continue;
			}
			// звичайний акаунт має пріоритет над School; при рівності — перший
			const main = prev.school && !t.school ? t : prev;
			const other = main === t ? prev : t;
			by.set(key, {
				...main,
				id: main.id ?? other.id,
				phone: main.phone || other.phone,
				email: main.email || other.email,
				photo: main.photo ?? other.photo,
				school: main.school && other.school
			});
		}
		return [...by.values()].map(({ school: _s, ...t }) => t);
	}

	/** Телефон для показу й tel:-посилання: лише цифри з одним провідним «+»
	 *  («++380 (44) 123-45-67» → «+380441234567»); надто короткі → ''. */
	function normPhone(raw: unknown): string {
		const digits = String(raw ?? '').replace(/\D/g, '');
		return digits.length >= 5 ? `+${digits}` : '';
	}

	function normTeachers(raw: unknown): Teacher[] {
		const arr = Array.isArray(raw) ? raw : [];
		const out: (Teacher & { school: boolean; lone?: boolean })[] = [];
		for (const t of arr) {
			if (!t || typeof t !== 'object') continue;
			const o = t as RawTeacher;
			const id = typeof o.id_teach === 'number' || typeof o.id_teach === 'string'
				? o.id_teach
				: (typeof o.id === 'number' || typeof o.id === 'string' ? o.id : null);
			const phone = pickStr(o, ['phone', 'tel', 'telephone', 'phone_number', 'contact_phone']);
			const email = pickStr(o, ['email', 'mail', 'e_mail', 'contact_email']);
			let name = pickStr(o, ['fio_teach', 'name', 'fio', 'teach_name', 'name_teacher', 'teacher_name', 'teachName', 'contact_name']);
			if (!name) {
				const fb = Object.values(o).find(
					(v) => typeof v === 'string' && v.trim() && !/^(https?:)?\/\//i.test(v.trim())
				);
				name = typeof fb === 'string' ? fb.trim() : '';
			}
			if (!name && !phone && !email) continue;
			// ім'я лише «School» — це не приписка, а саме ім'я: не зливаємо
			// (\W тут не годиться: без прапорця u кирилиця теж «не-літера»)
			const lone = /^[\s\p{P}\p{S}]*school[\s\p{P}\p{S}]*$/iu.test(name);
			const cleaned = lone ? name : (cleanTeacher(name) || name);
			out.push({
				id, name: cleaned, phone, email, photo: apiUrl(o.photo),
				school: !lone && cleaned.trim() !== name.trim(), lone
			});
		}
		return mergeSchool(out);
	}

	/** Директор — завжди першим у «Контактах» (дані й фото — з бекенду). */
	const director = $derived.by(() => {
		const d = data?.director as { name?: string; role?: string; photo?: string } | undefined;
		return d?.name ? { name: d.name, role: d.role || 'Директор', photo: apiUrl(d.photo) } : null;
	});

	const addr = $derived((data?.adress as { adress_name?: string }[] | undefined) ?? []);
	const teach = $derived(
		(data?.teach_main as { teachMain_name?: string; href_teach?: string[] }[] | undefined) ?? []
	);
	const teachers = $derived(normTeachers(data?.teach_contacts));
	/** Написати можна лише викладачу з id (MyStat адресує лист за id_teach). */
	const mailTeachers = $derived(teachers.filter((t) => t.id != null && String(t.id).trim() !== ''));
	/** Адресат листа (обраний карткою «Написати»). */
	const mailTo = $derived(mailTeachers.find((t) => String(t.id) === teacher) ?? null);

	/** Прожектор лише на короткому списку викладачів (до ~20 карток). */
	const spotShort: Action<HTMLElement> = (node) =>
		teachers.length <= 20 ? spotlight(node) : undefined;

	type Row = {
		icon: Component<any>;
		label: string;
		value: string;
		href: string;
		ext?: boolean;
		copy?: string;
	};

	/* Телефони за призначенням — підписи як в офіційному MyStat:
	   learning_tel = навчальна частина, tel_room = приймальна частина,
	   tel_book = бухгалтерія (назви полів у API історичні — «кімнат
	   відпочинку» й «бібліотек» у філіях немає).
	   Спершу — номери з адреси (adress[]: там кожен номер прив'язаний точно),
	   потім — загальні списки; кожен номер показуємо ОДИН раз (MyStat
	   повторює той самий номер у кількох списках і навіть двічі в одному). */
	const PHONE_KINDS: [key: string, label: string][] = [
		['learning_tel', 'Навчальна частина'],
		['tel_room', 'Приймальна частина'],
		['tel_book', 'Бухгалтерія']
	];
	const phoneRows = $derived.by<Row[]>(() => {
		const out: Row[] = [];
		const seen = new Set<string>();
		const add = (label: string, raw: string) => {
			const num = normPhone(raw);
			if (!num || seen.has(num)) return;
			seen.add(num);
			out.push({ icon: Phone, label, value: num, href: telHref(num), copy: num });
		};
		const sources: Record<string, unknown>[] = [
			...((data?.adress as Record<string, unknown>[] | undefined) ?? []),
			(data ?? {}) as Record<string, unknown>
		];
		for (const src of sources) {
			for (const [key, label] of PHONE_KINDS) {
				for (const t of strArr(src?.[key])) add(label, t);
			}
		}
		// згруповано за призначенням (стабільно: порядок усередині групи зберігається)
		const rank = (l: string) => PHONE_KINDS.findIndex(([, lbl]) => lbl === l);
		return out.sort((a, b) => rank(a.label) - rank(b.label));
	});

	const mailRows = $derived.by<Row[]>(() => {
		const out: Row[] = [];
		for (const t of teach) {
			for (const m of strArr(t.href_teach)) {
				out.push({
					icon: Mail, label: t.teachMain_name || 'Пошта', value: m,
					href: mailtoHref(m), copy: m
				});
			}
		}
		for (const m of strArr(data?.mail_shag)) {
			out.push({ icon: Mail, label: 'Пошта', value: m, href: mailtoHref(m), copy: m });
		}
		return out;
	});

	const onlineRows = $derived.by<Row[]>(() => {
		const out: Row[] = [];
		for (const s of strArr(data?.site_shag)) {
			out.push({ icon: Globe, label: 'Сайт', value: s, href: siteHref(s), ext: true, copy: s });
		}
		const soc: [string, Component<any>, unknown][] = [
			['Facebook', Link2, data?.facebook],
			['Instagram', Camera, data?.instagram],
			['YouTube', Play, data?.youtube]
		];
		for (const [name, icon, v] of soc) {
			for (const s of strArr(v)) {
				out.push({ icon, label: 'Соцмережа', value: name, href: safeUrl(s), ext: true, copy: s });
			}
		}
		return out;
	});

	const mapLinks = $derived(strArr(data?.google_maps));

	// Пошук серед викладачів (поле показуємо, коли їх багато).
	let q = $state('');
	const filtered = $derived.by(() => {
		const n = q.trim().toLowerCase();
		return n ? teachers.filter((t) => t.name.toLowerCase().includes(n)) : teachers;
	});
	/** Директор — у списку, поки пошук його не відсіяв. */
	const showDirector = $derived.by(() => {
		const n = q.trim().toLowerCase();
		return !!director && (!n || director.name.toLowerCase().includes(n)
			|| director.role.toLowerCase().includes(n));
	});
</script>

{#snippet rowItem(r: Row)}
	{@const Ico = r.icon}
	<div class="ct-row">
		<a class="ct-link-a" href={r.href} use:pressable={{ scale: 0.98 }}
			target={r.ext ? '_blank' : undefined} rel={r.ext ? 'noopener noreferrer' : undefined}>
			<span class="ct-chip"><Ico size={15} strokeWidth={2} /></span>
			<span class="ct-txt">
				<span class="ct-lbl">{r.label}</span>
				<span class="ct-val">{r.value}</span>
			</span>
		</a>
		{#if r.copy}<CopyButton text={r.copy} size="sm" label="Копіювати" toast />{/if}
	</div>
{/snippet}

{#if err && err !== OFFLINE_EMPTY}
	<ErrorState title="Не вдалося завантажити контакти" description={err}
		onretry={() => void load(true)} />
{:else if !data && err === OFFLINE_EMPTY}
	<p class="ct-offline">{err}</p>
{:else if !data}
	<div class="ct-grid">
		{#each [0, 1, 2, 3] as n (n)}
			<Skeleton height={120} radius="var(--radius-md)" />
		{/each}
	</div>
{:else}
	<div class="ct-grid" use:stagger={{ step: 55, max: 10, scale: true }}>
		<!-- порядок боксів: Телефони → Пошта → Посилання → Адреса -->
		{#if phoneRows.length}
			<section class="ct-card" use:spotlight>
				<h3><Phone size={15} strokeWidth={2} /> Телефони</h3>
				{#each phoneRows as r, i (i)}{@render rowItem(r)}{/each}
			</section>
		{/if}

		{#if mailRows.length}
			<section class="ct-card" use:spotlight>
				<h3><Mail size={15} strokeWidth={2} /> Пошта</h3>
				{#each mailRows as r, i (i)}{@render rowItem(r)}{/each}
			</section>
		{/if}

		{#if onlineRows.length}
			<section class="ct-card" use:spotlight>
				<h3><Link2 size={15} strokeWidth={2} /> Посилання</h3>
				{#each onlineRows as r, i (i)}{@render rowItem(r)}{/each}
			</section>
		{/if}

		{#if addr.length || mapLinks.length}
			<section class="ct-card" use:spotlight>
				<h3><MapPin size={15} strokeWidth={2} /> Адреса</h3>
				{#each addr as a, i (i)}
					<div class="ct-row">
						<p class="ct-big">{a.adress_name}</p>
						{#if a.adress_name}<CopyButton text={a.adress_name} size="sm" label="Копіювати адресу" toast />{/if}
					</div>
				{/each}
				{#each mapLinks as link, i (i)}
					<a class="btn link ct-mapbtn" use:pressable href={safeUrl(normalMapsUrl(link))}
						target="_blank" rel="noopener noreferrer">
						<Globe size={13} strokeWidth={2} /> Показати на карті</a>
				{/each}
			</section>
		{/if}
	</div>

	{#if teachers.length || director}
		<div class="ct-teach-head" in:blurFade|global={{ duration: 360, delay: 200, amount: 5 }}>
			<h2 class="ct-teach-title">Контакти <span class="ct-count">{teachers.length + (director ? 1 : 0)}</span></h2>
			{#if teachers.length > 6}
				<div class="ct-search" in:springIn|global={{ duration: 420, delay: 260, start: 0.94, y: 8 }}>
					<SearchField bind:value={q} size="sm" placeholder="Знайти контакт" />
				</div>
			{/if}
		</div>
		{#if filtered.length || showDirector}
			<div class="ct-grid" use:stagger={{ step: 30, max: 12, scale: true }}>
				{#if showDirector && director}
					<section class="ct-card ct-t ct-dir" use:spotShort>
						<div class="ct-who">
							<Avatar src={director.photo} name={director.name} size="lg" />
							<div class="ct-whotxt">
								<p class="ct-big">{director.name}</p>
								<span class="ct-role">{director.role}</span>
							</div>
						</div>
						<button class="btn f ct-write" use:pressable onclick={() => openMail('ceo')}>
							<Send size={13} strokeWidth={2} /> Написати</button>
					</section>
				{/if}
				{#each filtered as t, i (t.id ?? `i${i}`)}
					<section class="ct-card ct-t" use:spotShort>
						<div class="ct-who">
							<Avatar src={t.photo} name={t.name} size="lg" />
							<p class="ct-big">{t.name}</p>
						</div>
						{#if normPhone(t.phone)}
							{@render rowItem({ icon: Phone, label: 'Телефон', value: normPhone(t.phone), href: telHref(normPhone(t.phone)), copy: normPhone(t.phone) })}
						{/if}
						{#if t.email}
							{@render rowItem({ icon: Mail, label: 'Пошта', value: t.email, href: mailtoHref(t.email), copy: t.email })}
						{/if}
						<button class="btn f ct-write" use:pressable onclick={() => openMail('teach', t.id)}>
							<Send size={13} strokeWidth={2} /> Написати</button>
					</section>
				{/each}
			</div>
		{:else}
			<div in:blurFade={{ duration: 280, amount: 4 }}>
				<EmptyState icon={SearchX} title="Нікого не знайдено"
					description="Спробуй інший запит." />
			</div>
		{/if}
	{/if}
{/if}

<!-- Модалка «Написати директору / викладачу» -->
<Dialog bind:open={mailOpen} size="sm"
	title={mailTarget === 'ceo' ? 'Написати генеральному директору' : 'Написати викладачу'}>
	{#if mailSent}
		<div class="sent" in:blurFade={{ duration: 320, amount: 6 }}>
			<span in:springIn={{ duration: 520, start: 0.5, y: 0 }}><CheckCircle2 size={40} /></span>
			<h3>Лист надіслано</h3>
			<p>Відповідь прийде на твою пошту.</p>
			<Button onclick={() => (mailOpen = false)}>Закрити</Button>
		</div>
	{:else}
		<form class="mform" onsubmit={(e) => { e.preventDefault(); submitMail(); }}>
			{#if mailErr}<p class="ct-err">{mailErr}</p>{/if}
			<!-- Кому: адресата вже обрано карткою «Написати» — без вибору в модалці
			     (панель як «Викладач» у деталях домашки) -->
			{#if mailTarget === 'teach' && mailTo}
				<div class="to">
					<Avatar src={mailTo.photo} name={mailTo.name} size={34} />
					<span>
						<small class="text-faint">Викладач</small>
						<b>{mailTo.name}</b>
					</span>
				</div>
			{:else if mailTarget === 'ceo' && director}
				<div class="to">
					<Avatar src={director.photo} name={director.name} size={34} />
					<span>
						<small class="text-faint">{director.role}</small>
						<b>{director.name}</b>
					</span>
				</div>
			{/if}
			<Field label="Тема"
				hint={subject.trim() && !subjOk ? `Щонайменше ${MIN_LEN} символи` : undefined}>
				{#snippet children({ id, describedBy })}
					<Input {id} aria-describedby={describedBy} bind:value={subject}
						placeholder="Тема звернення" />
				{/snippet}
			</Field>
			<Field label="Повідомлення"
				hint={message.trim() && !msgOk ? `Щонайменше ${MIN_LEN} символи` : undefined}>
				{#snippet children({ id, describedBy })}
					<Textarea {id} aria-describedby={describedBy} rows={5} showCount maxlength={2000}
						bind:value={message} placeholder="Опиши своє звернення…" />
				{/snippet}
			</Field>
			<div class="mact">
				<Button variant="ghost" onclick={() => (mailOpen = false)}>Скасувати</Button>
				<Button type="submit" loading={sending}
					disabled={!subjOk || !msgOk
						|| (mailTarget === 'teach' && !teacher.trim())}>
					{sending ? 'Надсилаю…' : 'Надіслати'}
				</Button>
			</div>
		</form>
	{/if}
</Dialog>

<!-- Попередження перед листом генеральному директору -->
<Dialog bind:open={warnOpen} size="sm" title="Увага!">
	<div class="warn">
		<span class="warn-ico" in:springIn|global={{ duration: 520, start: 0.5, y: 0 }}>
			<TriangleAlert size={30} strokeWidth={2} />
		</span>
		<p>
			Лист піде <b>напряму генеральному директору</b> мережі. Він розглядає
			звернення особисто, і грубе, образливе чи необдумане повідомлення
			може мати серйозні наслідки — <b>і для тебе, і для твоєї філії</b>.
		</p>
		<p class="warn-sub">
			Пиши ввічливо й по суті. Якщо питання може вирішити викладач або
			навчальна частина — краще звернись до них.
		</p>
	</div>
	<div class="mact">
		<Button variant="ghost" onclick={closeWarn}>Скасувати</Button>
		<Button variant="danger" loading={sending} disabled={warnLeft > 0 || sending}
			onclick={() => void confirmCeo()}>
			{warnLeft > 0 ? `Надіслати (${warnLeft})` : 'Надіслати'}
		</Button>
	</div>
</Dialog>

<style>
	/* «Кому» у модалці листа — як панель «Викладач» у деталях домашки */
	.to {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 9px 11px;
		border-radius: 12px;
		background: var(--surface-2);
		width: fit-content;
		max-width: 100%;
		min-width: 0;
	}
	.to > span {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.to small {
		font-size: 11px;
	}
	.to b {
		font-size: 13.5px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	/* вікно-попередження перед листом ген. директору */
	.warn {
		display: flex;
		flex-direction: column;
		align-items: center;
		text-align: center;
		gap: 10px;
		margin-bottom: 18px;
	}
	.warn-ico {
		display: grid;
		place-items: center;
		width: 56px;
		height: 56px;
		border-radius: 50%;
		color: var(--danger);
		background: color-mix(in srgb, var(--danger) 14%, transparent);
	}
	.warn p {
		margin: 0;
		font-size: 14px;
		line-height: 1.5;
		color: var(--text);
	}
	.warn p.warn-sub {
		font-size: 13px;
		color: var(--text-dim);
	}

	.ct-offline {
		color: var(--text-dim, #8a8a99);
		text-align: center;
		padding: 24px 0;
		font-size: 14px;
	}

	.ct-err {
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-sm);
		background: var(--color-danger-soft);
		color: var(--color-danger);
		font-size: var(--text-sm);
	}

	.mform {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	.mact {
		display: flex;
		justify-content: flex-end;
		gap: var(--space-2);
	}

	.sent {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-4) 0;
		text-align: center;
		color: var(--color-success);
	}

	.sent h3 {
		margin: 0;
		font-size: var(--text-lg);
		color: var(--color-text);
	}

	.sent p {
		margin: 0 0 var(--space-3);
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}

	.ct-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(min(100%, 260px), 1fr));
		gap: 10px;
	}

	.ct-card {
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-md);
		background: var(--glass-bg);
		padding: 14px 16px;
		display: flex;
		flex-direction: column;
		gap: 8px;
		min-width: 0;
	}

	/* картки викладачів: довгий список — поза екраном не рендеряться */
	.ct-t {
		content-visibility: auto;
		contain-intrinsic-size: auto 150px;
	}

	.ct-card h3 {
		margin: 0;
		display: flex;
		align-items: center;
		gap: 7px;
		font-size: 13px;
		color: var(--accent);
	}

	.ct-card .btn.f {
		justify-content: flex-start;
		gap: 8px;
	}

	.ct-mapbtn {
		margin-top: auto;
	}

	.ct-big {
		margin: 0;
		font-weight: 700;
		color: var(--text);
		font-size: 14px;
		min-width: 0;
		flex: 1;
	}

	.ct-who {
		display: flex;
		align-items: center;
		gap: 12px;
		min-width: 0;
	}

	.ct-whotxt {
		display: flex;
		flex-direction: column;
		gap: 3px;
		min-width: 0;
		flex: 1;
	}

	/* роль директора — м'яка акцентна пігулка */
	.ct-role {
		align-self: flex-start;
		font-size: 11px;
		font-weight: 700;
		letter-spacing: 0.02em;
		color: var(--accent);
		background: var(--accent-soft);
		padding: 2px 9px;
		border-radius: 999px;
	}

	/* картка директора — ледь виділена акцентною рамкою */
	.ct-dir {
		border-color: color-mix(in srgb, var(--accent) 35%, var(--glass-border));
	}

	/* рядок: посилання (чип + два рядки тексту) і кнопка копіювання */
	.ct-row {
		display: flex;
		align-items: center;
		gap: 4px;
		min-width: 0;
	}

	.ct-link-a {
		flex: 1;
		min-width: 0;
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 4px 6px 4px 4px;
		border-radius: var(--radius-sm);
		color: var(--text-dim);
		text-decoration: none;
		transition: background var(--dur-fast) ease;
	}

	.ct-link-a:hover {
		background: var(--color-hover);
	}

	.ct-chip {
		flex-shrink: 0;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 30px;
		height: 30px;
		border-radius: var(--radius-sm);
		background: var(--color-surface-2);
		color: var(--accent);
		transition: transform 320ms var(--ease-spring);
	}

	.ct-link-a:hover .ct-chip {
		transform: scale(1.1) rotate(-4deg);
	}

	.ct-txt {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	.ct-lbl {
		font-size: 11px;
		color: var(--color-text-muted);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.ct-val {
		font-size: 13px;
		font-weight: 600;
		color: var(--text);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.ct-link-a:hover .ct-val {
		color: var(--accent);
	}

	.ct-write {
		margin-top: auto;
	}

	.ct-teach-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: 10px;
		margin: 20px 0 10px;
	}

	.ct-teach-title {
		margin: 0;
		font-size: 15px;
		color: var(--text);
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.ct-count {
		font-size: 11px;
		font-weight: 600;
		padding: 1px 8px;
		border-radius: 999px;
		background: var(--color-surface-2);
		color: var(--color-text-muted);
	}

	.ct-search {
		flex: 1 1 200px;
		max-width: 320px;
	}

	@media (max-width: 480px) {
		.ct-search {
			max-width: none;
		}
	}
</style>
