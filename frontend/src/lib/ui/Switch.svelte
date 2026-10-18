<script lang="ts">
	import type { HTMLButtonAttributes } from 'svelte/elements';

	interface Props extends Omit<HTMLButtonAttributes, 'onchange' | 'role'> {
		checked?: boolean;
		disabled?: boolean;
		/** Текст для aria-label. */
		label?: string;
		onchange?: (checked: boolean) => void;
	}

	let {
		checked = $bindable(false),
		disabled = false,
		label,
		onchange,
		class: klass = '',
		...rest
	}: Props = $props();

	// натиснутий стан: «великий палець» розтягується, як в iOS
	let pressing = $state(false);

	function toggle() {
		if (disabled) return;
		checked = !checked;
		onchange?.(checked);
	}
</script>

<button
	type="button"
	role="switch"
	aria-checked={checked}
	aria-label={label}
	{disabled}
	class="sw {klass}"
	class:on={checked}
	class:pressing
	onclick={toggle}
	onpointerdown={() => !disabled && (pressing = true)}
	onpointerup={() => (pressing = false)}
	onpointerleave={() => (pressing = false)}
	onpointercancel={() => (pressing = false)}
	{...rest}
>
	<span class="fill"></span>
	<span class="thumb"></span>
</button>

<style>
	.sw {
		position: relative;
		flex-shrink: 0;
		width: 44px;
		height: 26px;
		padding: 0;
		background: var(--color-border-strong);
		border: 0;
		border-radius: var(--radius-full);
		cursor: pointer;
	}
	/* трек: акцентний шар плавно проявляється поверх сірого (crossfade) */
	.fill {
		position: absolute;
		inset: 0;
		background: var(--color-accent);
		border-radius: inherit;
		opacity: 0;
		transition: opacity 280ms var(--ease-out);
	}
	.on .fill {
		opacity: 1;
	}
	.thumb {
		position: absolute;
		top: 2px;
		left: 2px;
		width: 22px;
		height: 22px;
		background: var(--color-text-on-accent);
		border-radius: 50%;
		box-shadow: var(--shadow-sm);
		transform-origin: 0 50%;
		transition:
			transform 460ms var(--ease-spring),
			background-color 200ms ease;
	}
	.on .thumb {
		transform: translateX(18px);
		transform-origin: 100% 50%;
	}
	/* при натисканні палець витягується в бік руху */
	.pressing .thumb {
		transform: scaleX(1.28);
	}
	.pressing.on .thumb {
		transform: translateX(18px) scaleX(1.28);
	}
	/* Темна тема (і неон): вимкнений стан має видиму доріжку з рамкою та світлий повзунок.
	   Рамка — inset-тінь на кнопці; ввімкнений .fill її перекриває. */
	:global(html[data-scheme='dark']) .sw {
		background: color-mix(in srgb, var(--text) 16%, transparent);
		box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--text) 42%, transparent);
	}
	:global(html[data-scheme='dark']) .sw:not(.on) .thumb {
		background: color-mix(in srgb, var(--text) 82%, transparent);
	}
	:global(html[data-anim='off']) .fill,
	:global(html[data-anim='off']) .thumb {
		transition: none;
	}
	:global(html[data-anim='off']) .pressing .thumb {
		transform: none;
	}
	:global(html[data-anim='off']) .pressing.on .thumb {
		transform: translateX(18px);
	}
	.sw:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
	.sw:focus-visible {
		outline: 2px solid var(--color-accent);
		outline-offset: 2px;
		border-radius: var(--radius-full);
	}
	/* зона тапу ≥40px на мобільному без зміни вигляду */
	.sw::before {
		content: '';
		position: absolute;
		inset: -8px -4px;
	}
</style>
