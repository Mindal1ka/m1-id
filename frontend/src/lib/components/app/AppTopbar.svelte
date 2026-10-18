<script lang="ts">
	import { ChevronDown, LayoutDashboard, RefreshCw, WifiOff } from '@lucide/svelte';
	import type { AccountOut } from '$lib/api/client';
	import type { Tab } from '$lib/app/helpers';
	import { blurFade, motionOK, ease, pressable } from '$lib/motion';

	interface Props {
		title: string;
		tab: Tab;
		offline: boolean;
		accounts: AccountOut[];
		activeId: number | null;
		/** Якась вкладка зараз вантажиться (крутимо іконку оновлення). */
		busy: boolean;
		/** Вміст прокручено більше ніж на 8px: топбар отримує тінь і стискає заголовок. */
		scrolled?: boolean;
		editHome: boolean;
		switchTo: (e: Event) => void;
		onrefresh: () => void;
	}
	let {
		title,
		tab,
		offline,
		accounts,
		activeId,
		busy,
		scrolled = false,
		editHome = $bindable(),
		switchTo,
		onrefresh
	}: Props = $props();

	// Іконка оновлення: один плавний оберт 360° із пружиною на початку спінінгу;
	// якщо завантаження триває — повторюємо.
	let spinEl = $state<HTMLElement | null>(null);
	let spinning = false;
	function spinOnce(): void {
		if (!spinEl || !motionOK()) {
			spinning = false;
			return;
		}
		spinning = true;
		const a = spinEl.animate([{ transform: 'rotate(0deg)' }, { transform: 'rotate(360deg)' }], {
			duration: 760,
			easing: ease('spring')
		});
		a.onfinish = () => {
			if (busy) spinOnce();
			else spinning = false;
		};
	}
	$effect(() => {
		if (busy && !spinning) spinOnce();
	});
</script>

<header class="topbar frosted" class:scrolled>
	<h1>{title}</h1>
	{#if offline}
		<span class="status-pill" role="status" in:blurFade={{ duration: 260, amount: 6 }} out:blurFade={{ duration: 180, amount: 6 }}
			><WifiOff size={13} strokeWidth={2} />офлайн</span
		>
	{/if}
	<div class="top-actions">
		{#if accounts.length > 1}
			<div class="select-wrap">
				<select value={String(activeId)} onchange={switchTo} aria-label="Акаунт MyStat">
					{#each accounts as a (a.id)}
						<option value={String(a.id)}>{a.login || a.fio || a.label}</option>
					{/each}
				</select>
				<ChevronDown size={16} strokeWidth={2} class="sel-chev" />
			</div>
		{/if}
		<button
			type="button"
			class="icon-btn"
			use:pressable={{ scale: 0.9 }}
			onclick={onrefresh}
			disabled={busy}
			aria-label="Оновити"
			title="Оновити дані"
		>
			<span class="spin-wrap" bind:this={spinEl}><RefreshCw size={18} strokeWidth={2} /></span>
		</button>
		{#if tab === 'home'}
			<button
				type="button"
				class="icon-btn"
				use:pressable={{ scale: 0.9 }}
				class:on={editHome}
				aria-pressed={editHome}
				onclick={() => (editHome = !editHome)}
				aria-label="Віджети"
				title="Налаштування віджетів"
			>
				<LayoutDashboard size={18} strokeWidth={2} />
			</button>
		{/if}
	</div>
</header>

<style>
	.topbar {
		position: sticky;
		top: 0;
		z-index: var(--z-sticky);
		flex-shrink: 0;
		display: flex;
		align-items: center;
		gap: var(--space-3);
		height: calc(var(--topbar-h) + var(--safe-top));
		padding: var(--safe-top) max(var(--space-6), env(safe-area-inset-right)) 0
			max(var(--space-6), env(safe-area-inset-left));
	}

	/* нижня риска + тінь: окремий шар, анімується лише opacity */
	.topbar::after {
		content: '';
		position: absolute;
		left: 0;
		right: 0;
		bottom: 0;
		height: 1px;
		background: var(--color-border);
		box-shadow: 0 8px 18px -8px rgba(0, 0, 0, 0.35);
		opacity: 0;
		pointer-events: none;
		transition: opacity 260ms var(--ease-out);
	}
	.topbar.scrolled::after {
		opacity: 1;
	}

	.spin-wrap {
		display: grid;
		place-items: center;
	}

	h1 {
		transform-origin: left center;
		transition: transform 380ms var(--ease-spring);
		margin-right: auto;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: var(--text-lg);
		font-weight: var(--weight-semibold);
	}

	/* «компактний» заголовок: scale замість зміни font-size (без layout) */
	.topbar.scrolled h1 {
		transform: scale(0.88);
	}

	.top-actions {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}

	.status-pill {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 3px 10px;
		font-size: var(--text-xs);
		font-weight: var(--weight-medium);
		color: var(--color-warning);
		background: var(--color-warning-soft);
		border: 1px solid color-mix(in srgb, var(--color-warning) 35%, transparent);
		border-radius: var(--radius-full);
	}

	.select-wrap {
		position: relative;
		display: flex;
		align-items: center;
	}
	select {
		appearance: none;
		-webkit-appearance: none;
		height: 36px;
		max-width: 200px;
		padding: 0 calc(var(--space-3) + 20px) 0 var(--space-3);
		font: inherit;
		font-size: var(--text-md);
		color: var(--color-text);
		background: var(--color-surface-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		cursor: pointer;
	}
	select:hover {
		border-color: var(--color-border-strong);
	}
	.select-wrap :global(.sel-chev) {
		position: absolute;
		right: var(--space-2);
		color: var(--color-text-muted);
		pointer-events: none;
	}

	.icon-btn {
		display: grid;
		place-items: center;
		width: 36px;
		height: 36px;
		color: var(--color-text-muted);
		background: transparent;
		border: 1px solid transparent;
		border-radius: var(--radius-md);
		cursor: pointer;
		transition:
			background var(--dur-fast) ease,
			color var(--dur-fast) ease;
	}
	.icon-btn:hover:not(:disabled) {
		background: var(--color-hover);
		color: var(--color-text);
	}
	.icon-btn:disabled {
		opacity: 0.5;
	}
	.icon-btn.on {
		background: var(--color-accent-soft);
		color: var(--color-accent-text);
	}

	:global(html[data-anim='off']) .topbar::after,
	:global(html[data-anim='off']) h1 {
		transition: none;
	}

	@media (max-width: 900px) {
		.topbar {
			padding-inline: max(var(--space-4), env(safe-area-inset-left));
		}
	}
	@media (max-width: 640px) {
		select {
			max-width: 140px;
		}
	}
</style>
