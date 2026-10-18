<script lang="ts">
	import { confirm } from '$lib/ui';
	import { onDestroy, tick, untrack } from 'svelte';
	import {
		ArrowLeft,
		Bold,
		Check,
		Code,
		Eye,
		Heading2,
		Italic,
		Link2,
		List,
		ListChecks,
		NotebookPen,
		Paperclip,
		Pencil,
		Pin,
		Plus,
		Quote,
		Search,
		Strikethrough,
		Trash2,
		Type
	} from '@lucide/svelte';
	import { flip } from 'svelte/animate';
	import { blurFade, pop, pressable, springIn, stagger } from '$lib/motion';
	import { api, type NoteItem } from '$lib/api/client';
	import { friendlyError } from '$lib/errors';
	import FilePicker from './FilePicker.svelte';
	import FilePreview from './FilePreview.svelte';
	import RichEditor from './RichEditor.svelte';
	import { tokensIn } from './fileUtils';
	import { filesStore } from './files.svelte';
	import { chipHtml, renderMarkdown, type ChipState } from './md';

	let { account }: { account: number } = $props();

	/** Чернетка відкритої нотатки; id=null — ще не створена на сервері. */
	interface Draft {
		id: number | null;
		title: string;
		body: string;
		pinned: boolean;
	}

	/** rich — «звичайний» (Word-подібний), md — Markdown, view — читання. */
	type Mode = 'rich' | 'md' | 'view';
	const PREF_KEY = 'm1.notes.editor';

	function loadPref(): 'rich' | 'md' {
		try {
			return localStorage.getItem(PREF_KEY) === 'md' ? 'md' : 'rich';
		} catch {
			return 'rich';
		}
	}

	let items = $state<NoteItem[]>([]);
	let q = $state('');
	let loading = $state(true);
	let err = $state('');

	/** null — нічого не відкрито; інакше відкрито `draft`. */
	let draft = $state<Draft | null>(null);
	let editorPref = $state<'rich' | 'md'>(loadPref());
	let mode = $state<Mode>(untrack(() => editorPref));
	let docKey = $state(0);
	let status = $state<'idle' | 'saving' | 'saved' | 'error'>('idle');
	let titleEl = $state<HTMLInputElement | null>(null);
	let bodyEl = $state<HTMLTextAreaElement | null>(null);
	let rich = $state<{ insertFile: (token: string) => void } | null>(null);

	let pickerOpen = $state(false);
	let pickerFiles = $state<File[]>([]);
	let preview = $state<{ url: string; name: string } | null>(null);
	let dragging = $state(false);
	let caret = 0;

	let dirty = false;
	let saveTimer: ReturnType<typeof setTimeout> | undefined;
	let searchTimer: ReturnType<typeof setTimeout> | undefined;
	let inFlight: Promise<void> | null = null;

	function resolve(token: string): ChipState {
		return filesStore.map.get(token) ?? (filesStore.loaded ? null : 'loading');
	}

	/** Пульс елемента при монтуванні (галочка «збережено»). */
	function popIn(node: HTMLElement): void {
		pop(node, 1.45);
	}

	const html = $derived(draft ? renderMarkdown(draft.body, { resolve }) : '');
	const attached = $derived(draft ? tokensIn(draft.body) : []);

	void filesStore.load();

	async function loadList(): Promise<void> {
		try {
			items = (await api.notesList(q.trim())).items;
			err = '';
		} catch (e) {
			err = friendlyError(e);
		} finally {
			loading = false;
		}
	}
	void loadList();

	function onSearch(): void {
		clearTimeout(searchTimer);
		searchTimer = setTimeout(() => void loadList(), 250);
	}

	/** Перші ~12 слів — для картки в списку. */
	function snippet(n: NoteItem): string {
		const words = n.preview.split(' ').filter(Boolean);
		return words.slice(0, 12).join(' ') + (words.length > 12 ? '…' : '');
	}

	function fmtDate(iso: string): string {
		const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
		if (isNaN(d.getTime())) return '';
		return d.toLocaleDateString('uk-UA', { day: 'numeric', month: 'short' });
	}

	function touchItem(n: NoteItem): void {
		const i = items.findIndex((x) => x.id === n.id);
		if (i >= 0) items[i] = n;
		else items.unshift(n);
		items.sort(
			(a, b) =>
				Number(b.pinned) - Number(a.pinned) || b.updated_at.localeCompare(a.updated_at)
		);
	}

	/** Збереження: серіалізоване (одночасно лише один запит). */
	async function save(): Promise<void> {
		clearTimeout(saveTimer);
		if (inFlight) {
			await inFlight;
		}
		if (!draft || !dirty) return;
		if (draft.id === null && !draft.title.trim() && !draft.body.trim()) return;
		const snap = { ...draft };
		dirty = false;
		status = 'saving';
		let failed = false;
		inFlight = (async () => {
			try {
				const body = { title: snap.title, body: snap.body, pinned: snap.pinned };
				const saved =
					snap.id === null ? await api.noteCreate(body) : await api.noteUpdate(snap.id, body);
				if (draft && draft.id === null && snap.id === null) draft.id = saved.id;
				touchItem({ ...saved, body: undefined });
				status = dirty ? 'saving' : 'saved';
				void filesStore.load(true); // «використано в нотатках» у списку файлів
			} catch (e) {
				dirty = true;
				failed = true;
				status = 'error';
				err = friendlyError(e);
			}
		})();
		await inFlight;
		inFlight = null;
		if (dirty && !failed) void save();
	}

	function changed(): void {
		dirty = true;
		status = 'idle';
		clearTimeout(saveTimer);
		saveTimer = setTimeout(() => void save(), 700);
	}

	async function openNote(n: NoteItem): Promise<void> {
		await save();
		try {
			const full = await api.noteGet(n.id);
			draft = { id: full.id, title: full.title, body: full.body ?? '', pinned: full.pinned };
			mode = editorPref;
			docKey++;
			status = 'idle';
			dirty = false;
		} catch (e) {
			err = friendlyError(e);
		}
	}

	async function newNote(): Promise<void> {
		await save();
		draft = { id: null, title: '', body: '', pinned: false };
		mode = editorPref;
		docKey++;
		status = 'idle';
		dirty = false;
		await tick();
		titleEl?.focus();
	}

	async function closeNote(): Promise<void> {
		await save();
		draft = null;
	}

	async function togglePin(): Promise<void> {
		if (!draft) return;
		draft.pinned = !draft.pinned;
		changed();
	}

	async function remove(): Promise<void> {
		if (!draft) return;
		const ok = await confirm({
			title: 'Видалити нотатку?',
			message: 'Нотатку буде видалено без можливості відновлення.',
			confirmText: 'Видалити',
			danger: true
		});
		if (!ok) return;
		clearTimeout(saveTimer);
		dirty = false;
		const id = draft.id;
		draft = null;
		if (id !== null) {
			try {
				await inFlight;
				await api.noteDelete(id);
				items = items.filter((x) => x.id !== id);
				void filesStore.load(true);
			} catch (e) {
				err = friendlyError(e);
			}
		}
	}

	async function setMode(m: Mode): Promise<void> {
		mode = m;
		if (m !== 'view') {
			editorPref = m;
			try {
				localStorage.setItem(PREF_KEY, m);
			} catch {
				/* не критично */
			}
		}
		if (m === 'md') {
			await tick();
			bodyEl?.focus();
		}
	}

	// ---------------------------------------------------------------- Markdown-режим

	/** Обгортає виділене в textarea (або вставляє шаблон). */
	function wrap(before: string, after = before, ph = 'текст'): void {
		if (!draft || !bodyEl) return;
		const { selectionStart: s, selectionEnd: e, value } = bodyEl;
		const mid = value.slice(s, e) || ph;
		draft.body = value.slice(0, s) + before + mid + after + value.slice(e);
		changed();
		void tick().then(() => {
			bodyEl?.focus();
			bodyEl?.setSelectionRange(s + before.length, s + before.length + mid.length);
		});
	}

	/** Додає префікс до початку поточного рядка. */
	function linePrefix(prefix: string): void {
		if (!draft || !bodyEl) return;
		const s = bodyEl.selectionStart;
		const v = bodyEl.value;
		const start = v.lastIndexOf('\n', s - 1) + 1;
		draft.body = v.slice(0, start) + prefix + v.slice(start);
		changed();
		void tick().then(() => {
			bodyEl?.focus();
			bodyEl?.setSelectionRange(s + prefix.length, s + prefix.length);
		});
	}

	// ---------------------------------------------------------------- файли

	function openAttach(): void {
		caret = bodyEl?.selectionStart ?? draft?.body.length ?? 0;
		pickerFiles = [];
		pickerOpen = true;
	}

	function onDroppedFiles(files: File[]): void {
		if (!files.length || !draft) return;
		caret = bodyEl?.selectionStart ?? draft.body.length;
		pickerFiles = files;
		pickerOpen = true;
	}

	function onPick(f: { token: string }): void {
		pickerOpen = false;
		pickerFiles = [];
		if (!draft) return;
		if (mode === 'rich') {
			rich?.insertFile(f.token);
		} else {
			const v = draft.body;
			const at = Math.min(caret, v.length);
			const pre = at > 0 && !/\s$/.test(v.slice(0, at)) ? ' ' : '';
			const ins = `${pre}file:${f.token} `;
			draft.body = v.slice(0, at) + ins + v.slice(at);
			changed();
			void tick().then(() => {
				bodyEl?.focus();
				bodyEl?.setSelectionRange(at + ins.length, at + ins.length);
			});
		}
	}

	function openToken(token: string): void {
		const f = filesStore.map.get(token);
		if (f) preview = { url: f.url, name: f.name };
	}

	/** Чипи в тексті/нижній панелі та чекбокси в режимі читання. */
	function onViewClick(e: MouseEvent): void {
		const t = e.target as HTMLElement;
		const chip = t.closest<HTMLElement>('[data-ftoken]');
		if (chip) {
			if (!chip.classList.contains('missing')) openToken(chip.dataset.ftoken ?? '');
			return;
		}
		if (t.classList.contains('tcheck') && draft && mode === 'view') {
			const host = e.currentTarget as HTMLElement;
			const boxes = Array.from(host.querySelectorAll('.tcheck'));
			const idx = boxes.indexOf(t);
			draft.body = toggleNthTask(draft.body, idx);
			changed();
			// {@html} перерендерився — пульсуємо новий чекбокс
			void tick().then(() => {
				const b = host.querySelectorAll<HTMLElement>('.tcheck')[idx];
				if (b) pop(b, 1.35);
			});
		}
	}

	/** Перемикає n-й чекбокс `- [ ]` у Markdown (поза блоками коду). */
	function toggleNthTask(md: string, n: number): string {
		const lines = md.split('\n');
		let k = 0;
		let fence = false;
		for (let i = 0; i < lines.length; i++) {
			if (/^```/.test(lines[i])) fence = !fence;
			if (fence) continue;
			const m = lines[i].match(/^(\s*[-*+]\s+)\[( |x|X)\](\s+.*)$/);
			if (!m) continue;
			if (k++ === n) {
				lines[i] = `${m[1]}[${m[2] === ' ' ? 'x' : ' '}]${m[3]}`;
				break;
			}
		}
		return lines.join('\n');
	}

	function onDragOver(e: DragEvent): void {
		if (draft && mode !== 'view' && e.dataTransfer?.types.includes('Files')) {
			e.preventDefault();
			dragging = true;
		}
	}

	function onDrop(e: DragEvent): void {
		dragging = false;
		const files = Array.from(e.dataTransfer?.files ?? []);
		if (!files.length || !draft || mode === 'view') return;
		e.preventDefault();
		onDroppedFiles(files);
	}

	/** Ctrl/⌘+S — зберегти одразу. */
	function onKey(e: KeyboardEvent): void {
		if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's' && draft) {
			e.preventDefault();
			void save();
		}
	}

	onDestroy(() => {
		clearTimeout(searchTimer);
		clearTimeout(saveTimer);
		if (dirty) void save();
	});
</script>

<svelte:window onkeydown={onKey} />

<div class="split" class:open={draft !== null}>
	<aside class="list">
		<div class="tools">
			<label class="search">
				<Search size={15} />
				<input
					type="search"
					placeholder="Пошук нотаток…"
					bind:value={q}
					oninput={onSearch}
					aria-label="Пошук нотаток"
				/>
			</label>
			<button class="btn btn-primary add" use:pressable onclick={newNote}>
				<Plus size={16} /> Нова
			</button>
		</div>

		{#if err}<p class="err" role="alert">⚠ {err}</p>{/if}

		<div class="cards">
			{#if loading}
				<p class="muted">Завантаження…</p>
			{:else if items.length === 0}
				<div class="empty">
					<NotebookPen size={30} />
					<p>{q.trim() ? 'Нічого не знайдено' : 'Поки що немає нотаток'}</p>
					{#if !q.trim()}<button class="btn" onclick={newNote}>Створити першу</button>{/if}
				</div>
			{:else}
				<div class="cl" use:stagger={{ step: 30, max: 10, y: 8 }}>
					{#each items as n (n.id)}
						<button
							class="card"
							class:active={draft?.id === n.id}
							use:pressable={{ scale: 0.98 }}
							animate:flip={{ duration: 340 }}
							in:springIn={{ duration: 320, start: 0.96, y: 8 }}
							onclick={() => openNote(n)}
						>
							<span class="row1">
								<b class="t">{n.title || 'Без назви'}</b>
								{#if n.pinned}<span class="pinw" in:springIn={{ duration: 360, start: 0.4, y: 0 }}><Pin size={13} class="pin" /></span>{/if}
							</span>
							<span class="snip">{snippet(n) || 'Порожня нотатка'}</span>
							<span class="date">{fmtDate(n.updated_at)}</span>
						</button>
					{/each}
				</div>
			{/if}
		</div>
	</aside>

	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<section
		class="editor"
		class:drag={dragging}
		ondragover={onDragOver}
		ondragleave={() => (dragging = false)}
		ondrop={onDrop}
	>
		{#if draft}
			{#key docKey}
			<div class="doc" in:blurFade|global={{ duration: 360, amount: 0, y: 6 }}>
			<header class="bar">
				<button class="icon back" onclick={closeNote} aria-label="Назад до списку">
					<ArrowLeft size={18} />
				</button>
				<div class="seg" role="tablist" aria-label="Режим">
					<button
						role="tab"
						aria-selected={mode === 'rich'}
						class:on={mode === 'rich'}
						onclick={() => setMode('rich')}><Type size={14} /> Звичайний</button
					>
					<button
						role="tab"
						aria-selected={mode === 'md'}
						class:on={mode === 'md'}
						onclick={() => setMode('md')}><Pencil size={14} /> Markdown</button
					>
					<button
						role="tab"
						aria-selected={mode === 'view'}
						class:on={mode === 'view'}
						onclick={() => setMode('view')}><Eye size={14} /> Перегляд</button
					>
				</div>
				<span class="state" class:bad={status === 'error'}>
					{#key status}
						<span class="st" in:springIn={{ duration: 300, start: 0.7, y: 4 }}>
							{#if status === 'saving'}
								<i class="spin" aria-hidden="true"></i> Збереження…
							{:else if status === 'saved'}
								<span class="ck" use:popIn><Check size={14} strokeWidth={3} /></span> Збережено
							{:else if status === 'error'}
								Не збережено
							{/if}
						</span>
					{/key}
				</span>
				<button
					class="icon pinbtn"
					class:on={draft.pinned}
					onclick={togglePin}
					aria-label={draft.pinned ? 'Відкріпити' : 'Закріпити'}
					title={draft.pinned ? 'Відкріпити' : 'Закріпити'}
				>
					<Pin size={17} />
				</button>
				<button class="icon danger" onclick={remove} aria-label="Видалити" title="Видалити">
					<Trash2 size={17} />
				</button>
			</header>

			<input
				class="title"
				placeholder="Назва нотатки"
				maxlength="200"
				bind:this={titleEl}
				bind:value={draft.title}
				oninput={changed}
				readonly={mode === 'view'}
			/>

			{#if mode === 'rich'}
				{#key docKey}
					<RichEditor
						bind:this={rich}
						value={draft.body}
						onchange={(md) => {
							if (draft) draft.body = md;
							changed();
						}}
						onattach={openAttach}
						onopenfile={openToken}
						onfiles={onDroppedFiles}
					/>
				{/key}
			{:else if mode === 'md'}
				<div class="mdtb" role="toolbar" aria-label="Markdown">
					<button class="b" title="Жирний" aria-label="Жирний" onclick={() => wrap('**')}><Bold size={16} /></button>
					<button class="b" title="Курсив" aria-label="Курсив" onclick={() => wrap('*')}><Italic size={16} /></button>
					<button class="b" title="Закреслений" aria-label="Закреслений" onclick={() => wrap('~~')}><Strikethrough size={16} /></button>
					<button class="b" title="Код" aria-label="Код" onclick={() => wrap('`')}><Code size={16} /></button>
					<span class="sep"></span>
					<button class="b" title="Заголовок" aria-label="Заголовок" onclick={() => linePrefix('## ')}><Heading2 size={17} /></button>
					<button class="b" title="Список" aria-label="Список" onclick={() => linePrefix('- ')}><List size={16} /></button>
					<button class="b" title="Завдання" aria-label="Завдання" onclick={() => linePrefix('- [ ] ')}><ListChecks size={16} /></button>
					<button class="b" title="Цитата" aria-label="Цитата" onclick={() => linePrefix('> ')}><Quote size={16} /></button>
					<button class="b" title="Посилання" aria-label="Посилання" onclick={() => wrap('[', '](https://)', 'текст')}><Link2 size={16} /></button>
					<button class="attach" onclick={openAttach}><Paperclip size={15} /> Прикріпити файл</button>
				</div>
				<textarea
					class="body"
					placeholder="Markdown: # заголовок, **жирний**, - список, - [ ] завдання, file:ТОКЕН — прикріплений файл"
					maxlength="50000"
					bind:this={bodyEl}
					bind:value={draft.body}
					oninput={changed}
				></textarea>
			{:else}
				<!-- svelte-ignore a11y_click_events_have_key_events -->
				<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
				<article class="m1md view" onclick={onViewClick}>
					{#if draft.body.trim()}
						<!-- eslint-disable-next-line svelte/no-at-html-tags -->
						{@html html}
					{:else}
						<p class="muted">Порожньо. Обери «Звичайний» або «Markdown», щоб писати.</p>
					{/if}
				</article>
			{/if}

			{#if attached.length}
				<!-- svelte-ignore a11y_click_events_have_key_events -->
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<div class="files" onclick={onViewClick}>
					<span class="fl"><Paperclip size={14} /> Прикріплено ({attached.length})</span>
					<div class="m1md fl-chips">
						<!-- eslint-disable-next-line svelte/no-at-html-tags -->
						{@html attached.map((t) => chipHtml(t, resolve(t))).join(' ')}
					</div>
				</div>
			{/if}

			</div>
			{/key}

			{#if dragging}
				<div class="dropveil" in:blurFade={{ duration: 180, amount: 4 }}><Paperclip size={30} /> Відпусти, щоб прикріпити файл</div>
			{/if}
		{:else}
			<div class="placeholder" in:blurFade|global={{ duration: 360, amount: 6 }}>
				<NotebookPen size={42} />
				<p>Обери нотатку зі списку або створи нову</p>
			</div>
		{/if}
	</section>
</div>

<FilePicker
	open={pickerOpen}
	{account}
	initialFiles={pickerFiles}
	onpick={onPick}
	onclose={() => {
		pickerOpen = false;
		pickerFiles = [];
	}}
/>
<FilePreview file={preview} onclose={() => (preview = null)} />

<style>
	.split {
		display: grid;
		grid-template-columns: minmax(250px, 340px) 1fr;
		gap: 14px;
		min-height: 62dvh;
		align-items: start;
	}

	.list,
	.editor {
		min-width: 0;
	}

	.editor {
		position: relative;
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
		contain-intrinsic-size: auto 82px;
		display: flex;
		flex-direction: column;
		gap: 4px;
		text-align: left;
		padding: 11px 13px;
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

	.row1 {
		display: flex;
		align-items: center;
		gap: 6px;
	}

	.t {
		flex: 1;
		min-width: 0;
		font-size: 14px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.card :global(.pin) {
		color: var(--accent);
		flex: none;
	}

	.snip {
		font-size: 12.5px;
		line-height: 1.4;
		color: var(--text-dim);
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	.date {
		font-size: 11px;
		color: var(--text-faint);
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

	/* ---- редактор ---- */
	.bar {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-bottom: 10px;
	}

	.back {
		display: none;
	}

	.seg {
		display: inline-flex;
		padding: 3px;
		gap: 2px;
		border-radius: 999px;
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
	}

	.seg button {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 6px 12px;
		font: inherit;
		font-size: 13px;
		font-weight: 600;
		color: var(--text-dim);
		background: none;
		border: 0;
		border-radius: 999px;
		cursor: pointer;
		transition:
			background 0.18s ease,
			color 0.18s ease;
	}

	.seg button.on {
		background: var(--accent);
		color: #fff;
	}

	.state {
		margin-left: auto;
		font-size: 12px;
		color: var(--text-faint);
		white-space: nowrap;
	}

	.state.bad {
		color: var(--danger);
	}

	.cl {
		display: contents;
	}

	.pinw {
		display: inline-flex;
	}

	.st {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}

	.ck {
		display: inline-flex;
		color: var(--success);
	}

	/* крутилка «зберігаю» — лише transform */
	.spin {
		width: 12px;
		height: 12px;
		border-radius: 50%;
		border: 2px solid color-mix(in srgb, var(--accent) 25%, transparent);
		border-top-color: var(--accent);
		animation: np-spin 0.7s linear infinite;
	}

	@keyframes np-spin {
		to {
			transform: rotate(360deg);
		}
	}

	:global(html[data-anim='off']) .spin {
		animation: none;
	}

	.icon {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex: none;
		width: 34px;
		height: 34px;
		color: var(--text-dim);
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-sm);
		cursor: pointer;
		transition:
			color 0.18s ease,
			border-color 0.18s ease;
	}

	.icon:hover {
		color: var(--text);
		border-color: var(--accent);
	}

	.icon.on {
		color: var(--accent);
		border-color: var(--accent);
		background: var(--accent-soft);
	}

	.icon.danger:hover {
		color: var(--danger);
		border-color: var(--danger);
	}

	.title {
		width: 100%;
		box-sizing: border-box;
		margin-bottom: 10px;
		padding: 10px 2px;
		font: inherit;
		font-family: var(--font-display);
		font-size: 20px;
		font-weight: 700;
		color: var(--text);
		background: none;
		border: 0;
		border-bottom: 1px solid var(--glass-border);
		outline: 0;
		transition: border-color 0.2s ease;
	}

	.title:focus {
		border-color: var(--accent);
	}

	/* ---- Markdown-режим ---- */
	.mdtb {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 2px;
		padding: 6px 8px;
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-bottom: 0;
		border-radius: var(--radius-md) var(--radius-md) 0 0;
	}

	.mdtb .b {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 30px;
		height: 30px;
		color: var(--text-dim);
		background: none;
		border: 0;
		border-radius: 8px;
		cursor: pointer;
		transition: background 0.15s ease, color 0.15s ease;
	}

	.mdtb .b:hover {
		color: var(--text);
		background: var(--glass-bg-hover);
	}

	.sep {
		width: 1px;
		height: 18px;
		margin: 0 6px;
		background: var(--glass-border);
	}

	.attach {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		margin-left: auto;
		padding: 6px 12px;
		font: inherit;
		font-size: 13px;
		font-weight: 600;
		color: var(--accent);
		background: var(--accent-soft);
		border: 1px solid transparent;
		border-radius: 999px;
		cursor: pointer;
		transition: border-color 0.15s ease;
	}

	.attach:hover {
		border-color: var(--accent);
	}

	.body {
		width: 100%;
		box-sizing: border-box;
		min-height: 46dvh;
		padding: 12px 14px;
		font-family: ui-monospace, 'Cascadia Mono', Consolas, monospace;
		font-size: 14px;
		line-height: 1.6;
		color: var(--text);
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: 0 0 var(--radius-md) var(--radius-md);
		outline: 0;
		resize: vertical;
		transition: border-color 0.2s ease;
	}

	.body:focus {
		border-color: var(--accent);
	}

	.view {
		min-height: 40dvh;
		padding: 4px 2px;
	}

	/* ---- прикріплені файли ---- */
	.files {
		display: flex;
		flex-direction: column;
		gap: 6px;
		margin-top: 12px;
		padding: 10px 12px;
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-md);
	}

	.fl {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 12px;
		font-weight: 600;
		color: var(--text-faint);
	}

	.fl-chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}

	.dropveil {
		position: absolute;
		inset: 0;
		z-index: 5;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 10px;
		font-weight: 600;
		color: var(--accent);
		background: color-mix(in srgb, var(--bg) 78%, transparent);
		border: 2px dashed var(--accent);
		border-radius: var(--radius-md);
		pointer-events: none;
	}

	@media (max-width: 820px) {
		.split {
			grid-template-columns: 1fr;
		}

		.split.open .list,
		.split:not(.open) .editor {
			display: none;
		}

		.back {
			display: inline-flex;
		}

		.cards {
			max-height: none;
		}

		.bar {
			flex-wrap: wrap;
		}

		.bar .seg {
			order: 5;
			flex: 1 1 100%;
		}

		.seg button {
			flex: 1;
			justify-content: center;
			padding: 6px 6px;
			font-size: 12.5px;
		}

		.pinbtn {
			margin-left: auto;
		}

		.state {
			display: none;
		}
	}
</style>
