<script lang="ts">
	/** Внутрішній стенд для візуальної перевірки мобільної нижньої панелі (без входу). */
	import { CalendarDays, Ellipsis, House, NotebookPen, ShoppingBag, Utensils } from '@lucide/svelte';
	import AppBottomNav from '$lib/components/app/AppBottomNav.svelte';
	import type { Tab } from '$lib/app/helpers';

	const tabs = [
		{ key: 'home' as Tab, icon: House, label: 'Головна' },
		{ key: 'schedule' as Tab, icon: CalendarDays, label: 'Розклад' },
		{ key: 'homework' as Tab, icon: NotebookPen, label: 'Домашка' },
		{ key: 'shop' as Tab, icon: ShoppingBag, label: 'Магазин' },
		{ key: 'nutrition' as Tab, icon: Utensils, label: 'Харчування' }
	];
	const mainTabs: ReadonlySet<Tab> = new Set(['home', 'schedule', 'homework', 'shop'] as Tab[]);
	let tab = $state<Tab>('home');
	let menuOpen = $state(false);
	let hidden = $state(false);
	void Ellipsis;
</script>

<svelte:head><meta name="robots" content="noindex" /></svelte:head>

<div class="stage">
	<p>Активна: <b>{tab}</b></p>
	<button type="button" onclick={() => (hidden = !hidden)}>hidden = {hidden}</button>
	<input placeholder="фокус → панель ховається" />
	{#each Array(30) as _, i (i)}<div class="row">Рядок {i + 1}</div>{/each}
</div>

<AppBottomNav
	{tabs}
	{mainTabs}
	{tab}
	isOther={!mainTabs.has(tab)}
	bind:menuOpen
	{hidden}
	onopen={(t) => (tab = t)}
	onother={() => (tab = 'nutrition')}
/>

<style>
	.stage {
		padding: var(--space-4);
		padding-bottom: 120px;
		display: grid;
		gap: var(--space-2);
	}
	.row {
		padding: var(--space-3);
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
	}
</style>
