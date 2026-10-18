<script lang="ts">
	import { confirm } from '$lib/ui';
	import { goto } from '$app/navigation';
	import { api, ApiError, type AccountOut } from '$lib/api/client';
	import { auth } from '$lib/stores/auth.svelte';
	import { store } from '$lib/stores/appStore.svelte';
	import { initials } from '$lib/sections';
	import { friendlyError } from '$lib/errors';
	import { fade } from 'svelte/transition';
	import { flip } from 'svelte/animate';
	import { stagger, spotlight, pressable, springIn, blurFade, shake } from '$lib/motion';
	import { motionOK } from '$lib/motion';
	import { backOut, cubicOut } from 'svelte/easing';
	import { Plus, RefreshCw, Trash2, UserPlus, X } from '@lucide/svelte';

	let accounts = $state<AccountOut[]>([]);
	let loading = $state(true);
	let err = $state('');

	// форма додавання (у модалці)
	let showAdd = $state(false);
	let mlogin = $state('');
	let mpass = $state('');
	let linking = $state(false);
	let formErr = $state('');
	let showTokenForm = $state(false);
	let tokenValue = $state('');

	$effect(() => {
		if (auth.restored && !auth.isAuthed) goto('/login');
	});

	let formErrEl = $state<HTMLElement>();
	$effect(() => {
		if (formErr && formErrEl) shake(formErrEl);
	});

	/** Прибирання картки зі зменшенням + м'який зсув сусідів. */
	function cardOut(node: Element): { duration: number; easing: (t: number) => number; css: (t: number, u: number) => string } {
		if (!motionOK()) return { duration: 0, easing: cubicOut, css: () => '' };
		return {
			duration: 320,
			easing: cubicOut,
			css: (t, u) => `opacity:${t};transform:scale(${0.92 + 0.08 * t}) translateX(${u * -24}px);filter:blur(${u * 4}px)`
		};
	}

	async function load(silent = false): Promise<void> {
		if (!silent) loading = true;
		err = '';
		try {
			accounts = await api.accountsList();
			// немає жодного акаунта → одразу відкриваємо модалку додавання
			if (accounts.length === 0) showAdd = true;
		} catch (ex) {
			err = friendlyError(ex);
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		if (auth.isAuthed) void load();
	});

	function openAdd(): void {
		formErr = '';
		mlogin = '';
		mpass = '';
		tokenValue = '';
		showTokenForm = false;
		showAdd = true;
	}

	async function link(e: SubmitEvent): Promise<void> {
		e.preventDefault();
		formErr = '';
		linking = true;
		try {
			const res = await api.accountLink(mlogin, mpass);
			// онбордінг-сторінку видалено: холодний старт /app сам показує
			// анімацію-кубик (немає клієнтського кешу → повна синхронізація)
			goto(`/app?account=${res.account.id}`);
		} catch (ex) {
			formErr = friendlyError(ex);
		} finally {
			linking = false;
		}
	}

	async function linkByToken(e: SubmitEvent): Promise<void> {
		e.preventDefault();
		formErr = '';
		linking = true;
		try {
			const res = await api.accountLinkToken(tokenValue.trim());
			goto(`/app?account=${res.account.id}`);
		} catch (ex) {
			formErr = friendlyError(ex);
		} finally {
			linking = false;
		}
	}

	async function remove(id: number): Promise<void> {
		const ok = await confirm({
			title: 'Видалити акаунт?',
			message: 'Акаунт буде видалено разом зі знімками даних. Це незворотно.',
			confirmText: 'Видалити',
			danger: true
		});
		if (!ok) return;
		try {
			await api.accountDelete(id);
			// без скелетона, щоб відіграла анімація видалення картки
			await load(true);
		} catch (ex) {
			err = friendlyError(ex);
		}
	}

	function open(a: AccountOut): void {
		// «Оновити дані»: скидаємо клієнтський кеш акаунта — /app?account=N
		// відкриється без кешу і покаже анімацію-кубик під час повної
		// ресинхронізації (стара сторінка онбордінгу видалена).
		store.invalidateAll(a.id);
		localStorage.removeItem('m1id.lastAccount');
		goto(`/app?account=${a.id}`);
	}

	function onkeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape' && showAdd) showAdd = false;
	}
</script>

<svelte:head><title>Акаунти · M1 ID</title><meta name="robots" content="noindex, nofollow" /></svelte:head>
<svelte:window onkeydown={onkeydown} />

<section class="head">
	<h1>Мої акаунти <span class="accent-text">MyStat</span></h1>
	<p class="text-dim">
		Підключи акаунт mystat.itstep.org — і всі дані зберуться автоматично.
	</p>
</section>

{#if loading}
	<div class="skeleton sk-card"></div>
{:else if accounts.length === 0}
	<section class="glass card empty-card">
		<h2>Підключи перший акаунт</h2>
		<p class="text-dim">
			Уведи логін і пароль від mystat.itstep.org — решту зробимо ми:
			розклад, домашка, оцінки та баланси зберуться автоматично.
		</p>
		<button class="btn btn-primary" onclick={openAdd}>
		<Plus size={16} strokeWidth={2.4} /> Підключити акаунт</button
	>
	</section>
{:else}
	{#if accounts.some((a) => a.status === 'needs_relogin')}
		<p class="relogin-hint">
			⚠ В одного з акаунтів застарів токен — натисни «Оновити дані» і увійди
			ще раз (дані не загубляться).
		</p>
	{/if}

	<div class="list" use:stagger={{ selector: ':scope > .acc', step: 60, y: 14, scale: true }}>
		{#each accounts as a (a.id)}
			<article
				class="glass acc"
				use:spotlight
				animate:flip={{ duration: 380, easing: cubicOut }}
				in:springIn={{ start: 0.94, duration: 460, y: 14 }}
				out:cardOut
			>
				<div class="avatar">{initials(a.fio || a.label)}</div>
				<div class="info">
					<b>{a.fio || a.label}</b>
					<span class="text-faint mono">
						login: <b class="lg">{a.login || '—'}</b> · філія: {a.branch_name || a.branch_alias || '—'} · logbook: {a.logbook_id}
					</span>
				</div>
				<span class="chip status">
					<span
						class="dot"
						class:breathe={a.status === 'active' && a.sync_status === 'running'}
						class:dot--online={a.status === 'active'}
						class:dot--offline={a.status !== 'active'}></span>
					{#key a.status === 'active' ? (a.sync_status === 'running' ? 'run' : 'ok') : 'relogin'}
						<span class="st-txt" in:blurFade={{ duration: 280, amount: 5, y: 4 }}
							>{a.status === 'active'
								? a.sync_status === 'running'
									? 'синхронізація…'
									: 'активний'
								: 'потрібен вхід'}</span
						>
					{/key}
				</span>
				<div class="actions">
					<button class="btn" use:pressable onclick={() => open(a)}>
						<RefreshCw size={14} strokeWidth={2} /> Оновити дані</button
					>
					<button class="btn danger" use:pressable onclick={() => remove(a.id)}>
						<Trash2 size={14} strokeWidth={2} /> Видалити</button
					>
				</div>
			</article>
		{/each}
	</div>

	<button class="btn add-btn" onclick={openAdd}>
		<Plus size={16} strokeWidth={2.4} /> Додати акаунт</button
	>
{/if}

{#if err}
	<p class="error" role="alert">⚠ {err}</p>
{/if}

{#if showAdd}
	<div
		class="overlay"
		transition:fade={{ duration: 150 }}
		onclick={(e) => e.target === e.currentTarget && (showAdd = false)}
		role="presentation"
	>
		<div
			class="modal glass"
			transition:springIn={{ start: 0.94, duration: 420, y: 12 }}
			role="dialog"
			aria-modal="true"
			aria-label="Додати акаунт MyStat"
		>
			<header>
				<h2 class="with-ico">
					<UserPlus size={18} strokeWidth={2} /> Додати акаунт MyStat
				</h2>
				<button class="x" onclick={() => (showAdd = false)} aria-label="Закрити">
					<X size={18} strokeWidth={2} />
				</button>
			</header>

			<form onsubmit={link}>
				<label>
					<span>Логін MyStat</span>
					<input required bind:value={mlogin} placeholder="логін або e-mail" />
				</label>
				<label>
					<span>Пароль MyStat</span>
					<input required type="password" bind:value={mpass}
						placeholder="••••••••" />
				</label>
				{#if formErr}
					<p class="error" role="alert" bind:this={formErrEl} in:blurFade={{ y: 4 }}>⚠ {formErr}</p>
				{/if}
				<button class="btn btn-primary wide" disabled={linking} use:pressable>
					{linking ? 'Входимо…' : 'Підключити ✨'}
				</button>
			</form>

			<details>
				<summary class="text-faint">Увійти готовим токеном (для розробки)</summary>
				<form class="token-form" onsubmit={linkByToken}>
					<textarea rows="3" bind:value={tokenValue}
						placeholder="eyJhbGciOiJIUzI1NiIs... (access_token)"></textarea>
					<button class="btn" disabled={linking}>Прив’язати токен</button>
				</form>
			</details>
		</div>
	</div>
{/if}

<style>
	.head {
		margin-bottom: 20px;
	}

	h1 {
		font-size: clamp(22px, 4vw, 30px);
	}

	.empty-card {
		max-width: 520px;
		display: flex;
		flex-direction: column;
		gap: 14px;
		align-items: flex-start;
		padding: 28px;
	}

	.empty-card h2 {
		font-family: var(--font-display);
		font-size: 19px;
	}

	.st-txt {
		display: inline-block;
	}

	.sk-card {
		height: 120px;
		border-radius: var(--radius-lg);
	}

	.add-btn {
		display: inline-flex;
		align-items: center;
		gap: 7px;
		margin-top: 16px;
	}

	.overlay {
		position: fixed;
		inset: 0;
		z-index: 90;
		background: rgba(5, 7, 11, 0.6);
		-webkit-backdrop-filter: blur(6px);
		backdrop-filter: blur(6px);
		display: grid;
		place-items: center;
		padding: 18px;
	}

	.modal {
		width: min(460px, 100%);
		max-height: 88dvh;
		overflow-y: auto;
		padding: 24px;
		border-radius: var(--radius-lg);
		display: flex;
		flex-direction: column;
		gap: 16px;
	}

	header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	header h2 {
		font-family: var(--font-display);
		font-size: 18px;
	}

	.with-ico {
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.with-ico :global(svg) {
		color: var(--accent);
	}

	.x {
		background: none;
		border: none;
		color: var(--text-faint);
		cursor: pointer;
		display: grid;
		place-items: center;
		padding: 2px;
	}

	.x:hover {
		color: var(--text);
	}

	.list {
		display: flex;
		flex-direction: column;
		gap: 12px;
		margin-bottom: 8px;
	}

	.acc {
		display: flex;
		align-items: center;
		gap: 14px;
		padding: 14px 16px;
		border-radius: var(--radius-md);
		flex-wrap: wrap;
	}

	.avatar {
		width: 44px;
		height: 44px;
		flex-shrink: 0;
		display: grid;
		place-items: center;
		border-radius: 50%;
		background: var(--accent-soft);
		color: var(--accent);
		font-weight: 700;
		font-family: var(--font-display);
	}

	.info {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 160px;
		flex: 1;
		font-size: 14.5px;
	}

	.lg {
		color: var(--text-dim);
		font-weight: 700;
	}

	.mono {
		font-family: ui-monospace, Consolas, monospace;
		font-size: 11.5px;
	}

	.relogin-hint {
		color: var(--amber);
		background: rgba(255, 180, 84, 0.08);
		border: 1px solid rgba(255, 180, 84, 0.3);
		border-radius: var(--radius-sm);
		padding: 10px 12px;
		font-size: 13.5px;
		margin-bottom: 16px;
		max-width: 640px;
	}

	form {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	label {
		display: flex;
		flex-direction: column;
		gap: 6px;
		font-size: 13.5px;
		color: var(--text-dim);
	}

	input,
	textarea {
		font: inherit;
		color: var(--text);
		background: var(--surface);
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-sm);
		padding: 10px 13px;
		outline: none;
	}

	input:focus,
	textarea:focus {
		border-color: var(--accent);
	}

	.error {
		color: var(--danger);
		background: rgba(248, 113, 113, 0.08);
		border: 1px solid rgba(248, 113, 113, 0.25);
		border-radius: var(--radius-sm);
		padding: 10px 12px;
		font-size: 13.5px;
	}

	.danger {
		color: var(--danger);
	}

	summary {
		cursor: pointer;
		user-select: none;
	}

	.token-form {
		margin-top: 12px;
	}

	textarea {
		width: 100%;
		resize: vertical;
		font-family: ui-monospace, Consolas, monospace;
		font-size: 12px;
	}

	.wide {
		width: 100%;
	}

	.sk-card {
		height: 90px;
		margin-bottom: 24px;
		border-radius: var(--radius-md);
	}
</style>
