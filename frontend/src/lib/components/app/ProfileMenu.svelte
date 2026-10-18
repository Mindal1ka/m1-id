<script lang="ts">
	import { fade } from 'svelte/transition';
	import { tick } from 'svelte';
	import { ArrowLeftRight, MonitorSmartphone, Settings, UserRound } from '@lucide/svelte';
	import type { Dashboard } from '$lib/api/client';
	import { initials } from '$lib/sections';
	import { springIn, pressable } from '$lib/motion';

	interface Props {
		menuOpen: boolean;
		user: Dashboard['user'];
		onprofile: () => void;
		onsettings: () => void;
		onsessions: () => void;
	}
	let { menuOpen = $bindable(), user, onprofile, onsettings, onsessions }: Props = $props();

	/** Пункт меню: спершу плавно закриваємо меню, потім виконуємо дію. */
	function pick(action: () => void): void {
		menuOpen = false;
		action();
	}

	let menuEl = $state<HTMLElement | null>(null);
	let trigger: HTMLElement | null = null;

	// Запам'ятовуємо тригер при відкритті, повертаємо фокус при закритті.
	$effect(() => {
		if (menuOpen) {
			trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
			void tick().then(() => items()[0]?.focus());
		} else if (trigger) {
			if (trigger.isConnected) trigger.focus();
			trigger = null;
		}
	});

	function items(): HTMLElement[] {
		return menuEl ? Array.from(menuEl.querySelectorAll<HTMLElement>('[role="menuitem"]')) : [];
	}

	function onkeydown(e: KeyboardEvent): void {
		const list = items();
		const i = list.indexOf(document.activeElement as HTMLElement);
		let next = -1;
		if (e.key === 'ArrowDown') next = (i + 1) % list.length;
		else if (e.key === 'ArrowUp') next = (i - 1 + list.length) % list.length;
		else if (e.key === 'Home') next = 0;
		else if (e.key === 'End') next = list.length - 1;
		else if (e.key === 'Escape') {
			e.preventDefault();
			e.stopPropagation();
			menuOpen = false;
			return;
		} else if (e.key === 'Tab') {
			e.preventDefault();
			menuOpen = false;
			return;
		}
		if (next >= 0) {
			e.preventDefault();
			list[next]?.focus();
		}
	}
</script>

{#if menuOpen}
	<button
		type="button"
		class="scrim"
		aria-label="Закрити меню"
		tabindex="-1"
		onclick={() => (menuOpen = false)}
		transition:fade={{ duration: 130 }}
	></button>
	<div
		class="pmenu"
		role="menu"
		aria-label="Профіль і акаунти"
		tabindex="-1"
		bind:this={menuEl}
		{onkeydown}
		in:springIn={{ duration: 360, start: 0.94, y: 8 }}
		out:springIn={{ duration: 160, start: 0.96, y: 4 }}
	>
		<div class="pm-head" in:springIn|global={{ delay: 40, duration: 360, start: 0.94, y: 6 }}>
			<div class="pm-avatar">
				{#if user.photo_url}
					<img src={user.photo_url} alt={user.fio} />
				{:else}
					{initials(user.fio)}
				{/if}
			</div>
			<div class="pm-name">
				<b>{user.fio}</b>
				<span class:mono={!user.branch_name}>{user.branch_name || user.branch_alias}</span>
			</div>
		</div>
		<div class="sep" role="separator"></div>
		<button type="button" class="pm-item" role="menuitem" tabindex="-1" use:pressable={{ scale: 0.97 }} in:springIn|global={{ delay: 65, duration: 360, start: 0.94, y: 6 }} onclick={() => pick(onprofile)}>
			<UserRound size={18} strokeWidth={2} />
			Профіль
		</button>
		<button type="button" class="pm-item" role="menuitem" tabindex="-1" use:pressable={{ scale: 0.97 }} in:springIn|global={{ delay: 90, duration: 360, start: 0.94, y: 6 }} onclick={() => pick(onsettings)}>
			<Settings size={18} strokeWidth={2} />
			Налаштування
		</button>
		<button type="button" class="pm-item" role="menuitem" tabindex="-1" use:pressable={{ scale: 0.97 }} in:springIn|global={{ delay: 105, duration: 360, start: 0.94, y: 6 }} onclick={() => pick(onsessions)}>
		<MonitorSmartphone size={18} strokeWidth={2} />
			Сеанси
		</button>
		<div class="sep" role="separator"></div>
		<a class="pm-item" href="/accounts" role="menuitem" onclick={() => (menuOpen = false)} tabindex="-1" use:pressable={{ scale: 0.97 }} in:springIn|global={{ delay: 115, duration: 360, start: 0.94, y: 6 }}>
			<ArrowLeftRight size={18} strokeWidth={2} />
			Змінити акаунт
		</a>
	</div>
{/if}

<style>
	.scrim {
		position: fixed;
		inset: 0;
		z-index: var(--z-overlay);
		background: transparent;
		border: none;
		cursor: default;
	}

	.pmenu {
		position: fixed;
		left: var(--space-3);
		bottom: calc(var(--space-3) + 56px);
		z-index: var(--z-popover);
		width: calc(var(--sidebar-w) - 2 * var(--space-3));
		padding: var(--space-2);
		display: flex;
		flex-direction: column;
		gap: 2px;
		background: var(--color-elevated);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		box-shadow: var(--shadow-lg);
		/* з'являється з кута біля кнопки «Профіль» */
		transform-origin: bottom left;
	}

	.pm-head {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-2) var(--space-3);
	}

	.pm-avatar {
		width: 36px;
		height: 36px;
		flex-shrink: 0;
		border-radius: var(--radius-full);
		overflow: hidden;
		display: grid;
		place-items: center;
		background: var(--color-accent-soft);
		color: var(--color-accent-text);
		font-weight: var(--weight-bold);
		font-size: var(--text-md);
	}
	.pm-avatar img {
		width: 100%;
		height: 100%;
		object-fit: cover;
	}

	.pm-name {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
		font-size: var(--text-md);
	}
	.pm-name b {
		font-family: var(--font-display);
		font-weight: 700;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.mono {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--color-text-subtle);
	}

	.sep {
		height: 1px;
		margin: var(--space-1) 0;
		background: var(--color-border);
	}

	.pm-item {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		width: 100%;
		min-height: 40px;
		padding: 0 var(--space-3);
		border-radius: var(--radius-md);
		background: none;
		border: none;
		color: var(--color-text);
		font: inherit;
		font-size: var(--text-md);
		font-weight: var(--weight-medium);
		text-align: left;
		text-decoration: none;
		cursor: pointer;
	}
	.pm-item :global(svg) {
		color: var(--color-text-muted);
		flex-shrink: 0;
	}
	.pm-item:hover,
	.pm-item:focus-visible {
		background: var(--color-hover);
	}

	@media (max-width: 900px) {
		.pmenu {
			/* над плаваючою нижньою панеллю, праворуч (від кнопки «Профіль») */
			left: auto;
			right: max(var(--space-3), env(safe-area-inset-right));
			width: min(320px, calc(100vw - 2 * var(--space-3)));
			max-height: calc(100dvh - var(--nav-total, 76px) - var(--space-6));
			overflow-y: auto;
			overscroll-behavior: contain;
			bottom: calc(var(--nav-total, 76px) + var(--space-2));
			transform-origin: bottom right;
		}
		.scrim {
			background: var(--color-overlay);
			/* без скролу/прокидання жестів на сторінку під шаром */
			touch-action: none;
			-webkit-tap-highlight-color: transparent;
		}
		/* без «залиплого» hover на дотику */
		.pm-item:hover:not(:focus-visible) {
			background: none;
		}
	}
</style>
