<script lang="ts">
	import type { Component, Snippet } from 'svelte';
	import { Dialog } from '$lib/ui';

	/**
	 * AppModal — тонка обгортка над `Dialog` з UI-кіту (зберігає старий API).
	 *
	 *  - width: бажана ширина в px → розмір Dialog (≤420 sm, ≤600 md, інакше lg);
	 *  - icon / tone: лишені для сумісності з викликами; Dialog малює
	 *    нейтральну шапку, тож вони візуально не впливають;
	 *  - snippet header: повністю замінює шапку;
	 *  - snippet footer: нижня панель з кнопками (можна не передавати);
	 *  - children: вміст (скролиться сам).
	 */
	let {
		open = $bindable(false),
		title = '',
		// eslint-disable-next-line @typescript-eslint/no-unused-vars
		icon = null,
		onclose,
		width = 560,
		// eslint-disable-next-line @typescript-eslint/no-unused-vars
		tone = 'default',
		children,
		header,
		footer
	}: {
		open?: boolean;
		title?: string;
		icon?: Component | null;
		onclose: () => void;
		width?: number;
		tone?: 'default' | 'accent' | 'cyan' | 'success' | 'danger';
		children?: Snippet;
		header?: Snippet;
		footer?: Snippet;
	} = $props();

	const size = $derived(width <= 420 ? 'sm' : width <= 600 ? 'md' : 'lg');
</script>

<Dialog bind:open title={header ? '' : title} {size} {onclose} {header} {footer}>
	<div class="content">
		{@render children?.()}
	</div>
</Dialog>

<style>
	.content {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
</style>
