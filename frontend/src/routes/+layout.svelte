<script lang="ts">
	import '@fontsource-variable/inter';
	import '@fontsource/unbounded/700.css';
	import '@fontsource/unbounded/900.css';
	import '$lib/design/tokens.css';
	import '$lib/motion/motion.css';

	import favicon from '$lib/assets/favicon.svg';
	import Aurora from '$lib/components/Aurora.svelte';
	import UpdateGate from '$lib/components/UpdateGate.svelte';
	import { ToastHost, ConfirmHost } from '$lib/ui';
	import { applyPerf, autoEnter } from '$lib/motion';
	import { auth } from '$lib/stores/auth.svelte';
	import { clearPerAccountCache } from '$lib/stores/appStore.svelte';
	import { theme } from '$lib/theme.svelte';
	import { fx } from '$lib/fx.svelte';
	import { PROJECT_NAME } from '$lib/config';
	import { api } from '$lib/api/client';
	import { dev } from '$app/environment';
	import { page } from '$app/state';
	import { purgeAllCaches } from '$lib/cachePurge';

	let { children } = $props();

	async function logout() {
		try {
			if (auth.refreshToken) await api.logout(auth.refreshToken);
		} catch {
			/* сервер міг уже відкликати сесію — не важливо */
		}
		// H7: разом із сесією чистимо ПЕР-АКАУНТНИЙ кеш (m1id.cache.*,
		// fs_menu_*, m1id.accounts, m1id.lastAccount) — інший користувач на тому ж
		// пристрої не має стартувати на кеші попереднього (чужі ФІО).
		clearPerAccountCache();
		auth.clear();
	}
	auth.restore();
	// Примусовий logout (refresh відмовив → auth.clear() у client.ts) теж має
	// чистити пер-акаунтний кеш, не лише ручний logout().
	let wasAuthed = auth.isAuthed;
	$effect(() => {
		const now = auth.isAuthed;
		if (wasAuthed && !now) clearPerAccountCache();
		wasAuthed = now;
	});
	theme.restore();
	fx.restore();
	// рівень продуктивності анімацій (auto: пам'ять/ядра/FPS або вибір у налаштуваннях)
	if (typeof document !== 'undefined') applyPerf();

	// єдиний двигун появи карток/рядків для всього застосунку (див. $lib/motion)
	$effect(() => {
		const a = autoEnter(document.body);
		return () => a?.destroy?.();
	});

	// '/' — лендінг: повноекранний, зі власною навігацією (глобальний хедер не малюємо)
	const isApp = $derived(
		page.url.pathname.startsWith('/app') ||
			page.url.pathname === '/' ||
			// лендінг — повноекранна копія головної сторінки, без хедера
			page.url.pathname === '/landing'
	);

	// PWA-життєвий цикл — детерміновані оновлення:
	// кожен білд штампується рандомними числами (__BUILD_STAMP__ вшитий в
	// бандл == build/version.json == build/sw.js). Раз на хвилину (і на
	// старті) питаємо в сервера /version.json:
	//   • збігається → тихо працюємо далі;
	//   • відрізняється → блокуючий блюр-оверлей з модалкою «Оновити»
	//     (UpdateGate): чистить SW + кеші (дані користувача не чіпає) і
	//     перезавантажує вкладку вже на нову збірку.
	// Навмисно БЕЗ toast-ів, «пізніше» та очікування активації воркера:
	// релоад після очищення кешів дає гарантію свіжої збірки навіть якщо
	// попереднє оновлення було отруєне деплоєм «на живу».
	let updateV = $state('');

	async function fetchVersion(): Promise<string | null> {
		try {
			// no-store + bypass у sw.js → завжди живе значення з сервера
			const r = await fetch('/version.json', { cache: 'no-store' });
			if (!r.ok) return null;
			const j: unknown = await r.json();
			return typeof j === 'object' && j !== null && 'v' in j
				? String((j as { v: unknown }).v)
				: null;
		} catch {
			return null; // офлайн - перевіримо на наступному тику
		}
	}

	async function checkUpdate(): Promise<void> {
		if (dev || !('serviceWorker' in navigator)) return;
		// Вкладка БЕЗ контролюючого воркера завантажилась НАПРЯМУ з
		// сервера (у неї ще ніколи не було воркера/PWA) - її код свіжий
		// на момент відкриття, гейт лише заважав би: нова версія прийде
		// сама зі звичайним перезавантаженням. Сторінка сама реєструє
		// SW - з наступного завантаження controller з'явиться і система
		// стане активною саме для тих, хто реально живе з кешем.
		// ВИПРАВКА: після періоду з невалідним sw.js контролер міг
		// померти, а вкладка лишиться на протухлому HTTP-кеші — тому
		// пам'ятаємо прапор «воркер колись був»: для таких вкладок
		// гейт перевіряє версію навіть без контролера.
		const SW_SEEN = 'm1id-sw-seen';
		if (navigator.serviceWorker.controller) {
			try { localStorage.setItem(SW_SEEN, '1'); } catch { /* приватний режим */ }
		} else {
			let seen = false;
			try { seen = localStorage.getItem(SW_SEEN) === '1'; } catch { /* noop */ }
			if (!seen) return;
		}
		const v = await fetchVersion();
		if (!v) return;
		if (v !== __BUILD_STAMP__) updateV = v; // модалка оновлення
	}

	$effect(() => {
		if (dev || !('serviceWorker' in navigator)) return;

		let intervalId: number | undefined;
		let onVis: (() => void) | undefined;
		let onOnline: (() => void) | undefined;

		navigator.serviceWorker
			.register('/sw.js', { updateViaCache: 'none' })
			.catch((e) => console.error('[pwa] SW НЕ зареєстровано:', e));

		void checkUpdate(); // старт
		intervalId = window.setInterval(() => void checkUpdate(), 60_000); // щохвилини
		onVis = () => {
			if (!document.hidden) void checkUpdate();
		};
		onOnline = () => void checkUpdate();
		document.addEventListener('visibilitychange', onVis);
		window.addEventListener('online', onOnline);

		return () => {
			if (intervalId !== undefined) window.clearInterval(intervalId);
			if (onVis) document.removeEventListener('visibilitychange', onVis);
			if (onOnline) window.removeEventListener('online', onOnline);
		};
	});

	// після оновлення прибираємо службовий ?v= з адреси (чистий URL);
	// сам обмін ?v= на свіжий HTML відбувається ще ДО реєстрації нового SW
	if (typeof window !== 'undefined') {
		const u = new URL(window.location.href);
		if (u.searchParams.has('v')) {
			u.searchParams.delete('v');
			history.replaceState(history.state, '', u.href);
		}
	}
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<Aurora />

{#if !isApp}
	<header>
		<nav>
			<a class="brand" href="/landing">
				<span>{PROJECT_NAME}</span>
			</a>
			<div class="links">
				{#if auth.isAuthed}
					<a href="/accounts">Акаунти</a>
					{#if auth.user}
						<span class="chip">👋 {auth.user.username}</span>
					{/if}
					<button class="btn ghost" onclick={logout}>Вийти</button>
				{:else}
					<a href="/login">Увійти</a>
				{/if}
			</div>
		</nav>
	</header>
	<main class="page-main">
		{@render children()}
	</main>
{:else}
	{@render children()}
{/if}

<!-- глобальні хости UI-кіту: тости та confirm() -->
<ToastHost />
<ConfirmHost />

{#if updateV}
	<UpdateGate version={updateV} />
{/if}

<style>
	header {
		position: sticky;
		top: 0;
		z-index: 10;
		/* у PWA-стендалоні не ліземо під «ніс»/статус-бар */
		padding-top: env(safe-area-inset-top, 0px);
		background: color-mix(in srgb, var(--bg) 75%, transparent);
		-webkit-backdrop-filter: blur(12px);
		backdrop-filter: blur(12px);
		border-bottom: 1px solid var(--glass-border);
	}

	nav {
		max-width: 1080px;
		margin: 0 auto;
		padding: 12px clamp(16px, 4vw, 48px);
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}

	.brand {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		font-family: var(--font-display);
		font-weight: 700;
		font-size: 18px;
		color: var(--text);
		text-decoration: none;
		letter-spacing: 0.02em;
		transition: color 0.2s ease;
	}
	.brand:hover {
		color: var(--accent);
	}

	.links {
		display: flex;
		align-items: center;
		gap: 10px;
		font-size: 14px;
	}

	.links a {
		color: var(--text-dim);
		text-decoration: none;
		padding: 6px 10px;
		border-radius: var(--radius-sm);
	}

	.links a:hover {
		color: var(--text);
		background: var(--glass-bg);
	}

	.btn.ghost {
		padding: 6px 12px;
		font-size: 13px;
	}

	.page-main {
		max-width: 1080px;
		margin: 0 auto;
		padding: clamp(16px, 3vw, 32px) clamp(16px, 4vw, 48px) 48px;
	}
</style>
