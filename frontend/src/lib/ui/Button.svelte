<script lang="ts">
	import type { Snippet, Component } from 'svelte';
	import type { HTMLButtonAttributes } from 'svelte/elements';
	import Spinner from './Spinner.svelte';
	import { pressable, blurFade } from '$lib/motion';

	interface Props extends Omit<HTMLButtonAttributes, 'children'> {
		variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'soft';
		size?: 'sm' | 'md' | 'lg';
		icon?: Component<any>;
		iconRight?: Component<any>;
		loading?: boolean;
		block?: boolean;
		href?: string;
		target?: string;
		rel?: string;
		children?: Snippet;
	}

	let {
		variant = 'primary',
		size = 'md',
		icon: Icon,
		iconRight: IconRight,
		loading = false,
		block = false,
		href,
		type = 'button',
		disabled = false,
		children,
		class: klass = '',
		...rest
	}: Props = $props();

	const iconSize = $derived(size === 'sm' ? 14 : size === 'lg' ? 20 : 16);
	const isDisabled = $derived(disabled || loading);
</script>

{#snippet content()}
	<!-- вміст лишається в потоці (ширина кнопки не стрибає), спінер накладається поверх -->
	<span class="inner">
		{#if Icon}<Icon size={iconSize} />{/if}
		{#if children}<span class="label">{@render children()}</span>{/if}
		{#if IconRight}<span class="ir"><IconRight size={iconSize} /></span>{/if}
	</span>
	{#if loading}
		<span class="spin" transition:blurFade={{ duration: 200, amount: 3 }}>
			<Spinner size={iconSize} />
		</span>
	{/if}
{/snippet}

{#if href && !isDisabled}
	<a
		class="btn {variant} {size} {klass}"
		class:block
		use:pressable={{ scale: 0.97 }}
		{href}
		{...rest as any}
	>
		{@render content()}
	</a>
{:else}
	<button
		class="btn {variant} {size} {klass}"
		class:block
		class:loading
		use:pressable={{ scale: 0.97 }}
		{type}
		disabled={isDisabled}
		aria-busy={loading || undefined}
		{...rest}
	>
		{@render content()}
	</button>
{/if}

<style>
	.btn {
		position: relative;
		overflow: hidden;
		isolation: isolate;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		font: inherit;
		font-weight: var(--weight-semibold);
		line-height: 1;
		white-space: nowrap;
		text-decoration: none;
		cursor: pointer;
		user-select: none;
		border: 1px solid transparent;
		transition:
			background var(--dur-fast) var(--ease-out),
			border-color var(--dur-fast) var(--ease-out),
			opacity var(--dur-fast) ease;
	}
	.inner {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-2);
		transition:
			opacity 180ms var(--ease-out),
			transform 320ms var(--ease-spring);
	}
	.ir {
		display: inline-flex;
		transition: transform 320ms var(--ease-spring);
	}
	/* loading: підпис плавно розчиняється, спінер з'являється по центру */
	.loading .inner {
		opacity: 0;
		transform: scale(0.92);
	}
	.spin {
		position: absolute;
		inset: 0;
		z-index: 1;
		display: flex;
		align-items: center;
		justify-content: center;
	}
	/* блиск: світла смуга пробігає по основній кнопці при hover (лише миша) */
	.primary::after {
		content: '';
		position: absolute;
		inset: 0;
		z-index: 0;
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
		.btn:hover:not(:disabled) .ir {
			transform: translateX(2px);
		}
	}
	/* блиск — важкий ефект: вимкнено на lite та на сенсорних пристроях */
	:global(html[data-perf='lite']) .primary::after,
	:global(html[data-anim='off']) .primary::after {
		display: none;
	}
	@media (hover: none), (pointer: coarse) {
		.primary::after {
			display: none;
		}
	}
	:global(html[data-anim='off']) .btn:hover .ir {
		transform: none;
	}
	.btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.block {
		display: flex;
		width: 100%;
	}
	.sm {
		min-height: var(--control-h-sm);
		padding: 0 var(--space-3);
		font-size: var(--text-sm);
		border-radius: var(--radius-sm);
	}
	.md {
		min-height: var(--control-h-md);
		padding: 0 var(--space-4);
		font-size: var(--text-md);
		border-radius: var(--radius-md);
	}
	.lg {
		min-height: var(--control-h-lg);
		padding: 0 var(--space-6);
		font-size: var(--text-base);
		border-radius: var(--radius-md);
	}
	@media (max-width: 640px) {
		.sm {
			min-height: 40px;
		}
	}

	.primary {
		background: var(--color-accent);
		color: var(--color-text-on-accent);
	}
	.primary:hover:not(:disabled) {
		background: var(--color-accent-hover);
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
	.ghost {
		background: transparent;
		color: var(--color-text-muted);
	}
	.ghost:hover:not(:disabled) {
		background: var(--color-hover);
		color: var(--color-text);
	}
	.ghost:active:not(:disabled) {
		background: var(--color-pressed);
	}
	.danger {
		background: var(--color-danger);
		color: var(--color-text-on-accent);
	}
	.danger:hover:not(:disabled) {
		background: color-mix(in srgb, var(--color-danger) 88%, var(--color-text));
	}
	.soft {
		background: var(--color-accent-soft);
		color: var(--color-accent-text);
	}
	.soft:hover:not(:disabled) {
		background: color-mix(in srgb, var(--color-accent) 24%, transparent);
	}
</style>
