<script lang="ts">
	import type { Snippet, Component } from 'svelte';
	import { AlertTriangle, RotateCw } from '@lucide/svelte';
	import Button from './Button.svelte';
	import { ease, motionOK } from '$lib/motion';

	interface Props {
		icon?: Component<any>;
		title?: string;
		description?: string;
		action?: Snippet;
		onretry?: () => void;
	}
	let {
		icon: Icon = AlertTriangle,
		title = 'Щось пішло не так',
		description,
		action,
		onretry
	}: Props = $props();

	/** Кружечок вистрибує, а після цього разово «трясеться». */
	function enter(node: HTMLElement) {
		if (!motionOK()) return;
		node.animate(
			[
				{ opacity: 0, transform: 'scale(0.4)' },
				{ opacity: 1, transform: 'none' }
			],
			{ duration: 520, easing: ease('spring'), fill: 'backwards' }
		);
		node.animate(
			[
				{ transform: 'translateX(0) rotate(0)' },
				{ transform: 'translateX(-6px) rotate(-6deg)' },
				{ transform: 'translateX(5px) rotate(5deg)' },
				{ transform: 'translateX(-3px) rotate(-3deg)' },
				{ transform: 'translateX(2px) rotate(1deg)' },
				{ transform: 'translateX(0) rotate(0)' }
			],
			{ duration: 480, delay: 420, easing: 'cubic-bezier(0.22, 1, 0.36, 1)' }
		);
	}
</script>

<div class="error" role="alert">
	<span class="circle" use:enter><Icon size={24} /></span>
	<h3>{title}</h3>
	{#if description}<p>{description}</p>{/if}
	{#if action || onretry}
		<div class="action">
			{#if action}
				{@render action()}
			{:else if onretry}
				<Button variant="secondary" icon={RotateCw} onclick={onretry}>Спробувати ще</Button>
			{/if}
		</div>
	{/if}
</div>

<style>
	.error {
		display: flex;
		flex-direction: column;
		align-items: center;
		text-align: center;
		padding: var(--space-12) var(--space-4);
	}
	.circle {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 56px;
		height: 56px;
		color: var(--color-danger);
		background: var(--color-danger-soft);
		border-radius: 50%;
	}
	h3 {
		margin-top: var(--space-4);
		font-size: var(--text-lg);
	}
	p {
		max-width: 360px;
		margin-top: var(--space-2);
		font-size: var(--text-md);
		color: var(--color-text-muted);
	}
	.action {
		margin-top: var(--space-5);
	}
</style>
