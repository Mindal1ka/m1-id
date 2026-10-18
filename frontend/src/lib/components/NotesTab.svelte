<script lang="ts">
	import { Files, KeyRound, NotebookPen } from '@lucide/svelte';
	import './notes/md.css';
	import FilesPane from './notes/FilesPane.svelte';
	import NotesPane from './notes/NotesPane.svelte';
	import VaultPane from './notes/VaultPane.svelte';
	import { blurFade, pressable, slideX } from '$lib/motion';

	/**
	 * Вкладка «Нотатки»: три розділи — Нотатки, Файли і Паролі.
	 * Дані прив'язані до користувача M1 ID, а не до акаунта MyStat, тож
	 * `account_id` потрібен лише для завантаження файлів: вони йдуть на fs
	 * itstep від імені АКТИВНОГО акаунта MyStat. Обраний розділ пам'ятаємо
	 * в localStorage (якщо воно доступне).
	 */
	type Section = 'notes' | 'files' | 'vault';
	let { account_id = 0 }: { account_id?: number } = $props();
	const KEY = 'm1.notes.section';

	function initial(): Section {
		try {
			const v = localStorage.getItem(KEY);
			return v === 'vault' || v === 'files' ? v : 'notes';
		} catch {
			return 'notes';
		}
	}

	let section = $state<Section>(initial());

	const ORDER: Section[] = ['notes', 'files', 'vault'];
	/** Напрям: вправо, якщо новий розділ далі за поточний. */
	let dir = $state<1 | -1>(1);

	function pick(s: Section): void {
		if (s === section) return;
		dir = ORDER.indexOf(s) > ORDER.indexOf(section) ? 1 : -1;
		section = s;
		try {
			localStorage.setItem(KEY, s);
		} catch {
			/* не критично */
		}
	}
</script>

<div class="nt">
	<div class="seg" role="tablist" aria-label="Розділ">
		<button
			role="tab"
			aria-selected={section === 'notes'}
			class:on={section === 'notes'}
			use:pressable={{ scale: 0.95 }}
			onclick={() => pick('notes')}
		>
			<NotebookPen size={16} /> Нотатки
		</button>
		<button
			role="tab"
			aria-selected={section === 'files'}
			class:on={section === 'files'}
			use:pressable={{ scale: 0.95 }}
			onclick={() => pick('files')}
		>
			<Files size={16} /> Файли
		</button>
		<button
			role="tab"
			aria-selected={section === 'vault'}
			class:on={section === 'vault'}
			use:pressable={{ scale: 0.95 }}
			onclick={() => pick('vault')}
		>
			<KeyRound size={16} /> Паролі
		</button>
	</div>

	{#key section}
		<div class="pane" in:slideX={{ dir, distance: 26, duration: 360 }}>
			<div class="pane-in" in:blurFade={{ duration: 380, amount: 0 }}>
				{#if section === 'notes'}
					<NotesPane account={account_id} />
				{:else if section === 'files'}
					<FilesPane account={account_id} />
				{:else}
					<VaultPane />
				{/if}
			</div>
		</div>
	{/key}
</div>

<style>
	.nt {
		display: flex;
		flex-direction: column;
		gap: 14px;
	}

	.pane,
	.pane-in {
		display: flex;
		flex-direction: column;
		gap: 14px;
		min-width: 0;
	}

	.seg {
		align-self: flex-start;
		display: inline-flex;
		padding: 4px;
		gap: 4px;
		border-radius: 999px;
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
	}

	.seg button {
		display: inline-flex;
		align-items: center;
		gap: 7px;
		padding: 8px 18px;
		font: inherit;
		font-weight: 600;
		font-size: 14px;
		color: var(--text-dim);
		background: none;
		border: 0;
		border-radius: 999px;
		cursor: pointer;
		transition:
			background 0.2s ease,
			color 0.2s ease,
			box-shadow 0.2s ease;
	}

	.seg button:hover:not(.on) {
		color: var(--text);
	}

	.seg button.on {
		color: #fff;
		background: var(--accent);
		box-shadow: 0 4px 16px var(--accent-soft);
	}

	@media (max-width: 520px) {
		.seg {
			align-self: stretch;
		}

		.seg button {
			flex: 1;
			justify-content: center;
			padding: 8px 6px;
			font-size: 13px;
		}
	}
</style>

