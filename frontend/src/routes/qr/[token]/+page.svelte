<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { ShieldCheck, Monitor } from '@lucide/svelte';
	import AppModal from '$lib/components/AppModal.svelte';
	import { api } from '$lib/api/client';
	import { auth } from '$lib/stores/auth.svelte';
	import { friendlyError } from '$lib/errors';
	import { stagger, pressable, springIn, blurFade, shake, pop } from '$lib/motion';

	const token = page.params.token ?? '';

	type Info = { device: string; ip: string; created_at: string; options: string[] };
	let info = $state<Info | null>(null);
	let picked = $state('');
	let busy = $state(false);
	let err = $state('');
	let done = $state<'' | 'approved' | 'denied'>('');
	let loading = false;
	let errEl = $state<HTMLElement>();
	let checkEl = $state<HTMLElement>();

	// помилка — потрушуємо повідомлення; успіх — пульс галочки
	$effect(() => {
		if (err && errEl) shake(errEl);
	});
	$effect(() => {
		if (done === 'approved' && checkEl) pop(checkEl, 1.15);
	});

	async function load() {
		loading = true;
		try {
			info = await api.qrInfo(token);
		} catch (ex) {
			err = friendlyError(ex);
		}
	}

	$effect(() => {
		if (auth.restored && auth.isAuthed && !loading) load();
	});

	async function approve() {
		busy = true;
		err = '';
		try {
			await api.qrApprove(token, picked);
			done = 'approved';
		} catch (ex) {
			err = friendlyError(ex);
			info = null;
		} finally {
			busy = false;
		}
	}

	async function deny() {
		busy = true;
		try {
			await api.qrDeny(token);
		} catch {
			/* запит і так згасне за 2 хв */
		}
		busy = false;
		done = 'denied';
	}

	const toApp = () => goto('/accounts');
	const toLogin = () => goto(`/login?next=${encodeURIComponent('/qr/' + token)}`);
</script>

<svelte:head
	><title>Підтвердження входу · M1 ID</title><meta name="robots" content="noindex" /></svelte:head
>

{#if auth.restored && !auth.isAuthed}
	<AppModal open title="Вхід на іншому пристрої" icon={Monitor} width={420} onclose={toLogin}>
		<p>
			Хтось просить увійти в M1 ID за цим QR. Щоб підтвердити, спершу увійдіть у свій акаунт на
			цьому пристрої.
		</p>
		<p class="text-dim">
			Після входу ви автоматично повернетеся сюди, і ми покажемо запит на підтвердження входу на
			іншому пристрої. Вхід там буде виконано лише після вашого підтвердження.
		</p>
		{#snippet footer()}
			<button class="btn btn-primary" onclick={toLogin}>Увійти</button>
		{/snippet}
	</AppModal>
{:else if auth.isAuthed}
	<AppModal
		open
		title="Підтвердити вхід?"
		icon={ShieldCheck}
		width={420}
		onclose={toApp}
		tone={done === 'approved' ? 'success' : 'accent'}
	>
		{#if done === 'approved'}
			<div class="done" in:blurFade={{ y: 6 }}>
				<span class="okmark" bind:this={checkEl} aria-hidden="true">
					<svg viewBox="0 0 52 52" width="56" height="56">
						<circle class="ok-c" cx="26" cy="26" r="23" pathLength="1" />
						<path class="ok-p" d="M15 27 l8 8 l15 -17" pathLength="1" />
					</svg>
				</span>
				<p>Готово — пристрій зараз увійде в ваш акаунт.</p>
			</div>
		{:else if done === 'denied'}
			<p in:blurFade={{ y: 6 }}>❌ Запит відхилено.</p>
		{:else if info}
			<p>Хтось намагається увійти у ваш акаунт M1 ID:</p>
			<ul class="dev">
				<li>💻 {info.device}</li>
				<li>🌐 IP: <code>{info.ip}</code></li>
			</ul>
			<p>Оберіть <b>код, що показано на екрані</b> біля QR:</p>
			<div class="codes" use:stagger={{ step: 70, y: 14, scale: true }}>
				{#each info.options as o (o)}
					<button
						class="code"
						class:on={picked === o}
						class:dim={picked !== '' && picked !== o}
						use:pressable={{ scale: 0.94 }}
						onclick={() => (picked = o)}>{o}</button
					>
				{/each}
			</div>
			<p class="text-dim small">Не ви? Натисніть «Відхилити» і нікому не показуйте цей екран.</p>
		{:else if !err}
			<p class="text-dim">Завантаження…</p>
		{/if}
		{#if err}<p class="error" role="alert" bind:this={errEl} in:blurFade={{ y: 4 }}>⚠ {err}</p>{/if}

		{#snippet footer()}
			{#if done || (!info && err)}
				<button class="btn btn-primary" onclick={toApp}>Закрити</button>
			{:else if info}
				<button class="btn" disabled={busy} onclick={deny}>Відхилити</button>
				<button class="btn btn-primary" disabled={busy || !picked} onclick={approve}>
					Підтвердити
				</button>
			{/if}
		{/snippet}
	</AppModal>
{/if}

<style>
	.dev {
		list-style: none;
		padding: 0;
		margin: 8px 0;
		display: grid;
		gap: 4px;
	}
	.codes {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 10px;
		margin: 10px 0;
	}
	.code {
		font: inherit;
		font-size: 24px;
		font-weight: 800;
		padding: 14px 0;
		border-radius: var(--radius-md);
		border: 1px solid var(--glass-border);
		background: var(--surface);
		color: var(--text);
		cursor: pointer;
		transition:
			background var(--dur-base) ease,
			border-color var(--dur-base) ease,
			color var(--dur-base) ease,
			opacity var(--dur-slow) var(--ease-out),
			scale 420ms var(--ease-spring);
	}
	.code.on {
		border-color: var(--accent);
		background: var(--accent);
		color: #fff;
		scale: 1.07;
	}
	.code.dim {
		opacity: 0.45;
		scale: 0.96;
	}
	.done {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 8px;
		text-align: center;
	}
	.okmark svg {
		fill: none;
		stroke: var(--success, var(--accent));
		stroke-width: 3;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.ok-c,
	.ok-p {
		stroke-dasharray: 1;
		stroke-dashoffset: 1;
	}
	.ok-c {
		animation: qt-draw 480ms var(--ease-out) 80ms forwards;
	}
	.ok-p {
		animation: qt-draw 340ms var(--ease-out) 420ms forwards;
	}
	@keyframes qt-draw {
		to { stroke-dashoffset: 0; }
	}
	:global(html[data-anim='off']) :is(.ok-c, .ok-p) {
		animation: none;
		stroke-dashoffset: 0;
	}
	:global(html[data-anim='off']) :is(.code, .code.on, .code.dim) {
		transition: none;
	}
	.small {
		font-size: 12.5px;
	}
	.error {
		color: var(--danger);
	}
</style>
