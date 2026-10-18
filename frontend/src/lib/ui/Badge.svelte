<script lang="ts">
	import type { Snippet, Component } from 'svelte';

	interface Props {
		tone?: 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'info';
		variant?: 'soft' | 'solid' | 'outline';
		size?: 'sm' | 'md';
		icon?: Component<any>;
		/** «Дихаюча» крапка зліва (live-статус). */
		pulse?: boolean;
		children?: Snippet;
		class?: string;
	}
	let {
		tone = 'neutral',
		variant = 'soft',
		size = 'md',
		icon: Icon,
		pulse = false,
		children,
		class: klass = ''
	}: Props = $props();
</script>

<span class="badge {tone} {variant} {size} {klass}">
	{#if pulse}<span class="dot breathe" aria-hidden="true"></span>{/if}
	{#if Icon}<Icon size={size === 'sm' ? 11 : 13} />{/if}
	{@render children?.()}
</span>

<style>
	.badge {
		--c: var(--color-text-muted);
		--c-soft: var(--color-surface-2);
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		white-space: nowrap;
		font-weight: var(--weight-medium);
		line-height: 1;
		border: 1px solid transparent;
		border-radius: var(--radius-full);
	}
	.dot {
		width: 6px;
		height: 6px;
		flex-shrink: 0;
		background: currentColor;
		border-radius: 50%;
	}
	.md {
		padding: 4px 10px;
		font-size: var(--text-xs);
	}
	.sm {
		padding: 2px 7px;
		font-size: 11px;
	}
	.accent {
		--c: var(--color-accent-text);
		--c-soft: var(--color-accent-soft);
	}
	.success {
		--c: var(--color-success);
		--c-soft: var(--color-success-soft);
	}
	.warning {
		--c: var(--color-warning);
		--c-soft: var(--color-warning-soft);
	}
	.danger {
		--c: var(--color-danger);
		--c-soft: var(--color-danger-soft);
	}
	.info {
		--c: var(--color-info);
		--c-soft: var(--color-info-soft);
	}
	.soft {
		background: var(--c-soft);
		color: var(--c);
	}
	.outline {
		background: transparent;
		color: var(--c);
		border-color: color-mix(in srgb, var(--c) 40%, transparent);
	}
	.neutral.outline {
		border-color: var(--color-border-strong);
	}
	.solid {
		background: var(--c);
		color: var(--color-text-on-accent);
	}
	.neutral.solid {
		background: var(--color-text-muted);
		color: var(--color-bg);
	}
</style>
