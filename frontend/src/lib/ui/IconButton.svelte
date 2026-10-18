<script lang="ts">
	import type { Component } from 'svelte';
	import { pressable } from '$lib/motion';
	import type { HTMLButtonAttributes } from 'svelte/elements';

	interface Props extends Omit<HTMLButtonAttributes, 'children'> {
		icon: Component<any>;
		label: string;
		variant?: 'ghost' | 'secondary' | 'primary' | 'danger';
		size?: 'sm' | 'md' | 'lg';
	}

	let {
		icon: Icon,
		label,
		variant = 'ghost',
		size = 'md',
		type = 'button',
		class: klass = '',
		...rest
	}: Props = $props();

	const iconSize = $derived(size === 'sm' ? 16 : size === 'lg' ? 22 : 18);
</script>

<button class="ib {variant} {size} {klass}" use:pressable={{ scale: 0.9 }} {type} aria-label={label} title={label} {...rest}>
	<Icon size={iconSize} />
</button>

<style>
	.ib {
		position: relative;
		overflow: hidden;
		isolation: isolate;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		padding: 0;
		cursor: pointer;
		border: 1px solid transparent;
		transition:
			background var(--dur-fast) var(--ease-out),
			color var(--dur-fast) var(--ease-out),
			border-color var(--dur-fast) var(--ease-out);
	}
	.ib :global(svg) {
		transition: transform 320ms var(--ease-spring);
	}
	/* блиск на основній іконці-кнопці (лише миша) */
	.primary::after {
		content: '';
		position: absolute;
		inset: 0;
		pointer-events: none;
		opacity: 0;
		transform: translateX(-120%);
		background: linear-gradient(
			105deg,
			transparent 30%,
			color-mix(in srgb, white 32%, var(--color-accent)) 50%,
			transparent 70%
		);
	}
	@media (hover: hover) and (pointer: fine) {
		.primary:hover:not(:disabled)::after {
			opacity: 0.55;
			transform: translateX(120%);
			transition:
				transform 700ms var(--ease-out),
				opacity 700ms ease;
		}
		.ib:hover:not(:disabled) :global(svg) {
			transform: scale(1.08);
		}
	}
	:global(html[data-anim='off']) .primary::after {
		display: none;
	}
	:global(html[data-anim='off']) .ib:hover :global(svg) {
		transform: none;
	}
	.ib:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.sm {
		width: var(--control-h-sm);
		height: var(--control-h-sm);
		border-radius: var(--radius-sm);
	}
	.md {
		width: var(--control-h-md);
		height: var(--control-h-md);
		border-radius: var(--radius-md);
	}
	.lg {
		width: var(--control-h-lg);
		height: var(--control-h-lg);
		border-radius: var(--radius-md);
	}
	@media (max-width: 640px) {
		.sm {
			width: 40px;
			height: 40px;
		}
	}
	.ghost {
		background: transparent;
		color: var(--color-text-muted);
	}
	.ghost:hover:not(:disabled) {
		background: var(--color-hover);
		color: var(--color-text);
	}
	.secondary {
		background: var(--color-surface-2);
		color: var(--color-text);
		border-color: var(--color-border);
	}
	.secondary:hover:not(:disabled) {
		background: var(--color-hover);
		border-color: var(--color-border-strong);
	}
	.primary {
		background: var(--color-accent);
		color: var(--color-text-on-accent);
	}
	.primary:hover:not(:disabled) {
		background: var(--color-accent-hover);
	}
	.danger {
		background: transparent;
		color: var(--color-danger);
	}
	.danger:hover:not(:disabled) {
		background: var(--color-danger-soft);
	}
</style>
