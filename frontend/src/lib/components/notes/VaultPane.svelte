<script lang="ts">
	import { confirm } from '$lib/ui';
	import { showToast } from '$lib/stores/toast.svelte';
	import { onDestroy, tick } from 'svelte';
	import { flip } from 'svelte/animate';
	import {
		AlignLeft,
		ArrowLeft,
		Check,
		Copy,
		Dices,
		ExternalLink,
		Eye,
		EyeOff,
		GripVertical,
		KeyRound,
		Link2,
		Lock,
		Mail,
		Pencil,
		Phone,
		Pin,
		Plus,
		Search,
		SlidersHorizontal,
		Trash2,
		User,
		X
	} from '@lucide/svelte';
	import type { Component } from 'svelte';
	import {
		api,
		type VaultEntryItem,
		type VaultField,
		type VaultFieldKind
	} from '$lib/api/client';
	import { friendlyError } from '$lib/errors';
	import { mailtoHref, siteHref, telHref } from '$lib/sanitize';
	import { blurFade, fx, motionOK, pop, pressable, springIn, stagger } from '$lib/motion';

	/** Ключ відкритого запису: перемонтує деталі з blur-появою. */
	let docKey = $state(0);
	/** Поле, значення якого щойно скопіювали (іконка → галочка). */
	let copiedId = $state<string | null>(null);
	let copiedTimer: ReturnType<typeof setTimeout> | undefined;

	function popIn(node: HTMLElement): void {
		pop(node, 1.4);
	}

	function markCopied(id: string): void {
		copiedId = id;
		clearTimeout(copiedTimer);
		copiedTimer = setTimeout(() => (copiedId = null), 1300);
	}

	interface Draft {
		id: number | null;
		title: string;
		group: string;
		pinned: boolean;
		broken: boolean;
		fields: VaultField[];
	}

	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	const KINDS: Record<VaultFieldKind, { label: string; icon: Component<any> }> = {
		login: { label: 'Логін', icon: User },
		password: { label: 'Пароль', icon: KeyRound },
		email: { label: 'Email', icon: Mail },
		phone: { label: 'Телефон', icon: Phone },
		url: { label: 'Посилання', icon: Link2 },
		secret: { label: 'Прихований секрет', icon: Lock },
		text: { label: 'Текст', icon: AlignLeft }
	};
	/** Що пропонуємо в меню «Додати поле». Останній пункт — довільне поле. */
	const ADD_MENU: { kind: VaultFieldKind; label: string; custom?: boolean }[] = [
		{ kind: 'email', label: 'Email' },
		{ kind: 'phone', label: 'Телефон' },
		{ kind: 'url', label: 'Посилання' },
		{ kind: 'login', label: 'Логін' },
		{ kind: 'password', label: 'Пароль' },
		{ kind: 'secret', label: 'Прихований секрет' },
		{ kind: 'text', label: 'Своє поле…', custom: true }
	];
	const isSecret = (k: VaultFieldKind): boolean => k === 'password' || k === 'secret';

	let items = $state<VaultEntryItem[]>([]);
	let q = $state('');
	let groupFilter = $state('');
	let loading = $state(true);
	let err = $state('');

	let draft = $state<Draft | null>(null);
	let editing = $state(false);
	let saving = $state(false);
	let revealed = $state<Record<string, boolean>>({});
	let addOpen = $state(false);
	/** Меню «Додати поле» відкриваємо вгору, якщо знизу немає місця (нижня панель на телефоні). */
	let addUp = $state(false);
	let listEl = $state<HTMLElement | null>(null);
	let titleEl = $state<HTMLInputElement | null>(null);

	// ---- генератор паролів (налаштування переживають перезавантаження)
	interface GenCfg {
		len: number;
		lower: boolean;
		upper: boolean;
		digits: boolean;
		symbols: boolean;
	}
	const GEN_KEY = 'm1.vault.gen';
	function loadGen(): GenCfg {
		const def: GenCfg = { len: 18, lower: true, upper: true, digits: true, symbols: true };
		try {
			const raw = localStorage.getItem(GEN_KEY);
			if (raw) return { ...def, ...(JSON.parse(raw) as Partial<GenCfg>) };
		} catch {
			/* сховище недоступне — дефолти */
		}
		return def;
	}
	let gen = $state<GenCfg>(loadGen());
	let genOpenFor = $state<string | null>(null);

	/** Відкладений запит (~150мс): фільтр не біжить на кожну літеру. */
	let qd = $state('');
	$effect(() => {
		const v = q;
		const t = setTimeout(() => (qd = v), 150);
		return () => clearTimeout(t);
	});

	const listed = $derived.by(() => {
		const s = qd.trim().toLowerCase();
		return items.filter((e) => {
			if (groupFilter && e.group !== groupFilter) return false;
			if (!s) return true;
			if (e.title.toLowerCase().includes(s) || e.group.toLowerCase().includes(s)) return true;
			return e.fields.some((f) => !isSecret(f.kind) && f.value.toLowerCase().includes(s));
		});
	});
	const groups = $derived([...new Set(items.map((e) => e.group).filter(Boolean))].sort());

	function flash(msg: string): void {
		showToast(msg, 1800);
	}

	async function loadList(): Promise<void> {
		try {
			items = (await api.vaultList()).items;
			err = '';
		} catch (e) {
			err = friendlyError(e);
		} finally {
			loading = false;
		}
	}
	void loadList();

	const newId = (): string => Math.random().toString(36).slice(2, 10);

	function toDraft(e: VaultEntryItem): Draft {
		return {
			id: e.id,
			title: e.title,
			group: e.group,
			pinned: e.pinned,
			broken: e.broken,
			fields: e.fields.map((f) => ({ id: f.id, kind: f.kind, label: f.label, value: f.value }))
		};
	}

	/** У списку секрети не зберігаємо — лише ознаку наявності. */
	function toListItem(e: VaultEntryItem): VaultEntryItem {
		return {
			...e,
			fields: e.fields.map((f) =>
				isSecret(f.kind) ? { ...f, value: '', has_value: !!f.value } : f
			)
		};
	}

	async function open(e: VaultEntryItem): Promise<void> {
		try {
			const full = await api.vaultGet(e.id);
			draft = toDraft(full);
			docKey++;
			editing = false;
			revealed = {};
			genOpenFor = null;
			addOpen = false;
		} catch (ex) {
			err = friendlyError(ex);
		}
	}

	async function newEntry(): Promise<void> {
		draft = {
			id: null,
			title: '',
			group: groupFilter,
			pinned: false,
			broken: false,
			fields: [
				{ id: newId(), kind: 'login', label: 'Логін', value: '' },
				{ id: newId(), kind: 'password', label: 'Пароль', value: '' },
				{ id: newId(), kind: 'text', label: 'Опис', value: '' }
			]
		};
		docKey++;
		editing = true;
		revealed = {};
		genOpenFor = null;
		addOpen = false;
		await tick();
		titleEl?.focus();
	}

	async function startEdit(): Promise<void> {
		editing = true;
		await tick();
		titleEl?.focus();
	}

	async function cancelEdit(): Promise<void> {
		if (!draft) return;
		genOpenFor = null;
		addOpen = false;
		if (draft.id === null) {
			draft = null;
			return;
		}
		const cur = items.find((x) => x.id === draft!.id);
		if (cur) await open(cur);
		editing = false;
	}

	async function save(): Promise<void> {
		if (!draft || saving) return;
		if (!draft.title.trim()) {
			err = 'Вкажи сайт або назву';
			titleEl?.focus();
			return;
		}
		saving = true;
		err = '';
		try {
			const body = {
				title: draft.title,
				group: draft.group,
				pinned: draft.pinned,
				fields: draft.fields.map(({ id, kind, label, value }) => ({ id, kind, label, value }))
			};
			const saved =
				draft.id === null ? await api.vaultCreate(body) : await api.vaultUpdate(draft.id, body);
			const li = toListItem(saved);
			const i = items.findIndex((x) => x.id === saved.id);
			if (i >= 0) items[i] = li;
			else items.push(li);
			items.sort(
				(a, b) => Number(b.pinned) - Number(a.pinned) || a.title.localeCompare(b.title, 'uk')
			);
			draft = toDraft(saved);
			editing = false;
			genOpenFor = null;
			flash('Збережено ✓');
		} catch (e) {
			err = friendlyError(e);
		} finally {
			saving = false;
		}
	}

	async function remove(): Promise<void> {
		if (!draft) return;
		const ok = await confirm({
			title: `Видалити запис «${draft.title || 'без назви'}»?`,
			message: 'Запис зникне зі сховища без можливості відновлення.',
			confirmText: 'Видалити',
			danger: true
		});
		if (!ok) return;
		if (!draft) return;
		const id = draft.id;
		draft = null;
		if (id === null) return;
		try {
			await api.vaultDelete(id);
			items = items.filter((x) => x.id !== id);
		} catch (e) {
			err = friendlyError(e);
		}
	}

	function closeEntry(): void {
		draft = null;
		editing = false;
		err = '';
	}

	// ---- поля
	async function addField(kind: VaultFieldKind, custom = false): Promise<void> {
		if (!draft) return;
		const id = newId();
		draft.fields.push({ id, kind, label: custom ? '' : KINDS[kind].label, value: '' });
		addOpen = false;
		await tick();
		const sel = custom ? `[data-fid="${id}"] .lbl` : `[data-fid="${id}"] .val`;
		listEl?.querySelector<HTMLElement>(sel)?.focus();
	}

	function toggleAdd(e: MouseEvent): void {
		addOpen = !addOpen;
		if (addOpen) {
			const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
			// меню ≈ 290px; знизу ще ~90px займає нижня панель
			addUp = window.innerHeight - r.bottom < 290 + 90 && r.top > 300;
		}
	}

	function removeField(id: string): void {
		if (!draft) return;
		draft.fields = draft.fields.filter((f) => f.id !== id);
	}

	function moveField(id: string, to: number): void {
		if (!draft) return;
		const from = draft.fields.findIndex((f) => f.id === id);
		if (from < 0 || to < 0 || to >= draft.fields.length || from === to) return;
		const [f] = draft.fields.splice(from, 1);
		draft.fields.splice(to, 0, f);
	}

	// ---- перетягування полів (pointer events: працює і мишею, і пальцем)
	let dragId = $state<string | null>(null);

	function dragStart(e: PointerEvent, id: string): void {
		e.preventDefault();
		dragId = id;
		(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
	}

	let dragRaf = 0;
	let dragY = 0;

	/** rAF-тротлінг: переставляємо поля не частіше за кадр. */
	function dragMove(e: PointerEvent): void {
		if (!dragId || !draft || !listEl) return;
		dragY = e.clientY;
		if (dragRaf) return;
		dragRaf = requestAnimationFrame(() => {
			dragRaf = 0;
			if (!dragId || !draft || !listEl) return;
			const others = [...listEl.querySelectorAll<HTMLElement>('[data-fid]')].filter(
				(el) => el.dataset.fid !== dragId
			);
			let idx = 0;
			for (const el of others) {
				const r = el.getBoundingClientRect();
				if (dragY > r.top + r.height / 2) idx++;
			}
			moveField(dragId, idx);
		});
	}

	function dragEnd(): void {
		dragId = null;
		cancelAnimationFrame(dragRaf);
		dragRaf = 0;
	}

	function dragKey(e: KeyboardEvent, id: string): void {
		if (!draft) return;
		const i = draft.fields.findIndex((f) => f.id === id);
		if (e.key === 'ArrowUp') {
			e.preventDefault();
			moveField(id, i - 1);
		} else if (e.key === 'ArrowDown') {
			e.preventDefault();
			moveField(id, i + 1);
		}
	}

	// ---- буфер обміну
	async function copy(text: string): Promise<void> {
		if (!text) return;
		try {
			await navigator.clipboard.writeText(text);
		} catch {
			const ta = document.createElement('textarea');
			ta.value = text;
			ta.style.position = 'fixed';
			ta.style.opacity = '0';
			document.body.appendChild(ta);
			ta.select();
			try {
				document.execCommand('copy');
			} finally {
				ta.remove();
			}
		}
		flash('Скопійовано');
	}

	// ---- генератор
	function randInt(n: number): number {
		const buf = new Uint32Array(1);
		const lim = Math.floor(0x100000000 / n) * n;
		do crypto.getRandomValues(buf);
		while (buf[0] >= lim);
		return buf[0] % n;
	}

	function makePassword(c: GenCfg): string {
		const sets: string[] = [];
		if (c.lower) sets.push('abcdefghijkmnopqrstuvwxyz');
		if (c.upper) sets.push('ABCDEFGHJKLMNPQRSTUVWXYZ');
		if (c.digits) sets.push('23456789');
		if (c.symbols) sets.push('!@#$%^&*-_=+?');
		if (!sets.length) sets.push('abcdefghijkmnopqrstuvwxyz');
		const all = sets.join('');
		const out: string[] = sets.map((s) => s[randInt(s.length)]);
		while (out.length < c.len) out.push(all[randInt(all.length)]);
		for (let i = out.length - 1; i > 0; i--) {
			const j = randInt(i + 1);
			[out[i], out[j]] = [out[j], out[i]];
		}
		return out.slice(0, Math.max(c.len, sets.length)).join('');
	}

	function generate(f: VaultField): void {
		f.value = makePassword(gen);
		revealed[f.id] = true;
		persistGen();
		// м'яка «перезйомка» нового значення: розмиття → різко
		if (motionOK()) {
			void tick().then(() => {
				listEl
					?.querySelector<HTMLElement>(`[data-fid="${f.id}"] .val`)
					?.animate(
						[
							{ opacity: 0.35, ...(fx() ? { filter: 'blur(5px)' } : {}), transform: 'translateY(2px)' },
							{ opacity: 1, ...(fx() ? { filter: 'none' } : {}), transform: 'none' }
						],
						{ duration: 260, easing: 'cubic-bezier(0.22, 1, 0.36, 1)' }
					);
			});
		}
	}

	function persistGen(): void {
		try {
			localStorage.setItem(GEN_KEY, JSON.stringify(gen));
		} catch {
			/* не критично */
		}
	}

	// ---- вигляд
	function hue(s: string): number {
		let h = 0;
		for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) % 360;
		return h;
	}

	function subtitle(e: VaultEntryItem): string {
		const login = e.fields.find((f) => f.kind === 'login' && f.value);
		const mail = e.fields.find((f) => f.kind === 'email' && f.value);
		return login?.value || mail?.value || e.group || '';
	}

	function linkFor(f: VaultField): string {
		if (f.kind === 'url') return siteHref(f.value);
		if (f.kind === 'email') return mailtoHref(f.value);
		if (f.kind === 'phone') return telHref(f.value);
		return '#';
	}

	onDestroy(() => {
		revealed = {};
	});
</script>

<div class="split" class:open={draft !== null}>
	<aside class="list">
		<div class="tools">
			<label class="search">
				<Search size={15} />
				<input type="search" placeholder="Пошук: сайт, логін…" bind:value={q} aria-label="Пошук" />
			</label>
			<button class="btn btn-primary add" use:pressable onclick={newEntry}><Plus size={16} /> Додати</button>
		</div>

		{#if groups.length}
			<div class="chips">
				<button class="chip" class:on={groupFilter === ''} onclick={() => (groupFilter = '')}
					>Усі</button
				>
				{#each groups as g (g)}
					<button
						class="chip"
						class:on={groupFilter === g}
						onclick={() => (groupFilter = groupFilter === g ? '' : g)}>{g}</button
					>
				{/each}
			</div>
		{/if}

		{#if err && !draft}<p class="err" role="alert">⚠ {err}</p>{/if}

		<div class="cards">
			{#if loading}
				<p class="muted">Завантаження…</p>
			{:else if listed.length === 0}
				<div class="empty">
					<KeyRound size={30} />
					<p>{q.trim() || groupFilter ? 'Нічого не знайдено' : 'Сховище порожнє'}</p>
					{#if !q.trim() && !groupFilter}
						<button class="btn" onclick={newEntry}>Додати перший запис</button>
					{/if}
				</div>
			{:else}
				<div class="cl" use:stagger={{ step: 28, max: 10, y: 8 }}>
					{#each listed as e (e.id)}
						<button
							class="card"
							class:active={draft?.id === e.id}
							use:pressable={{ scale: 0.98 }}
							animate:flip={{ duration: 340 }}
							in:springIn={{ duration: 320, start: 0.96, y: 8 }}
							onclick={() => open(e)}
						>
							<span class="ava" style="--h:{hue(e.title)}">{(e.title[0] || '?').toUpperCase()}</span>
							<span class="txt">
								<b class="t">{e.title}</b>
								<span class="sub">{subtitle(e) || '—'}</span>
							</span>
							{#if e.pinned}<Pin size={13} class="pin" />{/if}
						</button>
					{/each}
				</div>
			{/if}
		</div>
	</aside>

	<section class="detail" bind:this={listEl}>
		{#if draft}
			{#key docKey}
			<div class="doc" in:blurFade|global={{ duration: 360, amount: 0, y: 6 }}>
			<header class="bar">
				<button class="icon back" onclick={closeEntry} aria-label="Назад до списку">
					<ArrowLeft size={18} />
				</button>
				<span class="ava big" style="--h:{hue(draft.title)}"
					>{(draft.title[0] || '?').toUpperCase()}</span
				>
				<h3 class="head">{draft.title || 'Новий запис'}</h3>
				{#if editing}
					<button
						class="icon"
						class:on={draft.pinned}
						onclick={() => draft && (draft.pinned = !draft.pinned)}
						aria-label="Закріпити"
						title="Закріпити"><Pin size={17} /></button
					>
				{:else}
					<button class="icon" onclick={startEdit} aria-label="Редагувати" title="Редагувати">
						<Pencil size={17} />
					</button>
				{/if}
				{#if draft.id !== null}
					<button class="icon danger" onclick={remove} aria-label="Видалити" title="Видалити">
						<Trash2 size={17} />
					</button>
				{/if}
			</header>

			{#if draft.broken}
				<p class="err" role="alert">
					⚠ Не вдалося розшифрувати поля цього запису (змінився ключ шифрування сервера).
				</p>
			{/if}
			{#if err}<p class="err" role="alert">⚠ {err}</p>{/if}

			{#if editing}
				<div class="top2">
					<label class="fld">
						<span>Сайт або назва</span>
						<input
							bind:this={titleEl}
							bind:value={draft.title}
							maxlength="200"
							placeholder="example.com або 192.168.0.1"
							autocomplete="off"
							spellcheck="false"
						/>
					</label>
					<label class="fld">
						<span>Група</span>
						<input
							bind:value={draft.group}
							maxlength="60"
							list="vault-groups"
							placeholder="напр. Робота"
							autocomplete="off"
						/>
						<datalist id="vault-groups">
							{#each groups as g (g)}<option value={g}></option>{/each}
						</datalist>
					</label>
				</div>
			{:else if draft.group}
				<span class="grp">{draft.group}</span>
			{/if}

			<div class="fields" class:dragging={dragId !== null}>
				{#each draft.fields as f (f.id)}
					{@const K = KINDS[f.kind]}
					<div
						class="row"
						class:drag={dragId === f.id}
						data-fid={f.id}
						animate:flip={{ duration: 180 }}
						in:springIn={{ duration: 300, start: 0.96, y: 8 }}
						out:blurFade={{ duration: 160, amount: 0 }}
					>
						{#if editing}
							<button
								class="grip"
								aria-label="Перетягнути поле «{f.label || K.label}»"
								title="Перетягни (або ↑ ↓)"
								onpointerdown={(e) => dragStart(e, f.id)}
								onpointermove={dragMove}
								onpointerup={dragEnd}
								onpointercancel={dragEnd}
								onkeydown={(e) => dragKey(e, f.id)}
							>
								<GripVertical size={16} />
							</button>
						{/if}
						<K.icon size={16} class="kico" />
						<div class="body">
							{#if editing}
								<input
									class="lbl"
									bind:value={f.label}
									maxlength="60"
									placeholder="Назва поля"
									aria-label="Назва поля"
								/>
								<div class="valrow">
									{#if f.kind === 'text'}
										<textarea
											class="val"
											rows="2"
											bind:value={f.value}
											maxlength="4000"
											placeholder="Значення"
										></textarea>
									{:else}
										<input
											class="val"
											type={isSecret(f.kind) && !revealed[f.id] ? 'password' : 'text'}
											bind:value={f.value}
											maxlength="4000"
											placeholder="Значення"
											autocomplete={isSecret(f.kind) ? 'new-password' : 'off'}
											autocapitalize="off"
											spellcheck="false"
											inputmode={f.kind === 'phone'
												? 'tel'
												: f.kind === 'email'
													? 'email'
													: undefined}
										/>
									{/if}
									{#if isSecret(f.kind)}
										<button
											class="mini"
											onclick={() => (revealed[f.id] = !revealed[f.id])}
											aria-label={revealed[f.id] ? 'Сховати' : 'Показати'}
										>
											{#if revealed[f.id]}<EyeOff size={15} />{:else}<Eye size={15} />{/if}
										</button>
										{#if f.kind === 'password'}
											<button
												class="mini acc"
												onclick={() => generate(f)}
												aria-label="Згенерувати пароль"
												title="Згенерувати"><Dices size={15} /></button
											>
											<button
												class="mini"
												class:on={genOpenFor === f.id}
												onclick={() => (genOpenFor = genOpenFor === f.id ? null : f.id)}
												aria-label="Налаштування генератора"
												title="Налаштування"><SlidersHorizontal size={15} /></button
											>
										{/if}
									{/if}
								</div>
								{#if genOpenFor === f.id}
									<div class="gen">
										<label class="len">
											Довжина: <b>{gen.len}</b>
											<input
												type="range"
												min="8"
												max="48"
												bind:value={gen.len}
												oninput={() => generate(f)}
											/>
										</label>
										<div class="opts">
											{#each [['lower', 'a-z'], ['upper', 'A-Z'], ['digits', '0-9'], ['symbols', '!@#']] as [key, lab] (key)}
												<label class="opt">
													<input
														type="checkbox"
														checked={gen[key as 'lower' | 'upper' | 'digits' | 'symbols']}
														onchange={(ev) => {
															gen[key as 'lower' | 'upper' | 'digits' | 'symbols'] = (
																ev.currentTarget as HTMLInputElement
															).checked;
															generate(f);
														}}
													/>
													{lab}
												</label>
											{/each}
										</div>
									</div>
								{/if}
							{:else}
								<span class="lab">{f.label || K.label}</span>
								<div class="valrow">
									{#if isSecret(f.kind)}
										<span class="read mono">
											{#if !f.has_value && !f.value}
												<i class="faint">порожньо</i>
											{:else}
												{#key revealed[f.id]}
													<span class="rv" in:blurFade={{ duration: 380, amount: 9 }}
														>{revealed[f.id] ? f.value : '••••••••••'}</span
													>
												{/key}
											{/if}
										</span>
									{:else if !f.value}
										<span class="read"><i class="faint">порожньо</i></span>
									{:else if linkFor(f) !== '#'}
										<a
											class="read lnk"
											href={linkFor(f)}
											target={f.kind === 'url' ? '_blank' : undefined}
											rel="noopener noreferrer">{f.value}</a
										>
									{:else}
										<span class="read" class:pre={f.kind === 'text'}>{f.value}</span>
									{/if}
									{#if isSecret(f.kind) && (f.has_value || f.value)}
										<button
											class="mini"
											onclick={() => (revealed[f.id] = !revealed[f.id])}
											aria-label={revealed[f.id] ? 'Сховати' : 'Показати'}
										>
											{#if revealed[f.id]}<EyeOff size={15} />{:else}<Eye size={15} />{/if}
										</button>
									{/if}
									{#if f.value}
										<button
											class="mini"
											class:on={copiedId === f.id}
											use:pressable={{ scale: 0.88 }}
											onclick={() => {
												void copy(f.value);
												markCopied(f.id);
											}}
											aria-label="Копіювати"
											title="Копіювати"
											>{#key copiedId === f.id}<span class="ci" use:popIn
													>{#if copiedId === f.id}<Check size={15} />{:else}<Copy size={15} />{/if}</span
												>{/key}</button
										>
										{#if f.kind === 'url' && linkFor(f) !== '#'}
											<a
												class="mini"
												href={linkFor(f)}
												target="_blank"
												rel="noopener noreferrer"
												aria-label="Відкрити"><ExternalLink size={15} /></a
											>
										{/if}
									{/if}
								</div>
							{/if}
						</div>
						{#if editing}
							<button class="mini danger" onclick={() => removeField(f.id)} aria-label="Видалити поле"
								><X size={15} /></button
							>
						{/if}
					</div>
				{/each}
			</div>

			{#if editing}
				<div class="addwrap">
					<button class="btn addf" onclick={toggleAdd}>
						<Plus size={15} /> Додати поле
					</button>
					{#if addOpen}
						<div
							class="menu"
							class:up={addUp}
							role="menu"
							in:springIn={{ duration: 280, start: 0.94, y: addUp ? 6 : -6 }}
							out:blurFade={{ duration: 140, amount: 3 }}
						>
							{#each ADD_MENU as m (m.label)}
								{@const I = KINDS[m.kind].icon}
								<button role="menuitem" onclick={() => addField(m.kind, m.custom)}>
									<I size={15} />
									{m.label}
								</button>
							{/each}
						</div>
					{/if}
				</div>

				<div class="actions">
					<button class="btn" onclick={cancelEdit}>Скасувати</button>
					<button class="btn btn-primary" onclick={save} disabled={saving}>
						{saving ? 'Збереження…' : 'Зберегти'}
					</button>
				</div>
			{/if}
			</div>
			{/key}
		{:else}
			<div class="placeholder" in:blurFade|global={{ duration: 360, amount: 6 }}>
				<KeyRound size={42} />
				<p>Обери запис зі списку або додай новий</p>
				<small>Паролі зберігаються на сервері у зашифрованому вигляді</small>
			</div>
		{/if}
	</section>
</div>


<style>
	.split {
		display: grid;
		grid-template-columns: minmax(250px, 340px) 1fr;
		gap: 14px;
		min-height: 62dvh;
		align-items: start;
	}

	.list,
	.detail {
		min-width: 0;
	}

	.cl {
		display: contents;
	}

	.rv {
		display: inline-block;
	}

	.ci {
		display: inline-flex;
	}

	.tools {
		display: flex;
		gap: 8px;
		margin-bottom: 10px;
	}

	.search {
		flex: 1;
		min-width: 0;
		display: flex;
		align-items: center;
		gap: 7px;
		padding: 0 11px;
		border-radius: var(--radius-sm);
		border: 1px solid var(--glass-border);
		background: var(--glass-bg);
		color: var(--text-faint);
		transition: border-color 0.2s ease;
	}

	.search:focus-within {
		border-color: var(--accent);
	}

	.search input {
		flex: 1;
		min-width: 0;
		padding: 9px 0;
		border: 0;
		outline: 0;
		background: none;
		color: var(--text);
		font: inherit;
		font-size: 14px;
	}

	.add {
		padding: 8px 14px;
		white-space: nowrap;
	}

	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin-bottom: 10px;
	}

	.chip {
		padding: 4px 11px;
		font: inherit;
		font-size: 12px;
		font-weight: 600;
		color: var(--text-dim);
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: 999px;
		cursor: pointer;
		transition:
			background 0.18s ease,
			color 0.18s ease;
	}

	.chip.on {
		color: #fff;
		background: var(--accent);
		border-color: var(--accent);
	}

	.cards {
		display: flex;
		flex-direction: column;
		gap: 8px;
		max-height: 68dvh;
		overflow-y: auto;
		padding-right: 2px;
	}

	.card {
		content-visibility: auto;
		contain-intrinsic-size: auto 58px;
		display: flex;
		align-items: center;
		gap: 11px;
		text-align: left;
		padding: 10px 12px;
		font: inherit;
		color: var(--text);
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-md);
		background: var(--glass-bg);
		cursor: pointer;
		transition:
			background 0.18s ease,
			border-color 0.18s ease,
			transform 0.15s var(--ease-spring);
	}

	.card:hover {
		background: var(--glass-bg-hover);
		transform: translateY(-1px);
	}

	.card.active {
		border-color: var(--accent);
		background: var(--accent-soft);
	}

	.card :global(.pin) {
		color: var(--accent);
		flex: none;
	}

	.ava {
		flex: none;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 38px;
		height: 38px;
		font-weight: 700;
		font-size: 16px;
		color: hsl(var(--h) 85% 82%);
		background: hsl(var(--h) 50% 24% / 0.75);
		border: 1px solid hsl(var(--h) 60% 45% / 0.45);
		border-radius: 12px;
	}

	.ava.big {
		width: 40px;
		height: 40px;
	}

	.txt {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.t,
	.sub {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.t {
		font-size: 14px;
	}

	.sub {
		font-size: 12.5px;
		color: var(--text-dim);
	}

	.empty,
	.placeholder {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 10px;
		padding: 36px 16px;
		text-align: center;
		color: var(--text-faint);
	}

	.placeholder {
		min-height: 50dvh;
		justify-content: center;
		border: 1px dashed var(--glass-border);
		border-radius: var(--radius-md);
	}

	.empty p,
	.placeholder p {
		margin: 0;
		font-size: 14px;
	}

	.muted {
		color: var(--text-faint);
		font-size: 13px;
	}

	.err {
		margin: 0 0 8px;
		font-size: 13px;
		color: var(--danger);
	}

	/* ---- деталі ---- */
	.bar {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-bottom: 12px;
	}

	.back {
		display: none;
	}

	.head {
		flex: 1;
		min-width: 0;
		margin: 0;
		font-size: 18px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.grp {
		display: inline-block;
		margin-bottom: 10px;
		padding: 2px 10px;
		font-size: 12px;
		font-weight: 600;
		color: var(--accent);
		background: var(--accent-soft);
		border-radius: 999px;
	}

	.icon,
	.mini {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex: none;
		color: var(--text-dim);
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-sm);
		cursor: pointer;
		text-decoration: none;
		transition:
			color 0.18s ease,
			border-color 0.18s ease,
			background 0.18s ease;
	}

	.icon {
		width: 34px;
		height: 34px;
	}

	.mini {
		width: 30px;
		height: 30px;
	}

	.icon:hover,
	.mini:hover {
		color: var(--text);
		border-color: var(--accent);
	}

	.icon.on,
	.mini.on,
	.mini.acc {
		color: var(--accent);
		border-color: var(--accent);
		background: var(--accent-soft);
	}

	.icon.danger:hover,
	.mini.danger:hover {
		color: var(--danger);
		border-color: var(--danger);
	}

	.top2 {
		display: grid;
		grid-template-columns: 1fr 200px;
		gap: 10px;
		margin-bottom: 12px;
	}

	.fld {
		display: flex;
		flex-direction: column;
		gap: 4px;
		min-width: 0;
	}

	.fld span,
	.lab {
		font-size: 11.5px;
		font-weight: 600;
		letter-spacing: 0.02em;
		color: var(--text-faint);
	}

	.fld input,
	.lbl,
	.val {
		width: 100%;
		box-sizing: border-box;
		padding: 8px 11px;
		font: inherit;
		font-size: 14px;
		color: var(--text);
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-sm);
		outline: 0;
		transition: border-color 0.2s ease;
	}

	.fld input:focus,
	.lbl:focus,
	.val:focus {
		border-color: var(--accent);
	}

	textarea.val {
		resize: vertical;
		line-height: 1.5;
	}

	.fields {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.fields.dragging {
		-webkit-user-select: none;
		user-select: none;
	}

	.row {
		display: flex;
		align-items: flex-start;
		gap: 9px;
		padding: 10px 11px;
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-md);
		transition:
			box-shadow 0.2s ease,
			border-color 0.2s ease;
	}

	.row.drag {
		border-color: var(--accent);
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
		background: var(--glass-bg-hover);
	}

	.row :global(.kico) {
		flex: none;
		margin-top: 7px;
		color: var(--text-faint);
	}

	.grip {
		flex: none;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 22px;
		height: 30px;
		padding: 0;
		margin-top: 2px;
		color: var(--text-faint);
		background: none;
		border: 0;
		border-radius: 6px;
		cursor: grab;
		touch-action: none;
	}

	.grip:hover,
	.grip:focus-visible {
		color: var(--accent);
	}

	.row.drag .grip {
		cursor: grabbing;
	}

	.body {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 5px;
	}

	.lbl {
		padding: 4px 9px;
		font-size: 12px;
		font-weight: 600;
		color: var(--text-dim);
		background: none;
	}

	.valrow {
		display: flex;
		align-items: flex-start;
		gap: 6px;
	}

	.valrow .val {
		flex: 1;
		min-width: 0;
	}

	.read {
		flex: 1;
		min-width: 0;
		padding: 4px 0;
		font-size: 15px;
		overflow-wrap: anywhere;
	}

	.read.pre {
		white-space: pre-wrap;
		line-height: 1.5;
	}

	.read.mono {
		font-family: ui-monospace, 'Cascadia Mono', Consolas, monospace;
		letter-spacing: 0.02em;
	}

	.lnk {
		color: var(--accent);
		text-decoration: none;
	}

	.lnk:hover {
		text-decoration: underline;
	}

	.faint {
		color: var(--text-faint);
		font-size: 13px;
	}

	.gen {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 10px 18px;
		padding: 9px 12px;
		background: var(--surface-2);
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-sm);
		font-size: 13px;
	}

	.len {
		display: flex;
		align-items: center;
		gap: 8px;
		color: var(--text-dim);
	}

	.len input {
		accent-color: var(--accent);
	}

	.opts {
		display: flex;
		gap: 12px;
	}

	.opt {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		color: var(--text-dim);
		cursor: pointer;
	}

	.opt input {
		accent-color: var(--accent);
	}

	.addwrap {
		position: relative;
		margin-top: 10px;
	}

	.addf {
		padding: 8px 14px;
		font-size: 13px;
	}

	.menu {
		position: absolute;
		left: 0;
		top: calc(100% + 6px);
		z-index: 20;
		display: flex;
		flex-direction: column;
		min-width: 210px;
		padding: 6px;
		background: var(--surface-2);
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-md);
		box-shadow: var(--shadow-card);
		animation: vp-fade 0.14s ease;
	}

	.menu.up {
		top: auto;
		bottom: calc(100% + 6px);
	}

	.menu button {
		display: flex;
		align-items: center;
		gap: 9px;
		padding: 8px 10px;
		font: inherit;
		font-size: 14px;
		text-align: left;
		color: var(--text);
		background: none;
		border: 0;
		border-radius: 8px;
		cursor: pointer;
	}

	.menu button:hover {
		background: var(--accent-soft);
	}

	.actions {
		display: flex;
		justify-content: flex-end;
		gap: 10px;
		margin-top: 16px;
	}


	@keyframes vp-fade {
		from {
			opacity: 0;
		}
	}

	@media (max-width: 820px) {
		.split {
			grid-template-columns: 1fr;
		}

		.split.open .list,
		.split:not(.open) .detail {
			display: none;
		}

		.back {
			display: inline-flex;
		}

		.cards {
			max-height: none;
		}

		.top2 {
			grid-template-columns: 1fr;
		}
	}
</style>
