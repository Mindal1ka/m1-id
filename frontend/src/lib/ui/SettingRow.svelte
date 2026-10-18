<script lang="ts">
	import type { Component, Snippet } from 'svelte';
	import { ChevronRight } from '@lucide/svelte';
	import Switch from './Switch.svelte';
	import type { ActionReturn } from 'svelte/action';
	import { pressable } from '$lib/motion';

	interface Props {
		icon?: Component<any>;
		title: string;
		description?: string;
		/** Праворуч: довільний контрол. */
		control?: Snippet;
		href?: string;
		onclick?: (e: MouseEvent) => void;
		disabled?: boolean;
		/** Якщо задано (не undefined) — рядок сам малює Switch і перемикається по кліку. */
		checked?: boolean;
		onchange?: (checked: boolean) => void;
	}

	let {
		icon,
		title,
		description,
		control,
		href,
		onclick,
		disabled = false,
		checked = $bindable(undefined),
		onchange
	}: Props = $props();

	const Icon = $derived(icon);
	const isToggle = $derived(checked !== undefined);
	const interactive = $derived(!isToggle && !disabled && (!!href || !!onclick));

	/** Пружинне натискання рядка; вимикається разом із disabled. */
	function press(node: HTMLElement, on: boolean) {
		let sub: ActionReturn | undefined;
		const set = (v: boolean) => {
			sub?.destroy?.();
			sub = v ? ((pressable(node, { scale: 0.992 }) as ActionReturn | undefined) ?? undefined) : undefined;
		};
		set(on);
		return { update: set, destroy: () => sub?.destroy?.() };
	}

	function rowToggle(e: MouseEvent) {
		if (disabled) return;
		// клік по самому Switch обробляє він сам
		if ((e.target as HTMLElement).closest('[role="switch"]')) return;
		checked = !checked;
		onchange?.(!!checked);
	}
</script>

{#snippet inner()}
	{#if Icon}
		<span class="ico" aria-hidden="true"><Icon size={18} /></span>
	{/if}
	<span class="txt">
		<span class="title">{title}</span>
		{#if description}<span class="desc">{description}</span>{/if}
	</span>
	{#if isToggle}
		<Switch bind:checked={checked as boolean} {disabled} label={title} {onchange} />
	{:else if control}
		<span class="ctl">{@render control()}</span>
	{/if}
	{#if interactive}
		<span class="chev" aria-hidden="true"><ChevronRight size={18} /></span>
	{/if}
{/snippet}

{#if isToggle}
	<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
	<div class="row tap" class:disabled use:press={!disabled} onclick={rowToggle}>
		{@render inner()}
	</div>
{:else if interactive && href}
	<a class="row tap" use:press={true} {href} {onclick}>
		{@render inner()}
	</a>
{:else if interactive}
	<button type="button" class="row tap" use:press={true} {onclick}>
		{@render inner()}
	</button>
{:else}
	<div class="row" class:disabled>
		{@render inner()}
	</div>
{/if}

<style>
	.row {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		width: 100%;
		min-height: 56px;
		padding: var(--space-3) var(--space-4);
		font: inherit;
		text-align: left;
		color: var(--color-text);
		text-decoration: none;
		background: transparent;
		border: 0;
		transition: background var(--dur-fast) ease;
	}
	.tap {
		cursor: pointer;
	}
	.tap:hover:not(.disabled) {
		background: var(--color-hover);
	}
	.tap:active:not(.disabled) {
		background: var(--color-pressed);
	}
	.row:focus-visible {
		outline: 2px solid var(--color-accent);
		outline-offset: -2px;
		border-radius: var(--radius-md);
	}
	.disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
	.ico {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		width: 32px;
		height: 32px;
		color: var(--color-accent-text);
		background: var(--color-accent-soft);
		border-radius: var(--radius-sm);
	}
	.txt {
		display: flex;
		flex: 1;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}
	.title {
		font-size: var(--text-base);
		font-weight: var(--weight-medium);
	}
	.desc {
		font-size: var(--text-sm);
		line-height: var(--leading-normal);
		color: var(--color-text-muted);
	}
	.ctl {
		display: inline-flex;
		align-items: center;
		flex-shrink: 0;
	}
	.chev {
		display: inline-flex;
		flex-shrink: 0;
		color: var(--color-text-subtle);
		transition:
			transform 360ms var(--ease-spring),
			color var(--dur-fast) ease;
	}
	@media (hover: hover) and (pointer: fine) {
		.tap:hover .chev {
			transform: translateX(3px);
			color: var(--color-text-muted);
		}
	}
	:global(html[data-anim='off']) .tap:hover .chev {
		transform: none;
	}
</style>
