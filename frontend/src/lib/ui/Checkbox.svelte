<script lang="ts">
	import type { HTMLInputAttributes } from 'svelte/elements';
	import { pop } from '$lib/motion';

	interface Props extends Omit<HTMLInputAttributes, 'checked' | 'type' | 'children'> {
		checked?: boolean;
		indeterminate?: boolean;
		label?: string;
		description?: string;
	}

	let {
		checked = $bindable(false),
		indeterminate = $bindable(false),
		label,
		description,
		disabled = false,
		class: klass = '',
		...rest
	}: Props = $props();

	let boxEl: HTMLSpanElement | undefined = $state();
	let prevOn: boolean | undefined;
	// «Пульс» рамки при зміні стану (не на першому рендері)
	$effect(() => {
		const on = checked || indeterminate;
		if (prevOn !== undefined && prevOn !== on && boxEl) pop(boxEl, 1.14);
		prevOn = on;
	});
</script>

<label class="cb {klass}" class:disabled>
	<span class="box-wrap">
		<input
			type="checkbox"
			bind:checked
			bind:indeterminate
			{disabled}
			class="native"
			{...rest}
		/>
		<span class="box" bind:this={boxEl} aria-hidden="true">
			<svg class="mark" viewBox="0 0 20 20" width="14" height="14" fill="none">
				<path class="chk" d="M4.5 10.5 8.5 14.5 15.5 6" pathLength="1" />
				<path class="dash" d="M5 10h10" pathLength="1" />
			</svg>
		</span>
	</span>
	{#if label || description}
		<span class="txt">
			{#if label}<span class="lbl">{label}</span>{/if}
			{#if description}<span class="desc">{description}</span>{/if}
		</span>
	{/if}
</label>

<style>
	.cb {
		display: inline-flex;
		align-items: flex-start;
		gap: var(--space-3);
		min-height: 24px;
		cursor: pointer;
	}
	.cb.disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.box-wrap {
		position: relative;
		display: inline-flex;
		flex-shrink: 0;
		margin-top: 1px;
	}
	.native {
		position: absolute;
		inset: -8px;
		width: calc(100% + 16px);
		height: calc(100% + 16px);
		margin: 0;
		opacity: 0;
		cursor: inherit;
	}
	.box {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 20px;
		height: 20px;
		color: var(--color-text-on-accent);
		background: var(--color-surface-2);
		border: 1px solid var(--color-border-strong);
		border-radius: var(--radius-xs);
		transition:
			background 200ms ease,
			border-color 200ms ease;
	}
	/* темна тема: рамка порожнього чекбокса контрастніша */
	:global(html[data-scheme='dark']) .native:not(:checked):not(:indeterminate) + .box {
		border-color: color-mix(in srgb, var(--text) 45%, transparent);
	}
	.mark {
		overflow: visible;
	}
	.mark path {
		stroke: currentColor;
		stroke-width: 2.6;
		stroke-linecap: round;
		stroke-linejoin: round;
		stroke-dasharray: 1;
		stroke-dashoffset: 1;
		opacity: 0;
		transition:
			stroke-dashoffset 260ms var(--ease-out),
			opacity 60ms linear 60ms;
	}
	/* галочка «промальовується» */
	.native:checked:not(:indeterminate) + .box .chk {
		stroke-dashoffset: 0;
		opacity: 1;
		transition-delay: 60ms, 0ms;
	}
	.native:indeterminate + .box .dash {
		stroke-dashoffset: 0;
		opacity: 1;
		transition-delay: 0ms;
	}
	:global(html[data-anim='off']) .mark path {
		transition: none;
	}
	.native:checked + .box,
	.native:indeterminate + .box {
		background: var(--color-accent);
		border-color: var(--color-accent);
	}
	.native:focus-visible + .box {
		outline: 3px solid color-mix(in srgb, var(--color-accent) 35%, transparent);
		outline-offset: 1px;
	}
	.txt {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}
	.lbl {
		font-size: var(--text-md);
		color: var(--color-text);
		line-height: 22px;
	}
	.desc {
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}
</style>
