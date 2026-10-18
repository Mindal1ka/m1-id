<script lang="ts">
	import type { Snippet, Component } from 'svelte';
	import { Inbox } from '@lucide/svelte';
	import { ease, motionOK } from '$lib/motion';

	interface Props {
		icon?: Component<any>;
		title: string;
		description?: string;
		action?: Snippet;
	}
	let { icon: Icon = Inbox, title, description, action }: Props = $props();

	/** Кружечок пружинно з'являється, потім іконка м'яко «пливе». */
	function enter(node: HTMLElement) {
		if (!motionOK()) return;
		node.animate(
			[
				{ opacity: 0, transform: 'scale(0.4) rotate(-12deg)' },
				{ opacity: 1, transform: 'none' }
			],
			{ duration: 620, easing: ease('spring'), fill: 'backwards' }
		);
	}
</script>

<div class="empty">
	<span class="circle" use:enter><span class="ico"><Icon size={24} /></span></span>
	<h3>{title}</h3>
	{#if description}<p>{description}</p>{/if}
	{#if action}<div class="action">{@render action()}</div>{/if}
</div>

<style>
	.empty {
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
		color: var(--color-text-muted);
		background: var(--color-surface-2);
		border-radius: 50%;
	}
	.ico {
		display: inline-flex;
		animation: es-float 3.6s ease-in-out 0.8s infinite;
	}
	@keyframes es-float {
		0%,
		100% {
			transform: translateY(0);
		}
		50% {
			transform: translateY(-3px);
		}
	}
	:global(html[data-anim='off']) .ico {
		animation: none;
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
