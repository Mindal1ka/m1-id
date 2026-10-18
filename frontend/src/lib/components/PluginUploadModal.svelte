<script lang="ts">
	import { Archive, Check, Files, Link2, Lock, Globe, Upload, TriangleAlert } from '@lucide/svelte';
	import { api, ApiError } from '$lib/api/client';
	import { friendlyError } from '$lib/errors';
	import { Badge, Button, CopyButton, Dialog, Segmented } from '$lib/ui';

	let { open = $bindable(false), onclose, onuploaded }: {
		open?: boolean;
		onclose?: () => void;
		onuploaded?: () => void;
	} = $props();

	type Vis = 'public' | 'link' | 'private';

	const VIS_LABEL: Record<Vis, string> = {
		public: 'Публічний',
		link: 'За посиланням',
		private: 'Приватний'
	};
	const VIS_HINT: Record<Vis, string> = {
		public: 'Видно всім у маркетплейсі.',
		link: 'Видно лише тим, у кого є посилання.',
		private: 'Бачиш лише ти й адмін.'
	};
	const VIS_ITEMS = [
		{ value: 'public', label: VIS_LABEL.public, icon: Globe },
		{ value: 'link', label: VIS_LABEL.link, icon: Link2 },
		{ value: 'private', label: VIS_LABEL.private, icon: Lock }
	];
	const MODE_ITEMS = [
		{ value: 'zip', label: 'Zip-архів', icon: Archive },
		{ value: 'files', label: 'Окремі файли', icon: Files }
	];

	let zipInput = $state<HTMLInputElement | null>(null);
	let filesInput = $state<HTMLInputElement | null>(null);

	let mode = $state<'zip' | 'files'>('zip');
	let visibility = $state<Vis>('public');
	let uploading = $state(false);
	let done = $state(false);
	let shareToken = $state('');
	let err = $state('');

	// скидання при кожному відкритті
	$effect(() => {
		if (open) {
			mode = 'zip';
			visibility = 'public';
			uploading = false;
			shareToken = '';
			err = '';
			done = false;
		}
	});

	function shareUrl(token: string): string {
		return `${location.origin}${location.pathname}?plg=${token}`;
	}

	function handleZip(e: Event): void {
		const input = e.target as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;
		void doUpload(() => api.pluginUploadZip(file, visibility));
	}

	function handleFiles(e: Event): void {
		const input = e.target as HTMLInputElement;
		const list = Array.from(input.files ?? []);
		if (!list.length) return;
		if (!list.some((f) => f.name === 'manifest.json')) {
			err = 'Серед обраних файлів має бути manifest.json.';
			input.value = '';
			return;
		}
		void doUpload(() => api.pluginUploadFiles(list, visibility));
	}

	async function doUpload(fn: () => Promise<{ verified: boolean; share_token: string }>): Promise<void> {
		uploading = true;
		err = '';
		try {
			const resp = await fn();
			done = true;
			shareToken = resp.share_token || '';
			if (!resp.verified) {
				err = 'Плагін додано, але він НЕ верифікований.';
			}
			onuploaded?.();
		} catch (ex) {
			err = ex instanceof ApiError
				? `Помилка аплоаду: ${ex.message ?? ex}`
				: friendlyError(ex);
		} finally {
			uploading = false;
		}
	}
</script>

<Dialog bind:open title="Додати плагін" size="md" {onclose}>
	<div class="up">
		{#if !done}
			<Segmented
				items={MODE_ITEMS}
				bind:value={mode as string}
				block
				aria-label="Спосіб завантаження"
			/>

			<p class="hint">
				{#if mode === 'zip'}
					Обери .zip з маніфестом: manifest.json + plugin.py (+ index.html).
				{:else}
					Обери файли разом (кілька): manifest.json + plugin.py (+ index.html, .png…).
				{/if}
				Обмеження: 512 КБ, ≤ 20 файлів, без підпапок.
			</p>

			<div class="vis">
				<span class="vis-title">Видимість</span>
				<Segmented
					items={VIS_ITEMS}
					bind:value={visibility as string}
					block
					size="sm"
					aria-label="Видимість плагіна"
				/>
				<p class="hint">{VIS_HINT[visibility]}</p>
			</div>

			{#if mode === 'zip'}
				<Button icon={Upload} loading={uploading} block onclick={() => zipInput?.click()}>
					{uploading ? 'Завантаження…' : 'Обрати .zip'}
				</Button>
				<input bind:this={zipInput} type="file" accept=".zip" hidden onchange={handleZip} />
			{:else}
				<Button icon={Upload} loading={uploading} block onclick={() => filesInput?.click()}>
					{uploading ? 'Завантаження…' : 'Обрати файли'}
				</Button>
				<input
					bind:this={filesInput}
					type="file"
					multiple
					accept=".py,.html,.json,.md,.png,.txt"
					hidden
					onchange={handleFiles}
				/>
			{/if}
		{:else}
			<div class="ok-row">
				<span class="ok-ico"><Check size={22} aria-hidden="true" /></span>
				<b>Плагін завантажено</b>
				<Badge tone="neutral">Видимість: {VIS_LABEL[visibility]}</Badge>
			</div>
			{#if visibility === 'link' && shareToken}
				<p class="hint">Посилання для встановлення:</p>
				<div class="link-row">
					<code>{shareUrl(shareToken)}</code>
					<CopyButton text={shareUrl(shareToken)} label="Копіювати посилання" />
				</div>
			{:else if visibility === 'link'}
				<p class="hint">Токен згенерує адмін або автор (кнопка «Посилання» у картці плагіна).</p>
			{/if}
		{/if}

		{#if err}
			<p class="err" role="alert"><TriangleAlert size={14} aria-hidden="true" /> {err}</p>
		{/if}
	</div>
</Dialog>

<style>
	.up {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	.hint {
		margin: 0;
		font-size: var(--text-sm);
		color: var(--color-text-subtle);
	}

	.vis {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}

	.vis-title {
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
		color: var(--color-text-muted);
	}

	.ok-row {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-3) 0;
	}

	.ok-ico {
		display: grid;
		place-items: center;
		width: 44px;
		height: 44px;
		color: var(--color-success);
		background: var(--color-success-soft);
		border-radius: var(--radius-full);
	}

	.link-row {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-surface);
	}

	.link-row code {
		flex: 1;
		min-width: 0;
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		overflow-wrap: anywhere;
	}

	.err {
		display: flex;
		align-items: flex-start;
		gap: var(--space-1);
		margin: 0;
		color: var(--color-danger);
		font-size: var(--text-sm);
	}
</style>
