<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api, ApiError } from '$lib/api/client';
	import { auth } from '$lib/stores/auth.svelte';
	import { PROJECT_NAME } from '$lib/config';
	import { friendlyError } from '$lib/errors';
	import LoginQr from '$lib/components/LoginQr.svelte';
	import { slideX, springIn, blurFade, shake, pressable, magnetic, motionOK, ease } from '$lib/motion';

	let mode = $state<'login' | 'register'>(
		page.url.searchParams.get('mode') === 'register' ? 'register' : 'login'
	);
	let loginValue = $state('');
	let password = $state('');
	let email = $state('');
	let busy = $state(false);
	let err = $state('');
	let cardEl = $state<HTMLElement>();
	// напрямок перемикання вкладок: вперед (Реєстрація) = 1, назад = -1
	let dir = $state<1 | -1>(1);

	function setMode(m: 'login' | 'register'): void {
		if (m === mode) return;
		dir = m === 'register' ? 1 : -1;
		mode = m;
		err = '';
	}

	// поява картки: пружина + розмиття
	onMount(() => {
		if (!motionOK() || !cardEl) return;
		cardEl.animate(
			[
				{ opacity: 0, transform: 'translateY(22px) scale(0.95)', filter: 'blur(10px)' },
				{ opacity: 1, transform: 'none', filter: 'blur(0)' }
			],
			{ duration: 560, easing: ease('spring') }
		);
	});

	// невдала відправка — трясемо картку
	$effect(() => {
		if (err && cardEl) shake(cardEl);
	});

	// next - лише внутрішній шлях (повернення до підтвердження QR тощо)
	const rawNext = page.url.searchParams.get('next') ?? '';
	const next = /^\/(?!\/)[\w\-./]*$/.test(rawNext) ? rawNext : '/accounts';
	const fromQr = next.startsWith('/qr/');

	// QR показуємо збоку лише на широких екранах (з телефона самому себе не відсканувати)
	let wide = $state(false);
	onMount(() => {
		const mq = window.matchMedia('(min-width: 780px)');
		const upd = () => (wide = mq.matches);
		upd();
		mq.addEventListener('change', upd);
		return () => mq.removeEventListener('change', upd);
	});
	const showQr = $derived(wide && mode === 'login' && !fromQr);

	$effect(() => {
		if (auth.restored && auth.isAuthed) goto(next);
	});

	async function submit(e: SubmitEvent) {
		e.preventDefault();
		err = '';
		busy = true;
		try {
			const pair =
				mode === 'login'
					? await api.login({ login: loginValue, password })
					: await api.register({ username: loginValue, password, email });
			auth.setSession(pair);
			goto(next);
		} catch (ex) {
			err = friendlyError(ex);
		} finally {
			busy = false;
		}
	}
</script>

<svelte:head><title>Вхід · M1 ID</title><meta name="robots" content="noindex, follow" /></svelte:head>

<section class="wrap">
	<div class="glass card" class:two={showQr} bind:this={cardEl}>
		<div class="main">
		<h1>Вхід до <span class="accent-text">{PROJECT_NAME}</span></h1>
		<p class="text-dim sub">
			{mode === 'login'
				? 'Увійди у свій єдиний акаунт.'
				: 'Створи акаунт: логін, пароль і e-mail.'}
		</p>

		{#if fromQr}
			<p class="notice">
				🔐 Увійдіть у свій акаунт - і ви одразу повернетеся до підтвердження входу на іншому
				пристрої.
			</p>
		{/if}

		<div class="tabs" role="tablist" data-mode={mode}>
			<span class="pill" aria-hidden="true"></span>
			<button class:active={mode === 'login'} use:pressable={{ scale: 0.97 }} onclick={() => setMode('login')}
				>Вхід</button
			>
			<button
				class:active={mode === 'register'}
				use:pressable={{ scale: 0.97 }}
				onclick={() => setMode('register')}>Реєстрація</button
			>
		</div>

		{#key mode}
		<form onsubmit={submit} in:slideX={{ dir, distance: 36, duration: 380 }}>
			<label>
				<span>{mode === 'login' ? 'Логін або e-mail' : 'Логін'}</span>
				<input required minlength={mode === 'register' ? 3 : 1}
					maxlength={32} bind:value={loginValue}
					autocomplete="username" autocapitalize="none"
					spellcheck="false" placeholder="mystat_user" />
			</label>

			{#if mode === 'register'}
				<label>
					<span>E-mail</span>
					<input required type="email" bind:value={email}
						autocomplete="email" inputmode="email"
						placeholder="you@gmail.com" />
				</label>
			{/if}

			<label>
				<span>Пароль</span>
				<input required type="password" bind:value={password}
					minlength={mode === 'register' ? 8 : 1} placeholder="••••••••"
					autocomplete={mode === 'login'
						? 'current-password'
						: 'new-password'} />
			</label>

			{#if err}
				<p class="error" role="alert" in:blurFade={{ y: 4, duration: 260 }}>⚠ {err}</p>
			{/if}

			<button class="btn btn-primary wide" disabled={busy} use:magnetic={{ strength: 0.12 }} use:pressable>
				{busy ? '…' : mode === 'login' ? 'Увійти' : 'Створити акаунт'}
			</button>
		</form>
		{/key}
		</div>

		{#if showQr}
			<aside class="side" in:springIn={{ start: 0.92, duration: 480, delay: 160, y: 12 }}><LoginQr onlogin={() => goto(next)} /></aside>
		{/if}
	</div>
</section>

<style>
	.wrap {
		display: flex;
		justify-content: center;
		padding-top: clamp(16px, 8vh, 64px);
	}

	.main {
		display: flex;
		flex-direction: column;
		gap: 18px;
	}

	.card.two {
		width: min(800px, 100%);
		display: grid;
		grid-template-columns: minmax(0, 1fr) 260px;
		gap: 0 32px;
		align-items: center;
	}

	.side {
		border-left: 1px solid var(--glass-border);
		padding-left: 32px;
	}

	.card {
		width: min(440px, 100%);
		padding: clamp(24px, 5vw, 40px);
		display: flex;
		flex-direction: column;
		gap: 18px;
	}

	h1 {
		font-size: clamp(20px, 3.4vw, 26px);
	}

	.sub {
		font-size: 14px;
		margin-top: -10px;
	}

	.tabs {
		position: relative;
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 6px;
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		padding: 5px;
		border-radius: var(--radius-md);
	}

	/* активна «пігулка» їде між вкладками пружиною */
	.pill {
		position: absolute;
		top: 5px;
		bottom: 5px;
		left: 5px;
		width: calc((100% - 16px) / 2);
		border-radius: calc(var(--radius-md) - 3px);
		background: var(--accent);
		transition: transform 460ms var(--ease-spring);
	}
	.tabs[data-mode='register'] .pill {
		transform: translateX(calc(100% + 6px));
	}

	.tabs button {
		position: relative;
		font: inherit;
		font-size: 14px;
		font-weight: 600;
		padding: 8px;
		border: none;
		border-radius: calc(var(--radius-md) - 3px);
		background: transparent;
		color: var(--text-dim);
		cursor: pointer;
		transition: color 0.25s ease;
	}

	.tabs button.active {
		color: #fff;
	}
	:global(html[data-anim='off']) .pill {
		transition: none;
	}

	form {
		display: flex;
		flex-direction: column;
		gap: 14px;
	}

	label {
		display: flex;
		flex-direction: column;
		gap: 6px;
		font-size: 13.5px;
		color: var(--text-dim);
	}

	input {
		font: inherit;
		color: var(--text);
		background: var(--surface);
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-sm);
		padding: 11px 14px;
		outline: none;
		transition: border-color 0.2s ease;
	}

	input:focus {
		border-color: var(--accent);
	}

	.notice {
		font-size: 13.5px;
		padding: 10px 12px;
		border-radius: var(--radius-sm);
		background: var(--glass-bg);
		border: 1px solid var(--accent);
	}

	.error {
		color: var(--danger);
		background: rgba(248, 113, 113, 0.08);
		border: 1px solid rgba(248, 113, 113, 0.25);
		border-radius: var(--radius-sm);
		padding: 10px 12px;
		font-size: 13.5px;
	}

	.wide {
		width: 100%;
		margin-top: 4px;
	}

	@media (max-width: 640px) {
		.wrap {
			padding-top: 20px;
		}

		.card {
			padding: 22px 18px;
			gap: 14px;
		}

		/* великий тап-таргет для головної кнопки */
		.wide {
			padding: 13px;
		}

		.tabs button {
			padding: 10px;
		}
	}
</style>
