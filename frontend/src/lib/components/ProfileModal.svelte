<script lang="ts">
		import { api, ApiError, type AccountOut, type DashUser } from '$lib/api/client';
	import { auth } from '$lib/stores/auth.svelte';
		import { friendlyError } from '$lib/errors';
	import {
		Download, Pencil, Save, QrCode, Check, Clock,
		AlertTriangle, ImagePlus
	} from '@lucide/svelte';
	import { Dialog, Button, Badge, Avatar, Field, Input, Skeleton } from '$lib/ui';
	import { dev } from '$lib/devmode.svelte';
	import { untrack } from 'svelte';
	import { slide } from 'svelte/transition';
		import { cubicOut } from 'svelte/easing';
	import { stagger, blurFade } from '$lib/motion';

	let {
		open = $bindable(false),
		editMode = false,
		account,
		user,
		onclose,
		onqr
	}: {
		open?: boolean;
		editMode?: boolean;
		account: AccountOut | null;
		user: DashUser | null;
		onclose: () => void;
		onqr: () => void;
	} = $props();

	interface Personal {
		photo?: string | null;
		fio?: string;
		birthdate?: string | null;
		emails?: { value: string }[];
		phones?: { value: string }[];
	}

	let data = $state<Personal | null>(null);
	let moder = $state<Record<string, unknown> | null>(null);
	let loading = $state(false);
	let saving = $state(false);
	let saved = $state('');
	let err = $state('');

	let editing = $state(false);
	let birthdate = $state('');
	let phone = $state('');
	let email = $state('');
	let photoFile = $state<File | null>(null);
	let photoPreview = $state('');
	let refBusy = $state(false);
	// лічильник запитів: відповідь застарілого запиту ігнорується
	let loadGen = 0;

	/** Отримати довідку: файл з MyStat → завантаження браузером. */
	async function getReference(): Promise<void> {
		if (!account || refBusy) return;
		refBusy = true;
		err = '';
		try {
			const { blob, filename } = await api.downloadReference(account.id);
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = filename;
			a.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			err = friendlyError(e);
		} finally {
			refBusy = false;
		}
	}

	const fio = $derived(data?.fio || user?.fio || '');
	const photo = $derived(photoPreview || data?.photo || user?.photo_url || '');

	const accountId = $derived(account?.id ?? null);

	// Реагуємо лише на відкриття модалки та зміну id акаунта; решта стану
	// (editMode, account-об'єкт, поля форми) читається в untrack.
	$effect(() => {
		if (!open) {
			untrack(() => {
				loadGen++;
				editing = false;
				resetFields();
			});
			return;
		}
		if (accountId !== null) {
			untrack(() => {
				// окрема кнопка профілю відкриває одразу в режимі змін
				editing = editMode;
				void loadAll();
			});
		}
	});

	/** Повернути поля форми до оригінальних значень із завантажених даних. */
	function resetFields(): void {
		birthdate = data?.birthdate ?? '';
		phone = data?.phones?.[0]?.value ?? '';
		email = data?.emails?.[0]?.value ?? '';
		clearPhoto();
	}

	function clearPhoto(): void {
		if (photoPreview) URL.revokeObjectURL(photoPreview);
		photoFile = null;
		photoPreview = '';
	}

	async function loadAll(): Promise<void> {
		const my = ++loadGen;
		loading = true;
		err = '';
		try {
			const [p, m] = await Promise.all([
				api.personalData(account!.id, account!.branch_alias),
				api.checkModerating(account!.id, account!.branch_alias).catch(() => null)
			]);
			if (my !== loadGen) return; // застаріла відповідь
			data = p as Personal;
			// жива форма відповіді: {photo: null|шлях-на-модерації,
			//   email: {verified_status, email_address}, phone: {...}}
			moder = (m && typeof m === 'object' ? m : null) as Record<string, unknown> | null;
			resetFields();
		} catch (ex) {
			if (my !== loadGen) return;
			err = friendlyError(ex);
		} finally {
			if (my === loadGen) loading = false;
		}
	}

	const pendingPhoto = $derived(Boolean(moder?.photo));
	const emailVerified = $derived(
		(moder?.email as { verified_status?: string } | undefined)?.verified_status === '1'
	);
	const phoneVerified = $derived(
		(moder?.phone as { verified_status?: string } | undefined)?.verified_status === '1'
	);

	function pickPhoto(e: Event): void {
		const input = e.currentTarget as HTMLInputElement;
		const f = input.files?.[0] ?? null;
		if (photoPreview) URL.revokeObjectURL(photoPreview);
		photoFile = f;
		photoPreview = f ? URL.createObjectURL(f) : '';
	}

	async function save(): Promise<void> {
		if (!account) return;
		saving = true;
		saved = '';
		err = '';
		try {
			await api.changePersonalData(account.id, account.branch_alias, {
				birthdate: birthdate || null,
				phone: phone || null,
				email: email || null,
				photo: photoFile
			});
			editing = false;
			clearPhoto();
			saved = 'Збережено. Зміни можуть пройти модерацію.';
			await loadAll();
		} catch (ex) {
			err = friendlyError(ex);
		} finally {
			saving = false;
		}
	}

	function startEdit(): void {
		saved = '';
		editing = true;
	}

	function cancelEdit(): void {
		editing = false;
		resetFields();
	}
</script>


<Dialog bind:open {onclose} size="lg" title={fio || 'Профіль'}>
	{#snippet header()}
		<div class="hdr">
			<div class="av">
				<Avatar src={photo || null} name={fio} size="lg" />
			</div>
			<div class="who">
				<h2>{fio || 'Профіль'}</h2>
				<span class="sub">
					{account?.branch_name || account?.branch_alias || ''}{user?.group_name ? ` · ${user.group_name}` : ''}
				</span>
				{#if dev.enabled && account}
					<span class="tech">
						Технічні дані: logbook {account.logbook_id} · uid {account.id_user_storage}
					</span>
				{/if}
			</div>
		</div>
	{/snippet}

	<div class="body">
		{#if pendingPhoto}
			<Badge tone="warning" icon={Clock}>Нове фото ще на модерації</Badge>
		{/if}
		{#if saved}
			<p class="note ok" in:blurFade={{ y: 6 }}><Check size={16} /> {saved}</p>
		{/if}
		{#if err}
			<p class="note err" in:blurFade={{ y: 6 }}><AlertTriangle size={16} /> {err}</p>
		{/if}

		<section>
			<h3>Контакти</h3>
			{#if loading}
				<div class="skel">
					<Skeleton height={40} />
					<Skeleton height={40} />
					<Skeleton height={40} />
				</div>
			{:else}
				<div class="fields" use:stagger={{ step: 35, y: 12, max: 10 }}>
					<Field label="ПІБ">
						{#snippet children({ id, describedBy })}
							<Input {id} aria-describedby={describedBy} value={fio} disabled />
						{/snippet}
					</Field>
					<Field label="Дата народження">
						{#snippet children({ id, describedBy })}
							<Input {id} aria-describedby={describedBy} type="date"
								bind:value={birthdate} disabled={!editing} />
						{/snippet}
					</Field>
					<Field label="Email">
						{#snippet children({ id, describedBy })}
							<Input {id} aria-describedby={describedBy} bind:value={email}
								disabled={!editing} placeholder="email">
								{#snippet trailing()}
									{#if emailVerified}
										<Badge tone="success" size="sm" icon={Check}>Підтверджено</Badge>
									{/if}
								{/snippet}
							</Input>
						{/snippet}
					</Field>
					<Field label="Телефон">
						{#snippet children({ id, describedBy })}
							<Input {id} aria-describedby={describedBy} bind:value={phone}
								disabled={!editing} placeholder="+380…">
								{#snippet trailing()}
									{#if phoneVerified}
										<Badge tone="success" size="sm" icon={Check}>Підтверджено</Badge>
									{/if}
								{/snippet}
							</Input>
						{/snippet}
					</Field>
					<Field label="Філія">
						{#snippet children({ id, describedBy })}
							<Input {id} aria-describedby={describedBy}
								value={account?.branch_name || account?.branch_alias || ''} disabled />
						{/snippet}
					</Field>
					<Field label="Мова">
						{#snippet children({ id, describedBy })}
							<Input {id} aria-describedby={describedBy}
								value={(user?.lang ?? 'uk').toUpperCase()} disabled />
						{/snippet}
					</Field>
				</div>

				{#if editing}
					<div class="photo" transition:slide={{ duration: 340, easing: cubicOut }}>
						<Avatar src={photo || null} name={fio} size="xl" />
						<div class="photo-field">
							<Field label="Нове фото"
								hint={photoFile ? photoFile.name : 'Перегляд з\'явиться одразу, збережеш нижче.'}>
								{#snippet children({ id, describedBy })}
									<input {id} aria-describedby={describedBy} class="file" type="file"
										accept="image/*" onchange={pickPhoto} />
								{/snippet}
							</Field>
						</div>
					</div>
				{/if}
			{/if}
		</section>

	</div>

	{#snippet footer()}
		<div class="actions">
			{#key editing}
			<div class="grp" in:blurFade={{ duration: 260, amount: 6, y: 4 }}>
			{#if editing}
				<Button variant="ghost" onclick={cancelEdit}>Скасувати</Button>
				<Button icon={Save} loading={saving} onclick={save}>
					{saving ? 'Зберігаю…' : 'Зберегти'}
				</Button>
			{:else}
				<Button variant="secondary" icon={QrCode} onclick={onqr}>QR-код</Button>
				<Button variant="secondary" icon={Download} loading={refBusy} onclick={getReference}>
					{refBusy ? 'Отримую…' : 'Отримати довідку'}
				</Button>
				<Button icon={Pencil} onclick={startEdit}>Редагувати</Button>
			{/if}
			</div>
			{/key}
		</div>
	{/snippet}
</Dialog>

<style>
	.hdr {
		display: flex;
		align-items: center;
		gap: var(--space-4);
		min-width: 0;
	}

	/* аватар вистрибує пружиною, м'яке кільце розходиться один раз */
	.av {
		position: relative;
		flex: none;
		animation: pm-av 560ms var(--ease-spring) both;
	}
	.av::after {
		content: '';
		position: absolute;
		inset: -3px;
		border-radius: var(--radius-full);
		border: 2px solid var(--color-accent);
		pointer-events: none;
		opacity: 0;
		animation: pm-ring 900ms var(--ease-out) 180ms 1;
	}
	@keyframes pm-av {
		from { opacity: 0; transform: scale(0.6); filter: blur(6px); }
	}
	@keyframes pm-ring {
		0% { opacity: 0.7; transform: scale(0.9); }
		100% { opacity: 0; transform: scale(1.5); }
	}
	/* lite: той самий пружинний вихід аватара, але без blur */
	@keyframes pm-av-lite {
		from { opacity: 0; transform: scale(0.6); }
	}
	:global(html[data-perf='lite']) .av {
		animation-name: pm-av-lite;
	}
	:global(html[data-anim='off']) :is(.av, .av::after) {
		animation: none;
	}

	.who {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}

	h2 {
		margin: 0;
		font-size: var(--text-xl);
		font-weight: var(--weight-semibold);
		color: var(--color-text);
	}

	.sub {
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}

	.tech {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--color-text-subtle);
	}

	.body {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}

	section {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	h3 {
		margin: 0;
		font-size: var(--text-base);
		font-weight: var(--weight-semibold);
		color: var(--color-text);
	}

	.fields {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-3);
	}

	.skel {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	.photo {
		display: flex;
		align-items: flex-start;
		gap: var(--space-4);
	}

	.photo-field {
		flex: 1;
		min-width: 0;
	}

	.file {
		font: inherit;
		font-size: var(--text-sm);
		color: var(--color-text-muted);
		max-width: 100%;
	}

	.note {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-sm);
		font-size: var(--text-sm);
	}

	.note.ok {
		color: var(--color-success);
		background: var(--color-success-soft);
	}

	.note.err {
		color: var(--color-danger);
		background: var(--color-danger-soft);
	}

	.grp {
		display: flex;
		justify-content: flex-end;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	.actions {
		display: flex;
		justify-content: flex-end;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	@media (max-width: 640px) {
		.fields {
			grid-template-columns: 1fr;
		}

		.actions :global(button) {
			flex: 1;
		}
	}
</style>
