<script lang="ts">
	import type { HTMLInputAttributes } from 'svelte/elements';
	import { Search, X } from '@lucide/svelte';
	import Input from './Input.svelte';
	import { springIn } from '$lib/motion';

	interface Props extends Omit<HTMLInputAttributes, 'size' | 'value' | 'type'> {
		value?: string;
		size?: 'sm' | 'md' | 'lg';
		/** Затримка (мс) перед onsearch; 0 — одразу. */
		debounce?: number;
		onsearch?: (value: string) => void;
		el?: HTMLInputElement | null;
	}

	let {
		value = $bindable(''),
		size = 'md',
		debounce = 0,
		onsearch,
		el = $bindable(null),
		placeholder = 'Пошук',
		...rest
	}: Props = $props();

	let timer: ReturnType<typeof setTimeout> | undefined;

	function emit(v: string) {
		clearTimeout(timer);
		if (debounce > 0) timer = setTimeout(() => onsearch?.(v), debounce);
		else onsearch?.(v);
	}

	function oninput() {
		emit(value);
	}

	function clear() {
		value = '';
		clearTimeout(timer);
		onsearch?.('');
		el?.focus();
	}

	function onkeydown(e: KeyboardEvent) {
		if (e.key === 'Escape' && value) {
			e.preventDefault();
			e.stopPropagation();
			clear();
		}
	}

	$effect(() => () => clearTimeout(timer));
</script>

<Input
	bind:value
	bind:el
	type="search"
	{size}
	{placeholder}
	icon={Search}
	role="searchbox"
	autocomplete="off"
	{oninput}
	{onkeydown}
	{...rest}
>
	{#snippet trailing()}
		{#if value}
			<button
				type="button"
				class="clr"
				aria-label="Очистити пошук"
				onclick={clear}
				transition:springIn={{ start: 0.3, duration: 280, y: 0 }}
			>
				<X size={14} />
			</button>
		{/if}
	{/snippet}
</Input>

<style>
	.clr {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 24px;
		height: 24px;
		margin-right: -4px;
		color: var(--color-text-muted);
		background: var(--color-hover);
		border: 0;
		border-radius: var(--radius-full);
		cursor: pointer;
	}
	.clr:hover {
		color: var(--color-text);
		background: var(--color-pressed);
	}
	@media (max-width: 640px) {
		.clr {
			width: 32px;
			height: 32px;
		}
	}
</style>
