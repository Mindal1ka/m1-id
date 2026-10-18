<script lang="ts">
	import { Check, ExternalLink, Eye, FileText, Link2, Pencil, Paperclip, Trash2, Images, AlertTriangle } from '@lucide/svelte';
	import { api, type M1LinkView } from '$lib/api/client';
	import { friendlyError } from '$lib/errors';
	import { safeUrl } from '$lib/sanitize';
	import { flip } from 'svelte/animate';
	import { cubicOut } from 'svelte/easing';
	import { AnimatedNumber, springIn, blurFade, motionOK, pressable, shake, fx } from '$lib/motion';
	import {
		Dialog, Badge, Button, IconButton, Input, Skeleton, EmptyState, ErrorState,
		CopyButton, confirm
	} from '$lib/ui';

	let {
		open = $bindable(false),
		hwId = 0,
		hwTitle = '',
		account = 0,
		onclose,
		onchanged
	}: {
		open?: boolean;
		hwId?: number;
		hwTitle?: string;
		account?: number;
		onclose?: () => void;
		onchanged?: () => void;
	} = $props();

	let items = $state<M1LinkView[]>([]);
	let loading = $state(false);
	let loadErr = $state('');
	let err = $state('');
	let editingSlug = $state('');
	let editUrl = $state('');
	let saving = $state(false);

	let allMode = $derived(!hwId);

	$effect(() => {
		if (open && account) void load();
	});

	/** Вихід картки: зменшення + зсув (+ blur лише на рівні full; сусіди з'їжджаються через flip). */
	function cardOut(node: Element) {
		if (!motionOK()) return { duration: 0 };
		const blur = fx();
		return {
			duration: 320,
			easing: cubicOut,
			css: (t: number, u: number) =>
				`opacity:${t};transform:scale(${0.9 + 0.1 * t}) translateX(${u * -28}px)` +
				(blur ? `;filter:blur(${u * 4}px)` : '')
		};
	}

	let errEl = $state<HTMLElement>();
	$effect(() => {
		if (err && errEl) shake(errEl);
	});

	async function load(silent = false): Promise<void> {
		if (!silent) loading = true;
		loadErr = '';
		try {
			items = (await api.links(account, hwId || undefined)).items;
		} catch (e) {
			items = [];
			loadErr = friendlyError(e);
		} finally {
			loading = false;
		}
	}

	function fmtDate(s: string | null): string {
		if (!s) return '—';
		const d = new Date(s);
		return Number.isNaN(d.getTime())
			? s
			: d.toLocaleString('uk-UA', { day: '2-digit', month: '2-digit',
				hour: '2-digit', minute: '2-digit' });
	}

	async function save(): Promise<void> {
		if (!editUrl.trim() || saving) return;
		saving = true;
		try {
			await api.updateLink(editingSlug, editUrl.trim());
			editingSlug = '';
			await load();
			onchanged?.();
		} catch (e) {
			err = friendlyError(e);
		} finally {
			saving = false;
		}
	}

	async function revoke(slug: string): Promise<void> {
		const ok = await confirm({
			title: 'Вилучити посилання?',
			message: 'Посилання перестане працювати — вчитель більше не зможе його відкрити.',
			confirmText: 'Вилучити',
			danger: true
		});
		if (!ok) return;
		try {
			await api.revokeLink(slug);
			// без скелетона, щоб відіграла анімація зникнення картки
			await load(true);
			onchanged?.();
		} catch (e) {
			err = friendlyError(e);
		}
	}

	let uploadPendingSlug = $state('');
	let uploadErr = $state('');
	let fileInput: HTMLInputElement | null = $state(null);

	function pickFile(l: M1LinkView): void {
		uploadPendingSlug = l.slug;
		uploadErr = '';
		fileInput?.click();
	}

	async function onFilePicked(e: Event): Promise<void> {
		const f = (e.currentTarget as HTMLInputElement).files?.[0];
		(e.currentTarget as HTMLInputElement).value = '';
		const slug = uploadPendingSlug;
		uploadPendingSlug = '';
		if (!f || !slug) return;
		loading = true;
		try {
			await api.uploadLinkFile(slug, f, account);
			await load();
			onchanged?.();
		} catch (ex) {
			uploadErr = friendlyError(ex);
		} finally {
			loading = false;
		}
	}
</script>

<Dialog
	bind:open
	{onclose}
	size="lg"
	title="M1 Provider"
	description={allMode
		? 'Усі твої посилання M1 Provider — статистика, редагування й вилучення в одному місці.'
		: `${hwTitle || `Домашка #${hwId}`} — посилання, які вчитель відкриє замість файлу. Статистика відкриттів оновлюється в реальному часі.`}
>
	<div class="body">
		{#if loading}
			<Skeleton height={120} radius="var(--radius-md)" />
			<Skeleton height={120} radius="var(--radius-md)" />
		{:else if loadErr}
			<ErrorState title="Не вдалося завантажити посилання" description={loadErr}
				onretry={() => void load()} />
		{:else if !items.length}
			<EmptyState icon={Eye} title="Посилань ще немає"
				description="Вони створюються автоматично, коли ти здаєш роботу через M1 Provider." />
		{:else}
			{#each items as l, i (l.slug)}
				<div
					class="card"
					class:off={!l.active}
					animate:flip={{ duration: 360, easing: cubicOut }}
					in:springIn|global={{ delay: Math.min(i, 8) * 55, start: 0.95, duration: 460, y: 12 }}
					out:cardOut
				>
					{#if allMode}
						<button type="button" class="hw-lbl" onclick={() => onclose?.()}>
							ДЗ #{l.homework_id}{l.hw_title ? ` · ${l.hw_title}` : ''}
						</button>
					{/if}
					<div class="row1">
						{#if l.gallery}
							<Badge tone="accent" size="sm" icon={Images}>Галерея</Badge>
						{:else}
							<Badge size="sm" icon={Link2}>Redirect</Badge>
						{/if}
						<Badge size="sm" icon={Eye}>Відкриттів: <AnimatedNumber value={l.opens} duration={700} /></Badge>
						{#if !l.active}
							<Badge tone="danger" size="sm">Вилучено</Badge>
						{/if}
					</div>

					{#if editingSlug === l.slug}
						<div class="edit">
							<Input bind:value={editUrl} spellcheck={false} placeholder="https://…"
								aria-label="Адреса посилання" />
							<IconButton icon={Check} label="Зберегти адресу" variant="primary"
								disabled={saving} onclick={() => void save()} />
						</div>
					{:else if l.kind === 'file'}
						<a class="target" href={safeUrl(l.target_url)} target="_blank"
							rel="noopener noreferrer" title="Файл школи — натисни, щоб відкрити">
							<FileText size={14} />
							<span>Файл школи (fs)</span>
							<ExternalLink size={14} class="pen" />
						</a>
					{:else}
						<button type="button" class="target"
							onclick={() => { editingSlug = l.slug; editUrl = l.target_url; }}
							title="Натисни, щоб змінити адресу">
							<Link2 size={14} />
							<span>{l.target_url || '—'}</span>
							<Pencil size={14} class="pen" />
						</button>
					{/if}

					<small class="meta">
						Створено {fmtDate(l.created_at)} · останнє відкриття {fmtDate(l.last_opened_at)}
					</small>

					<div class="row2">
						<CopyButton text={l.url} variant="button" label="Копіювати" size="sm" />
						<Button variant="secondary" size="sm" icon={ExternalLink}
							href={safeUrl(l.url)} target="_blank" rel="noopener noreferrer">Відкрити</Button>
						<Button variant="secondary" size="sm" icon={Paperclip}
							title="Замінити файлом (завантажиться в fs)"
							onclick={() => pickFile(l)}>Файл</Button>
						<span class="spacer"></span>
						<IconButton icon={Trash2} label="Вилучити" variant="danger" size="sm"
							onclick={() => void revoke(l.slug)} />
					</div>
				</div>
			{/each}
		{/if}

		{#if err}
			<p class="f-err" bind:this={errEl} in:blurFade={{ y: 4 }}><AlertTriangle size={16} /> {err}</p>
		{/if}
		{#if uploadErr}
			<p class="f-err" in:blurFade={{ y: 4 }}><AlertTriangle size={16} /> {uploadErr}</p>
		{/if}
		<input type="file" hidden bind:this={fileInput}
			onchange={(e) => void onFilePicked(e)} />
	</div>
</Dialog>

<style>
	.body {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	.card {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-3) var(--space-4);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-2);
	}

	.card.off {
		opacity: 0.55;
	}

	.hw-lbl {
		align-self: flex-start;
		padding: 0;
		border: none;
		background: none;
		color: var(--color-text-subtle);
		font: inherit;
		font-size: var(--text-xs);
		text-align: left;
		cursor: pointer;
	}

	.hw-lbl:hover {
		color: var(--color-accent);
	}

	.row1,
	.row2 {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	.spacer {
		flex: 1;
	}

	.target {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		width: 100%;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-surface);
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-sm);
		text-align: left;
		text-decoration: none;
		cursor: pointer;
	}

	.target:hover {
		border-color: var(--color-accent);
	}

	.target span {
		flex: 1;
		min-width: 0;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.target :global(.pen) {
		flex-shrink: 0;
		opacity: 0.5;
	}

	.edit {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}

	.edit > :global(:first-child) {
		flex: 1;
		min-width: 0;
	}

	.meta {
		font-size: var(--text-xs);
		color: var(--color-text-subtle);
	}

	.f-err {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-sm);
		background: var(--color-danger-soft);
		color: var(--color-danger);
		font-size: var(--text-sm);
	}
</style>
