<script lang="ts">
	import type { TransitionConfig } from 'svelte/transition';
	import { cubicIn } from 'svelte/easing';
	import { LogIn } from '@lucide/svelte';
	import BootCube from '$lib/components/BootCube.svelte';
	import { Button, Field, Input } from '$lib/ui';
	import { springIn, blurFade, shake, motionOK, fx } from '$lib/motion';

	interface Props {
		needRelogin: boolean;
		err: string;
		/** Акаунтів немає й бут завершено. */
		noAccounts: boolean;
		bootNote: string;
		bootProgress: number | null;
		relogLogin: string;
		relogPass: string;
		relogBusy: boolean;
		relogErr: string;
		doRelogin: (e: SubmitEvent) => void;
		onretry: () => void;
	}
	let {
		needRelogin,
		err,
		noAccounts,
		bootNote,
		bootProgress,
		relogLogin = $bindable(),
		relogPass = $bindable(),
		relogBusy,
		relogErr,
		doRelogin,
		onretry
	}: Props = $props();

	/** Вихід бут-екрана, коли прийшли дані: scale + fade (+ blur лише на рівні full; дашборд проявляється під ним). */
	function bootOut(_n: Element): TransitionConfig {
		if (!motionOK()) return { duration: 0 };
		// blur на повноекранному шарі дорогий: лише на «full», і з меншим радіусом
		const blur = fx();
		return {
			duration: 460,
			easing: cubicIn,
			css: (t, u) =>
				`opacity:${t};transform:scale(${1 + u * 0.04})` + (blur ? `;filter:blur(${u * 10}px)` : '')
		};
	}

	// помилка входу: форма «трусить»
	let formEl = $state<HTMLElement | null>(null);
	$effect(() => {
		if (relogErr && formEl) shake(formEl);
	});
</script>

<div class="boot" out:bootOut|global>
	{#if needRelogin}
		<section class="glass empty-card relog" in:springIn={{ duration: 420, start: 0.95, y: 10 }}>
			<h1>Акаунт потребує повторного входу</h1>
			<p class="text-dim">
				Токен MyStat недійсний (наприклад, після зміни ключа шифрування
				на сервері). Впиши логін і пароль MyStat прямо тут — бекенд
				оновить токен того самого акаунта: дані, налаштування та
				Telegram-лінки залишаться на місці.
			</p>
			<form class="relog-form" onsubmit={doRelogin} bind:this={formEl}>
				<Field label="Логін або email MyStat" required>
					{#snippet children({ id, describedBy })}
						<Input
							{id}
							aria-describedby={describedBy}
							type="text"
							bind:value={relogLogin}
							placeholder="Логін або email MyStat"
							autocomplete="username"
							required
						/>
					{/snippet}
				</Field>
				<Field label="Пароль MyStat" required>
					{#snippet children({ id, describedBy })}
						<Input
							{id}
							aria-describedby={describedBy}
							type="password"
							bind:value={relogPass}
							placeholder="Пароль MyStat"
							autocomplete="current-password"
							required
						/>
					{/snippet}
				</Field>
				{#if relogErr}
					<p class="relog-err" role="alert" in:blurFade={{ duration: 260, amount: 6, y: 4 }}>{relogErr}</p>
				{/if}
				<Button type="submit" icon={LogIn} loading={relogBusy} block>
					{relogBusy ? 'Входимо…' : 'Увійти та відновити'}
				</Button>
			</form>
			<Button href="/accounts" variant="ghost">Керувати акаунтами →</Button>
		</section>
	{:else if err}
		<section class="glass empty-card" in:springIn={{ duration: 420, start: 0.95, y: 10 }}>
			<h1>Помилка</h1>
			<p class="text-dim">{err}</p>
			<Button onclick={onretry}>Спробувати знову</Button>
		</section>
	{:else if noAccounts}
		<section class="glass empty-card" in:springIn={{ duration: 420, start: 0.95, y: 10 }}>
			<h1>Ще немає підключеного акаунту</h1>
			<p class="text-dim">Підключи MyStat — і тут з’являться твої дані.</p>
			<Button href="/accounts">До акаунтів →</Button>
		</section>
	{:else}
		<BootCube note={bootNote} progress={bootProgress} />
	{/if}
</div>

<style>
	/* фіксований шар: при виході не штовхає дашборд, що з'являється під ним */
	.boot {
		position: fixed;
		inset: 0;
		z-index: 50;
		display: grid;
		place-items: center;
		padding: 24px;
		background: var(--color-bg);
	}

	.empty-card {
		padding: 40px;
		display: flex;
		flex-direction: column;
		gap: 14px;
		align-items: flex-start;
		max-width: 520px;
	}

	/* інлайн-релогін: форма входу в MyStat прямо на екрані бута */
	.relog-form {
		display: flex;
		flex-direction: column;
		gap: 12px;
		width: 100%;
		margin-top: 4px;
	}
	.relog-err {
		margin: 0;
		font-size: 13px;
		color: var(--danger);
	}
</style>
