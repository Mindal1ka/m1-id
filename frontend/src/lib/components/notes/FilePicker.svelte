<script lang="ts">
	import { Paperclip, Plus, Search } from '@lucide/svelte';
	import type { FileItem } from '$lib/api/client';
	import AppModal from '$lib/components/AppModal.svelte';
	import type { Action } from 'svelte/action';
	import UploadForm from './UploadForm.svelte';
	import { badgeOf, catOf, fmtSize } from './fileUtils';
	import { filesStore } from './files.svelte';
	import { blurFade, pressable, spotlight, stagger } from '$lib/motion';

	/**
	 * Вибір файла для прикріплення до нотатки: пошук серед своїх файлів
	 * або завантаження нового (кинуті в редактор файли відкривають форму
	 * одразу). Після завантаження файл прикріплюється автоматично.
	 */
	let {
		open,
		account,
		initialFiles = [],
		onpick,
		onclose
	}: {
		open: boolean;
		account: number;
		initialFiles?: File[];
		onpick: (f: FileItem) => void;
		onclose: () => void;
	} = $props();

	let q = $state('');
	/** Відкладений запит (~150мс). */
	let qd = $state('');
	$effect(() => {
		const v = q;
		const t = setTimeout(() => (qd = v), 150);
		return () => clearTimeout(t);
	});

	/** Прожектор лише на коротких списках (до ~20 рядків). */
	const spotShort: Action<HTMLElement> = (node) =>
		shown.length <= 20 ? spotlight(node) : undefined;
	let uploading = $state(false);

	$effect(() => {
		if (open) {
			void filesStore.load();
			uploading = initialFiles.length > 0;
			q = '';
			qd = '';
		}
	});

	const shown = $derived.by(() => {
		const s = qd.trim().toLowerCase();
		return filesStore.items.filter(
			(f) => !s || f.name.toLowerCase().includes(s) || f.description.toLowerCase().includes(s)
		);
	});
</script>

<AppModal {open} title="Прикріпити файл" icon={Paperclip} tone="accent" width={520} {onclose}>
	{#if uploading}
		{#key initialFiles}
			<div in:blurFade={{ duration: 320, amount: 0, y: 6 }}>
				<UploadForm
					{account}
					initial={initialFiles}
					onuploaded={(f) => {
						uploading = false;
						onpick(f);
					}}
					oncancel={() => (uploading = false)}
				/>
			</div>
		{/key}
	{:else}
		<div class="top" in:blurFade={{ duration: 300, amount: 5 }}>
			<label class="search">
				<Search size={15} />
				<input placeholder="Шукати свій файл…" bind:value={q} aria-label="Пошук файлу" />
			</label>
			<button class="btn btn-primary" use:pressable onclick={() => (uploading = true)}>
				<Plus size={16} /> Новий
			</button>
		</div>

		<div class="rows">
			{#if filesStore.loading && !filesStore.loaded}
				<p class="muted">Завантаження…</p>
			{:else if shown.length === 0}
				<p class="muted">
					{q.trim() ? 'Нічого не знайдено' : 'У тебе ще немає файлів — завантаж перший.'}
				</p>
			{:else}
				<div class="rl" use:stagger={{ step: 28, max: 10, y: 8 }}>
					{#each shown as f (f.token)}
						<button class="row" use:spotShort use:pressable={{ scale: 0.98 }} onclick={() => onpick(f)}>
							<span class="bx {catOf(f)}">{badgeOf(f)}</span>
							<span class="txt">
								<b>{f.name}</b>
								<small>{f.description || '—'}</small>
							</span>
							<span class="sz">{fmtSize(f.size)}</span>
						</button>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
</AppModal>

<style>
	.rl {
		display: contents;
	}

	.top {
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
		color: var(--text-faint);
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-sm);
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

	.rows {
		display: flex;
		flex-direction: column;
		gap: 6px;
		max-height: 52dvh;
		overflow-y: auto;
	}

	.row {
		display: flex;
		content-visibility: auto;
		contain-intrinsic-size: auto 54px;
		align-items: center;
		gap: 10px;
		padding: 9px 11px;
		font: inherit;
		text-align: left;
		color: var(--text);
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-md);
		cursor: pointer;
		transition: border-color 0.15s ease, background 0.15s ease;
	}

	.row:hover {
		border-color: var(--accent);
		background: var(--accent-soft);
	}

	.bx {
		flex: none;
		min-width: 36px;
		padding: 3px 7px;
		font-size: 10px;
		font-weight: 700;
		text-align: center;
		color: #fff;
		background: var(--text-faint);
		border-radius: 999px;
	}

	.bx.img { background: #0ea5a4; }
	.bx.doc { background: #4f7cff; }
	.bx.arc { background: #d08a1d; }
	.bx.media { background: #c05cd6; }
	.bx.code { background: #3aa86b; }

	.txt {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.txt b,
	.txt small {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.txt b {
		font-size: 14px;
	}

	.txt small {
		font-size: 12px;
		color: var(--text-dim);
	}

	.sz {
		flex: none;
		font-size: 12px;
		color: var(--text-faint);
	}

	.muted {
		margin: 8px 0;
		font-size: 13px;
		color: var(--text-faint);
		text-align: center;
	}
</style>
