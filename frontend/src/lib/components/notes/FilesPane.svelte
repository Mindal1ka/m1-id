<script lang="ts">
	import { confirm } from '$lib/ui';
	import { showToast } from '$lib/stores/toast.svelte';
	import {
		Copy,
		CloudUpload,
		Download,
		Eye,
		FileText,
		Files,
		NotebookPen,
		Pencil,
		Search,
		Trash2
	} from '@lucide/svelte';
	import { api, type FileItem } from '$lib/api/client';
	import AppModal from '$lib/components/AppModal.svelte';
	import { friendlyError } from '$lib/errors';
	import FilePreview from './FilePreview.svelte';
	import UploadForm from './UploadForm.svelte';
	import { badgeOf, catOf, fmtDate, fmtSize, isImage, type FileCat } from './fileUtils';
	import { filesStore } from './files.svelte';
	import type { Action } from 'svelte/action';
	import type { TransitionConfig } from 'svelte/transition';
	import { backOut, cubicOut } from 'svelte/easing';
	import { blurFade, motionOK, pressable, spotlight, stagger } from '$lib/motion';

	let { account }: { account: number } = $props();

	/** Новий файл «влітає»: масштаб + підйом (лише transform/opacity, без blur у списку). */
	function flyIn(_node: Element, { duration = 420 } = {}): TransitionConfig {
		if (!motionOK()) return { duration: 0 };
		return {
			duration,
			easing: backOut,
			css: (t, u) =>
				`opacity:${Math.min(1, t * 1.8)};transform:translateY(${u * 14}px) scale(${0.86 + 0.14 * t})`
		};
	}

	/** Видалений файл зменшується й розчиняється. */
	function scaleOut(_node: Element, { duration = 240 } = {}): TransitionConfig {
		if (!motionOK()) return { duration: 0 };
		return {
			duration,
			easing: cubicOut,
			css: (t, u) => `opacity:${t};transform:scale(${0.8 + 0.2 * t})`
		};
	}

	type Filter = 'all' | FileCat;
	const FILTERS: { key: Filter; label: string }[] = [
		{ key: 'all', label: 'Усі' },
		{ key: 'img', label: 'Зображення' },
		{ key: 'doc', label: 'Документи' },
		{ key: 'arc', label: 'Архіви' },
		{ key: 'media', label: 'Медіа' },
		{ key: 'other', label: 'Інше' }
	];

	let q = $state('');
	/** Відкладений запит (~150мс): фільтр великого списку не біжить на кожну літеру. */
	let qd = $state('');
	$effect(() => {
		const v = q;
		const t = setTimeout(() => (qd = v), 150);
		return () => clearTimeout(t);
	});

	/** Прожектор лише на коротких сітках (до ~20 карток). */
	const spotShort: Action<HTMLElement> = (node) =>
		shown.length <= 20 ? spotlight(node) : undefined;

	/** Плавна поява картинки після завантаження (лише opacity). */
	const fadeImg: Action<HTMLImageElement> = (node) => {
		if (node.complete) return;
		node.style.opacity = '0';
		const done = () => {
			node.style.transition = 'opacity .3s ease';
			node.style.opacity = '';
		};
		node.addEventListener('load', done, { once: true });
		node.addEventListener('error', done, { once: true });
	};
	let filter = $state<Filter>('all');
	let uploadOpen = $state(false);
	let sel = $state<FileItem | null>(null);
	let editName = $state('');
	let editDesc = $state('');
	let saving = $state(false);
	let err = $state('');
	let preview = $state<{ url: string; name: string } | null>(null);
	let broken = $state<Record<string, boolean>>({});

	void filesStore.load();

	const shown = $derived.by(() => {
		const s = qd.trim().toLowerCase();
		return filesStore.items.filter((f) => {
			const cat = catOf(f);
			if (filter !== 'all' && (filter === 'other' ? !['other', 'code'].includes(cat) : cat !== filter))
				return false;
			return (
				!s ||
				f.name.toLowerCase().includes(s) ||
				f.description.toLowerCase().includes(s) ||
				f.orig_name.toLowerCase().includes(s)
			);
		});
	});

	const dirty = $derived(
		!!sel && (editName.trim() !== sel.name || editDesc.trim() !== sel.description)
	);

	function flash(msg: string): void {
		showToast(msg, 2600);
	}

	function openFile(f: FileItem): void {
		sel = f;
		editName = f.name;
		editDesc = f.description;
		err = '';
	}

	async function copy(text: string, what: string): Promise<void> {
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
		flash(`${what} скопійовано`);
	}

	async function save(): Promise<void> {
		if (!sel || saving) return;
		saving = true;
		err = '';
		try {
			const f = await api.fileUpdate(sel.token, {
				name: editName.trim(),
				description: editDesc.trim()
			});
			filesStore.upsert(f);
			sel = f;
			editName = f.name;
			editDesc = f.description;
			flash('Збережено ✓');
		} catch (e) {
			err = friendlyError(e);
		} finally {
			saving = false;
		}
	}

	async function remove(): Promise<void> {
		if (!sel) return;
		const used = sel.notes.length;
		const msg =
			(used
				? `Файл прикріплено до нотаток (${used}): там він покаже «файл недоступний». `
				: '') +
			'На сервері IT Step файл не видаляється — зникне лише запис у M1 ID.';
		const ok = await confirm({
			title: `Видалити «${sel.name}»?`,
			message: msg,
			confirmText: 'Видалити',
			danger: true
		});
		if (!ok || !sel) return;
		const f = sel;
		try {
			const r = await api.fileDelete(f.token, account);
			filesStore.remove(f.token);
			sel = null;
			flash(
				r.remote_deleted
					? 'Файл видалено в M1 ID і на сервері IT Step'
					: 'Видалено в M1 ID (на сервері IT Step файл лишається)'
			);
		} catch (e) {
			err = friendlyError(e);
		}
	}
</script>

<div class="fp">
	<div class="tools">
		<label class="search">
			<Search size={15} />
			<input placeholder="Пошук файлів…" bind:value={q} aria-label="Пошук файлів" />
		</label>
		<button class="btn btn-primary" use:pressable onclick={() => (uploadOpen = true)}>
			<CloudUpload size={16} /> Завантажити
		</button>
	</div>

	<div class="chips">
		{#each FILTERS as f (f.key)}
			<button class="chip" class:on={filter === f.key} onclick={() => (filter = f.key)}>{f.label}</button>
		{/each}
	</div>

	{#if filesStore.error}<p class="err" role="alert">⚠ {filesStore.error}</p>{/if}

	{#if filesStore.loading && !filesStore.loaded}
		<p class="muted">Завантаження…</p>
	{:else if shown.length === 0}
		<div class="empty" in:blurFade={{ duration: 340, amount: 6 }}>
			<Files size={34} />
			<p>{q.trim() || filter !== 'all' ? 'Нічого не знайдено' : 'Файлів ще немає'}</p>
			{#if !q.trim() && filter === 'all'}
				<small>Завантаж файл — він отримає токен, і його можна прикріпити до будь-якої нотатки.</small>
				<button class="btn btn-primary" onclick={() => (uploadOpen = true)}>Завантажити перший</button>
			{/if}
		</div>
	{:else}
		<div class="grid" use:stagger={{ step: 32, max: 12, scale: true }}>
			{#each shown as f (f.token)}
				<div
					class="card"
					use:spotShort
					in:flyIn
					out:scaleOut
				>
					<button class="main" onclick={() => openFile(f)} aria-label="Відкрити «{f.name}»">
						<span class="thumb {catOf(f)}">
							{#if isImage(f) && !broken[f.token]}
								<img src={f.url} alt="" loading="lazy" decoding="async" use:fadeImg onerror={() => (broken[f.token] = true)} />
							{:else}
								<span class="big">{badgeOf(f)}</span>
							{/if}
						</span>
						<span class="body">
							<b class="t">{f.name}</b>
							<span class="d">{f.description || (f.kind === 'zip' ? `${f.parts.length} файлів в архіві` : '—')}</span>
							<span class="m">{fmtSize(f.size)} · {fmtDate(f.created_at)}</span>
						</span>
					</button>
					<div class="foot">
						<button class="tok" title="Скопіювати file:{f.token}" onclick={() => copy(`file:${f.token}`, 'Токен')}>
							<code>file:{f.token}</code>
							<Copy size={13} />
						</button>
						{#if f.notes.length}
							<span class="used" title={f.notes.map((n) => n.title || 'Без назви').join(', ')}>
								<NotebookPen size={12} />{f.notes.length}
							</span>
						{/if}
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>

<AppModal open={uploadOpen} title="Завантажити файл" icon={CloudUpload} tone="accent" width={520} onclose={() => (uploadOpen = false)}>
	{#key uploadOpen}
		<UploadForm
			{account}
			onuploaded={(f) => {
				uploadOpen = false;
				flash(`«${f.name}» завантажено ✓`);
			}}
			oncancel={() => (uploadOpen = false)}
		/>
	{/key}
</AppModal>

<AppModal open={!!sel} title={sel?.name ?? ''} icon={FileText} tone="cyan" width={560} onclose={() => (sel = null)}>
	{#if sel}
		<div class="det" in:blurFade={{ duration: 340, amount: 6, y: 6 }}>
			{#if isImage(sel) && !broken[sel.token]}
				<img class="pic" src={sel.url} alt="" onerror={() => (broken[sel!.token] = true)} />
			{/if}

			<div class="meta">
				<span class="bx {catOf(sel)}">{badgeOf(sel)}</span>
				<span>{fmtSize(sel.size)}</span>
				<span>·</span>
				<span>{fmtDate(sel.created_at)}</span>
			</div>

			<label class="fld">
				<span>Назва</span>
				<input bind:value={editName} maxlength="200" />
			</label>
			<label class="fld">
				<span>Опис</span>
				<textarea bind:value={editDesc} rows="2" maxlength="2000"></textarea>
			</label>

			<div class="tokrow">
				<code>file:{sel.token}</code>
				<button class="btn sm" onclick={() => copy(`file:${sel!.token}`, 'Токен')}><Copy size={14} /> Токен</button>
				<button class="btn sm" onclick={() => copy(sel!.url, 'Посилання')}><Copy size={14} /> Посилання</button>
			</div>
			<p class="hint">
				Встав <code>file:{sel.token}</code> у нотатку (режим Markdown) — з'явиться картка файлу. У «Звичайному» режимі
				достатньо кнопки «Прикріпити файл».
			</p>

			{#if sel.kind === 'zip'}
				<div class="parts">
					<b>В архіві ({sel.parts.length}):</b>
					{sel.parts.join(', ')}
				</div>
			{/if}

			{#if sel.notes.length}
				<div class="parts">
					<b>Використано в нотатках:</b>
					{sel.notes.map((n) => n.title || 'Без назви').join(', ')}
				</div>
			{/if}

			{#if err}<p class="err" role="alert">⚠ {err}</p>{/if}

			<div class="acts">
				<button class="btn" onclick={() => (preview = { url: sel!.url, name: sel!.name })}><Eye size={15} /> Переглянути</button>
				<a class="btn" href={sel.url} target="_blank" rel="noopener noreferrer" download={sel.orig_name}>
					<Download size={15} /> Завантажити
				</a>
				<button class="btn danger" onclick={remove}><Trash2 size={15} /> Видалити</button>
				<button class="btn btn-primary save" onclick={save} disabled={!dirty || saving}>
					<Pencil size={15} /> {saving ? 'Збереження…' : 'Зберегти'}
				</button>
			</div>
		</div>
	{/if}
</AppModal>

<FilePreview file={preview} onclose={() => (preview = null)} />


<style>
	.fp {
		display: flex;
		flex-direction: column;
		gap: 10px;
		min-height: 50dvh;
	}

	.tools {
		display: flex;
		gap: 8px;
	}

	.search {
		flex: 1;
		min-width: 0;
		display: flex;
		align-items: center;
		gap: 7px;
		padding: 0 11px;
		color: var(--text-faint);
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-sm);
		transition: border-color 0.2s ease;
	}

	.search:focus-within {
		border-color: var(--accent);
	}

	.search input {
		flex: 1;
		min-width: 0;
		padding: 9px 0;
		font: inherit;
		font-size: 14px;
		color: var(--text);
		background: none;
		border: 0;
		outline: 0;
	}

	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}

	.chip {
		padding: 4px 12px;
		font: inherit;
		font-size: 12px;
		font-weight: 600;
		color: var(--text-dim);
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: 999px;
		cursor: pointer;
		transition: background 0.18s ease, color 0.18s ease;
	}

	.chip.on {
		color: #fff;
		background: var(--accent);
		border-color: var(--accent);
	}

	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(215px, 1fr));
		gap: 12px;
	}

	.card {
		display: flex;
		flex-direction: column;
		overflow: hidden;
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-md);
		content-visibility: auto;
		contain-intrinsic-size: auto 210px;
		transition: border-color 0.18s ease, transform 0.15s var(--ease-spring);
	}

	.card:hover {
		border-color: var(--accent);
		transform: translateY(-2px);
		box-shadow: var(--shadow-card);
	}

	.main {
		display: flex;
		flex-direction: column;
		padding: 0;
		font: inherit;
		text-align: left;
		color: var(--text);
		background: none;
		border: 0;
		cursor: pointer;
	}

	.thumb {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 112px;
		aspect-ratio: 215 / 112;
		overflow: hidden;
		background: var(--glass-bg-hover);
	}

	.thumb img {
		width: 100%;
		height: 100%;
		object-fit: cover;
	}

	.big {
		padding: 8px 16px;
		font-size: 15px;
		font-weight: 800;
		letter-spacing: 0.06em;
		color: #fff;
		background: var(--text-faint);
		border-radius: 999px;
	}

	.thumb.img .big { background: #0ea5a4; }
	.thumb.doc .big { background: #4f7cff; }
	.thumb.arc .big { background: #d08a1d; }
	.thumb.media .big { background: #c05cd6; }
	.thumb.code .big { background: #3aa86b; }

	.body {
		display: flex;
		flex-direction: column;
		gap: 3px;
		padding: 10px 12px 6px;
	}

	.t {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 14px;
	}

	.d {
		min-height: 2.6em;
		font-size: 12.5px;
		line-height: 1.3;
		color: var(--text-dim);
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	.m {
		font-size: 11.5px;
		color: var(--text-faint);
	}

	.foot {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 6px;
		padding: 6px 10px 10px;
	}

	.tok {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		min-width: 0;
		padding: 3px 8px;
		font: inherit;
		color: var(--text-dim);
		background: var(--glass-bg-hover);
		border: 1px solid transparent;
		border-radius: 8px;
		cursor: pointer;
		transition: border-color 0.15s ease, color 0.15s ease;
	}

	.tok:hover {
		color: var(--accent);
		border-color: var(--accent);
	}

	.tok code {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 11.5px;
	}

	.used {
		display: inline-flex;
		align-items: center;
		gap: 3px;
		flex: none;
		padding: 2px 7px;
		font-size: 11.5px;
		font-weight: 600;
		color: var(--accent);
		background: var(--accent-soft);
		border-radius: 999px;
	}

	.empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 8px;
		padding: 44px 16px;
		text-align: center;
		color: var(--text-faint);
		border: 1px dashed var(--glass-border);
		border-radius: var(--radius-md);
	}

	.empty p {
		margin: 0;
		font-size: 14px;
	}

	.empty small {
		max-width: 340px;
		font-size: 12.5px;
	}

	.muted {
		margin: 8px 0;
		font-size: 13px;
		color: var(--text-faint);
	}

	.err {
		margin: 0;
		font-size: 13px;
		color: var(--danger);
	}

	/* ---- деталі ---- */
	.det {
		display: flex;
		flex-direction: column;
		gap: 11px;
	}

	.pic {
		width: 100%;
		max-height: 220px;
		object-fit: contain;
		background: var(--glass-bg-hover);
		border-radius: var(--radius-sm);
	}

	.meta {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 13px;
		color: var(--text-dim);
	}

	.bx {
		padding: 2px 9px;
		font-size: 11px;
		font-weight: 700;
		color: #fff;
		background: var(--text-faint);
		border-radius: 999px;
	}

	.bx.img { background: #0ea5a4; }
	.bx.doc { background: #4f7cff; }
	.bx.arc { background: #d08a1d; }
	.bx.media { background: #c05cd6; }
	.bx.code { background: #3aa86b; }

	.fld {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.fld span {
		font-size: 11.5px;
		font-weight: 600;
		color: var(--text-faint);
	}

	.fld input,
	.fld textarea {
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
		resize: vertical;
	}

	.fld input:focus,
	.fld textarea:focus {
		border-color: var(--accent);
	}

	.tokrow {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
	}

	.tokrow code {
		padding: 5px 10px;
		font-size: 13px;
		background: var(--glass-bg-hover);
		border-radius: 8px;
	}

	.sm {
		padding: 5px 11px;
		font-size: 12.5px;
	}

	.hint {
		margin: 0;
		font-size: 12.5px;
		line-height: 1.5;
		color: var(--text-faint);
	}

	.hint code {
		padding: 0 5px;
		background: var(--glass-bg-hover);
		border-radius: 5px;
	}

	.parts {
		font-size: 13px;
		line-height: 1.5;
		color: var(--text-dim);
	}

	.acts {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
	}

	.acts .btn {
		padding: 8px 14px;
		font-size: 13.5px;
		text-decoration: none;
	}

	.acts .danger:hover {
		color: var(--danger);
		border-color: var(--danger);
	}

	.acts .save {
		margin-left: auto;
	}


</style>
