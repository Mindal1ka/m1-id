<script lang="ts">
	import { onMount } from 'svelte';
	import {
		Bold,
		Eraser,
		Heading1,
		Heading2,
		Heading3,
		Italic,
		Link2,
		List,
		ListChecks,
		ListOrdered,
		Minus,
		Paperclip,
		Quote,
		Redo2,
		SquareCode,
		Strikethrough,
		Undo2,
		Code
	} from '@lucide/svelte';
	import { safeUrl } from '$lib/sanitize';
	import { chipHtml, htmlToMarkdown, renderMarkdown, type ChipState } from './md';
	import { filesStore } from './files.svelte';

	/**
	 * «Звичайний» (Word-подібний) редактор нотаток. Тримає в DOM лише те, що
	 * вміє md.ts, а назовні віддає Markdown — тож режими «Звичайний» і
	 * «Markdown» перемикаються без втрат. Форматування — document.execCommand
	 * (ним користуються всі contenteditable-редактори); плюс Markdown-скорочення
	 * при наборі (`# `, `- `, `1. `, `> `, `[] `), Ctrl+B/I/K, чипи файлів.
	 */
	let {
		value,
		onchange,
		onattach,
		onopenfile,
		onfiles
	}: {
		value: string;
		onchange: (md: string) => void;
		/** Користувач натиснув «Прикріпити»: батько відкриє вибір файла. */
		onattach: () => void;
		onopenfile: (token: string) => void;
		/** Файли, кинуті/вставлені в редактор. */
		onfiles: (files: File[]) => void;
	} = $props();

	let el = $state<HTMLDivElement | null>(null);
	let lastMd = '';
	let empty = $state(true);
	let savedRange: Range | null = null;

	let fmt = $state({
		bold: false,
		italic: false,
		strike: false,
		ul: false,
		ol: false,
		task: false,
		block: 'P'
	});

	let linkOpen = $state(false);
	let linkUrl = $state('');
	let linkErr = $state('');
	let linkInput = $state<HTMLInputElement | null>(null);

	function resolve(token: string): ChipState {
		return filesStore.map.get(token) ?? (filesStore.loaded ? null : 'loading');
	}

	const EMPTY_DOC = '<p><br></p>';

	function render(md: string): void {
		if (!el) return;
		el.innerHTML = md.trim() ? renderMarkdown(md, { resolve }) : EMPTY_DOC;
		lastMd = md;
		empty = !md.trim();
	}

	// зовнішня зміна тексту (інша нотатка, перемикання режиму)
	$effect(() => {
		if (el && value !== lastMd) render(value);
	});

	// список файлів дозавантажився / змінився → оновити чипи на місці
	$effect(() => {
		void filesStore.map;
		void filesStore.loaded;
		if (!el) return;
		for (const c of Array.from(el.querySelectorAll<HTMLElement>('[data-ftoken]'))) {
			const tpl = document.createElement('template');
			tpl.innerHTML = chipHtml(c.dataset.ftoken ?? '', resolve(c.dataset.ftoken ?? ''));
			const fresh = tpl.content.firstElementChild;
			if (fresh && fresh.outerHTML !== c.outerHTML) c.replaceWith(fresh);
		}
	});

	onMount(() => {
		try {
			document.execCommand('defaultParagraphSeparator', false, 'p');
			document.execCommand('styleWithCSS', false, 'false');
		} catch {
			/* не критично */
		}
		document.addEventListener('selectionchange', updateFmt);
		return () => document.removeEventListener('selectionchange', updateFmt);
	});

	// ---------------------------------------------------------------- стан

	function inEditor(n: Node | null): boolean {
		return !!el && !!n && el.contains(n);
	}

	function closestEl(n: Node | null, sel: string): HTMLElement | null {
		let cur: Node | null = n;
		while (cur && cur !== el) {
			if (cur.nodeType === 1 && (cur as HTMLElement).matches(sel)) return cur as HTMLElement;
			cur = cur.parentNode;
		}
		return null;
	}

	function updateFmt(): void {
		const sel = getSelection();
		if (!sel || !sel.anchorNode || !inEditor(sel.anchorNode)) return;
		const li = closestEl(sel.anchorNode, 'li');
		const h = closestEl(sel.anchorNode, 'h1,h2,h3,blockquote,pre');
		fmt = {
			bold: document.queryCommandState('bold'),
			italic: document.queryCommandState('italic'),
			strike: document.queryCommandState('strikeThrough'),
			ul: !!li && li.parentElement?.tagName === 'UL' && !li.classList.contains('task'),
			ol: !!li && li.parentElement?.tagName === 'OL',
			task: !!li && li.classList.contains('task'),
			block: h ? h.tagName : 'P'
		};
	}

	/** Приводить DOM до того, що розуміє md.ts, і віддає Markdown батькові. */
	function normalize(): void {
		if (!el) return;
		const sel = getSelection();
		for (const li of Array.from(el.querySelectorAll('li'))) {
			const has = li.querySelector(':scope > .tcheck');
			if (li.classList.contains('task')) {
				if (!has) {
					// курсор на самому початку порожнього пункту має опинитись ПІСЛЯ чекбокса
					const caretAtStart = !!sel && sel.isCollapsed && sel.anchorNode === li && sel.anchorOffset === 0;
					const s = document.createElement('span');
					s.className = 'tcheck';
					s.contentEditable = 'false';
					li.prepend(s);
					if (caretAtStart) sel!.collapse(li, 1);
				}
			} else if (has) has.remove();
		}
		// сміття від браузера: <font>, <span style=…>
		for (const n of Array.from(el.querySelectorAll('font, span[style]:not([data-ftoken])'))) {
			n.replaceWith(...Array.from(n.childNodes));
		}
	}

	function emit(): void {
		if (!el) return;
		normalize();
		const md = htmlToMarkdown(el);
		empty = !el.textContent?.trim() && !el.querySelector('[data-ftoken], hr');
		if (md !== lastMd) {
			lastMd = md;
			onchange(md);
		}
		updateFmt();
	}

	// ---------------------------------------------------------------- команди

	function run(cmd: string, val?: string): void {
		el?.focus();
		document.execCommand(cmd, false, val);
		emit();
	}

	function setBlock(tag: 'H1' | 'H2' | 'H3' | 'BLOCKQUOTE' | 'PRE'): void {
		run('formatBlock', `<${fmt.block === tag ? 'P' : tag}>`);
	}

	function selectedLis(): HTMLElement[] {
		const sel = getSelection();
		if (!el || !sel || !sel.rangeCount) return [];
		return Array.from(el.querySelectorAll<HTMLElement>('li')).filter((li) =>
			sel.containsNode(li, true)
		);
	}

	function toggleTask(): void {
		el?.focus();
		if (!selectedLis().length) document.execCommand('insertUnorderedList');
		const lis = selectedLis();
		const makeTask = !lis.every((li) => li.classList.contains('task'));
		for (const li of lis) {
			if (li.parentElement?.tagName === 'OL') continue;
			li.classList.toggle('task', makeTask);
			if (!makeTask) li.classList.remove('done');
		}
		emit();
	}

	function toggleInlineCode(): void {
		const sel = getSelection();
		if (!el || !sel || !sel.rangeCount || !inEditor(sel.anchorNode)) return;
		const code = closestEl(sel.anchorNode, 'code');
		if (code && !closestEl(code, 'pre')) {
			code.replaceWith(...Array.from(code.childNodes));
		} else if (!sel.isCollapsed) {
			const r = sel.getRangeAt(0);
			const c = document.createElement('code');
			c.appendChild(r.extractContents());
			r.insertNode(c);
			sel.selectAllChildren(c);
		}
		emit();
	}

	function clearFormat(): void {
		el?.focus();
		document.execCommand('removeFormat');
		document.execCommand('formatBlock', false, '<P>');
		emit();
	}

	// ---------------------------------------------------------------- посилання

	function saveSel(): void {
		const sel = getSelection();
		if (sel && sel.rangeCount && inEditor(sel.anchorNode)) savedRange = sel.getRangeAt(0).cloneRange();
	}

	function restoreSel(): void {
		el?.focus();
		const sel = getSelection();
		if (sel && savedRange) {
			sel.removeAllRanges();
			sel.addRange(savedRange);
		}
	}

	async function openLink(): Promise<void> {
		saveSel();
		linkUrl = '';
		linkErr = '';
		linkOpen = true;
		await Promise.resolve();
		setTimeout(() => linkInput?.focus(), 0);
	}

	function applyLink(): void {
		let u = linkUrl.trim();
		if (!u) return void (linkOpen = false);
		if (!/^[a-z][a-z0-9+.-]*:/i.test(u)) u = 'https://' + u;
		if (safeUrl(u) === '#') {
			linkErr = 'Це посилання небезпечне або некоректне';
			return;
		}
		restoreSel();
		const sel = getSelection();
		if (sel && sel.isCollapsed) {
			const t = u.replace(/^https?:\/\//, '');
			document.execCommand(
				'insertHTML',
				false,
				`<a href="${u.replace(/"/g, '%22')}">${t.replace(/[<>&]/g, '')}</a>&nbsp;`
			);
		} else {
			document.execCommand('createLink', false, u);
		}
		linkOpen = false;
		emit();
	}

	// ---------------------------------------------------------------- файли

	/** Викликає батько, коли файл обрано: вставляє чип на місце курсора. */
	export function insertFile(token: string): void {
		if (!el) return;
		restoreSel();
		if (!inEditor(getSelection()?.anchorNode ?? null)) {
			el.focus();
			const r = document.createRange();
			r.selectNodeContents(el);
			r.collapse(false);
			getSelection()?.removeAllRanges();
			getSelection()?.addRange(r);
		}
		document.execCommand('insertHTML', false, chipHtml(token, resolve(token)) + '&nbsp;');
		emit();
	}

	function attach(): void {
		saveSel();
		onattach();
	}

	// ---------------------------------------------------------------- події

	function tryShortcut(): boolean {
		const sel = getSelection();
		if (!el || !sel || !sel.isCollapsed || !sel.anchorNode || !inEditor(sel.anchorNode)) return false;
		const blk = closestEl(sel.anchorNode, 'p, div, li');
		if (!blk || closestEl(blk, 'pre, h1, h2, h3')) return false;
		const r = document.createRange();
		r.selectNodeContents(blk);
		r.setEnd(sel.anchorNode, sel.anchorOffset);
		const before = r.toString();
		let action: (() => void) | null = null;
		if (/^#{1,3}$/.test(before)) {
			const lvl = before.length;
			action = () => document.execCommand('formatBlock', false, `<H${lvl}>`);
		} else if (/^[-*]$/.test(before) && !closestEl(blk, 'li')) {
			action = () => document.execCommand('insertUnorderedList');
		} else if (/^\d+\.$/.test(before) && !closestEl(blk, 'li')) {
			action = () => document.execCommand('insertOrderedList');
		} else if (before === '>') {
			action = () => document.execCommand('formatBlock', false, '<BLOCKQUOTE>');
		} else if (/^\[ ?\]$/.test(before) && !closestEl(blk, 'li')) {
			action = () => {
				document.execCommand('insertUnorderedList');
				const li = closestEl(getSelection()?.anchorNode ?? null, 'li');
				if (li) li.classList.add('task');
			};
		}
		if (!action) return false;
		r.deleteContents();
		if (!blk.textContent && !blk.querySelector('br')) blk.innerHTML = '<br>';
		sel.collapse(blk, 0);
		action();
		emit();
		return true;
	}

	function onKeydown(e: KeyboardEvent): void {
		if (e.key === ' ' && !e.ctrlKey && !e.metaKey && !e.altKey) {
			if (tryShortcut()) e.preventDefault();
		} else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
			e.preventDefault();
			void openLink();
		}
	}

	function onClick(e: MouseEvent): void {
		const t = e.target as HTMLElement;
		const chip = t.closest<HTMLElement>('[data-ftoken]');
		if (chip) {
			e.preventDefault();
			if (!chip.classList.contains('missing')) onopenfile(chip.dataset.ftoken ?? '');
			return;
		}
		if (t.classList.contains('tcheck')) {
			e.preventDefault();
			t.closest('li')?.classList.toggle('done');
			emit();
		}
	}

	function onPaste(e: ClipboardEvent): void {
		const files = Array.from(e.clipboardData?.files ?? []);
		e.preventDefault();
		if (files.length) {
			onfiles(files);
			return;
		}
		const text = e.clipboardData?.getData('text/plain') ?? '';
		if (text) document.execCommand('insertText', false, text);
	}

	function onDragOver(e: DragEvent): void {
		if (e.dataTransfer?.types.includes('Files')) e.preventDefault();
	}

	function onDrop(e: DragEvent): void {
		const files = Array.from(e.dataTransfer?.files ?? []);
		if (!files.length) return;
		e.preventDefault();
		onfiles(files);
	}

	function onFocus(): void {
		if (el && !el.firstElementChild) el.innerHTML = EMPTY_DOC;
	}
</script>

<div class="rwrap">
	<div class="tb" role="toolbar" aria-label="Форматування">
		<div class="grp">
			<button class="b" title="Скасувати (Ctrl+Z)" aria-label="Скасувати" onmousedown={(e) => e.preventDefault()} onclick={() => run('undo')}><Undo2 size={16} /></button>
			<button class="b" title="Повторити (Ctrl+Y)" aria-label="Повторити" onmousedown={(e) => e.preventDefault()} onclick={() => run('redo')}><Redo2 size={16} /></button>
		</div>
		<div class="grp">
			<button class="b" class:on={fmt.block === 'H1'} title="Заголовок 1" aria-label="Заголовок 1" onmousedown={(e) => e.preventDefault()} onclick={() => setBlock('H1')}><Heading1 size={17} /></button>
			<button class="b" class:on={fmt.block === 'H2'} title="Заголовок 2" aria-label="Заголовок 2" onmousedown={(e) => e.preventDefault()} onclick={() => setBlock('H2')}><Heading2 size={17} /></button>
			<button class="b" class:on={fmt.block === 'H3'} title="Заголовок 3" aria-label="Заголовок 3" onmousedown={(e) => e.preventDefault()} onclick={() => setBlock('H3')}><Heading3 size={17} /></button>
		</div>
		<div class="grp">
			<button class="b" class:on={fmt.bold} title="Жирний (Ctrl+B)" aria-label="Жирний" onmousedown={(e) => e.preventDefault()} onclick={() => run('bold')}><Bold size={16} /></button>
			<button class="b" class:on={fmt.italic} title="Курсив (Ctrl+I)" aria-label="Курсив" onmousedown={(e) => e.preventDefault()} onclick={() => run('italic')}><Italic size={16} /></button>
			<button class="b" class:on={fmt.strike} title="Закреслений" aria-label="Закреслений" onmousedown={(e) => e.preventDefault()} onclick={() => run('strikeThrough')}><Strikethrough size={16} /></button>
			<button class="b" title="Код" aria-label="Код" onmousedown={(e) => e.preventDefault()} onclick={toggleInlineCode}><Code size={16} /></button>
		</div>
		<div class="grp">
			<button class="b" class:on={fmt.ul} title="Маркований список" aria-label="Маркований список" onmousedown={(e) => e.preventDefault()} onclick={() => run('insertUnorderedList')}><List size={16} /></button>
			<button class="b" class:on={fmt.ol} title="Нумерований список" aria-label="Нумерований список" onmousedown={(e) => e.preventDefault()} onclick={() => run('insertOrderedList')}><ListOrdered size={16} /></button>
			<button class="b" class:on={fmt.task} title="Список завдань" aria-label="Список завдань" onmousedown={(e) => e.preventDefault()} onclick={toggleTask}><ListChecks size={16} /></button>
		</div>
		<div class="grp">
			<button class="b" class:on={fmt.block === 'BLOCKQUOTE'} title="Цитата" aria-label="Цитата" onmousedown={(e) => e.preventDefault()} onclick={() => setBlock('BLOCKQUOTE')}><Quote size={16} /></button>
			<button class="b" class:on={fmt.block === 'PRE'} title="Блок коду" aria-label="Блок коду" onmousedown={(e) => e.preventDefault()} onclick={() => setBlock('PRE')}><SquareCode size={16} /></button>
			<button class="b" title="Розділювач" aria-label="Розділювач" onmousedown={(e) => e.preventDefault()} onclick={() => run('insertHorizontalRule')}><Minus size={16} /></button>
		</div>
		<div class="grp">
			<button class="b" title="Посилання (Ctrl+K)" aria-label="Посилання" onmousedown={(e) => e.preventDefault()} onclick={openLink}><Link2 size={16} /></button>
			<button class="b" title="Прибрати форматування" aria-label="Прибрати форматування" onmousedown={(e) => e.preventDefault()} onclick={clearFormat}><Eraser size={16} /></button>
		</div>
		<button class="attach" onmousedown={(e) => e.preventDefault()} onclick={attach}>
			<Paperclip size={15} /> Прикріпити файл
		</button>
	</div>

	{#if linkOpen}
		<div class="linkbar">
			<Link2 size={15} />
			<input
				bind:this={linkInput}
				bind:value={linkUrl}
				placeholder="https://…"
				aria-label="Адреса посилання"
				onkeydown={(e) => {
					if (e.key === 'Enter') {
						e.preventDefault();
						applyLink();
					} else if (e.key === 'Escape') {
						e.preventDefault();
						linkOpen = false;
						restoreSel();
					}
				}}
			/>
			<button class="btn btn-primary sm" onclick={applyLink}>Додати</button>
			<button class="btn sm" onclick={() => { linkOpen = false; restoreSel(); }}>Скасувати</button>
			{#if linkErr}<span class="lerr">{linkErr}</span>{/if}
		</div>
	{/if}

	<div class="area">
		{#if empty}
			<div class="ph" aria-hidden="true">
				Пиши тут… Працюють скорочення: <code>#</code> заголовок, <code>-</code> список, <code>[]</code> завдання,
				<code>&gt;</code> цитата
			</div>
		{/if}
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<div
			bind:this={el}
			class="m1md rt"
			contenteditable="true"
			role="textbox"
			aria-multiline="true"
			aria-label="Текст нотатки"
			tabindex="0"
			spellcheck="true"
			oninput={emit}
			onkeydown={onKeydown}
			onkeyup={updateFmt}
			onclick={onClick}
			onpaste={onPaste}
			ondragover={onDragOver}
			ondrop={onDrop}
			onfocus={onFocus}
			onblur={emit}
		></div>
	</div>
</div>

<style>
	.rwrap {
		display: flex;
		flex-direction: column;
	}

	.tb {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px 10px;
		padding: 6px 8px;
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-bottom: 0;
		border-radius: var(--radius-md) var(--radius-md) 0 0;
	}

	.grp {
		display: inline-flex;
		gap: 2px;
		padding-right: 10px;
		border-right: 1px solid var(--glass-border);
	}

	.b {
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

	.b:hover {
		color: var(--text);
		background: var(--glass-bg-hover);
	}

	.b.on {
		color: var(--accent);
		background: var(--accent-soft);
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

	.linkbar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
		padding: 8px 10px;
		color: var(--text-dim);
		background: var(--surface-2);
		border: 1px solid var(--glass-border);
		border-bottom: 0;
	}

	.linkbar input {
		flex: 1;
		min-width: 160px;
		padding: 6px 10px;
		font: inherit;
		font-size: 14px;
		color: var(--text);
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: 8px;
		outline: 0;
	}

	.linkbar input:focus {
		border-color: var(--accent);
	}

	.sm {
		padding: 5px 12px;
		font-size: 13px;
	}

	.lerr {
		width: 100%;
		font-size: 12px;
		color: var(--danger);
	}

	.area {
		position: relative;
	}

	.ph {
		position: absolute;
		inset: 12px 16px auto 16px;
		font-size: 15px;
		line-height: 1.65;
		color: var(--text-faint);
		pointer-events: none;
	}

	.ph code {
		padding: 0 5px;
		font-size: 0.85em;
		background: var(--glass-bg-hover);
		border-radius: 5px;
	}
</style>
