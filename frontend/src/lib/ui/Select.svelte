<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLSelectAttributes } from 'svelte/elements';
	import { ChevronDown } from '@lucide/svelte';

	interface Option {
		value: string | number;
		label: string;
		disabled?: boolean;
	}

	interface Props extends Omit<HTMLSelectAttributes, 'size' | 'value'> {
		value?: string | number | null;
		options?: Option[];
		size?: 'sm' | 'md' | 'lg';
		invalid?: boolean;
		el?: HTMLSelectElement | null;
		children?: Snippet;
	}

	let {
		value = $bindable(''),
		options,
		size = 'md',
		invalid = false,
		el = $bindable(null),
		children,
		class: klass = '',
		...rest
	}: Props = $props();
</script>

<div class="wrap s-{size} {klass}" class:invalid class:disabled={rest.disabled}>
	<select
		bind:this={el}
		bind:value
		class="sel"
		aria-invalid={invalid || undefined}
		{...rest}
	>
		{#if options}
			{#each options as o (o.value)}
				<option value={o.value} disabled={o.disabled}>{o.label}</option>
			{/each}
		{:else}
			{@render children?.()}
		{/if}
	</select>
	<span class="chev" aria-hidden="true"><ChevronDown size={16} /></span>
</div>

<style>
	.wrap {
		position: relative;
		width: 100%;
		min-width: 0;
	}
	.s-sm {
		--h: var(--control-h-sm);
		font-size: var(--text-sm);
	}
	.s-md {
		--h: var(--control-h-md);
		font-size: var(--text-md);
	}
	.s-lg {
		--h: var(--control-h-lg);
		font-size: var(--text-base);
	}
	.sel {
		width: 100%;
		height: var(--h);
		padding: 0 calc(var(--space-3) + 24px) 0 var(--space-3);
		font: inherit;
		color: var(--color-text);
		background: var(--color-surface-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		outline: 3px solid transparent;
		appearance: none;
		-webkit-appearance: none;
		cursor: pointer;
		transition:
			border-color var(--dur-fast) ease,
			outline-color var(--dur-fast) ease;
	}
	.sel:hover:not(:disabled) {
		border-color: var(--color-border-strong);
	}
	.sel:focus {
		border-color: var(--color-accent);
		outline-color: color-mix(in srgb, var(--color-accent) 25%, transparent);
	}
	.invalid .sel {
		border-color: var(--color-danger);
	}
	.invalid .sel:focus {
		outline-color: color-mix(in srgb, var(--color-danger) 25%, transparent);
	}
	.sel:disabled {
		opacity: 0.55;
		cursor: not-allowed;
	}
	.chev {
		position: absolute;
		top: 50%;
		right: var(--space-3);
		display: inline-flex;
		color: var(--color-text-muted);
		transform: translateY(-50%);
		pointer-events: none;
	}
</style>
