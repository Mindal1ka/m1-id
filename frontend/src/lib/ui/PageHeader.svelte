<script lang="ts">
	import type { Snippet, Component } from 'svelte';

	interface Props {
		title: string;
		subtitle?: string;
		icon?: Component<any>;
		actions?: Snippet;
		children?: Snippet;
	}
	let { title, subtitle, icon: Icon, actions, children }: Props = $props();
</script>

<header class="ph">
	<div class="row">
		<div class="main">
			{#if Icon}<span class="ico"><Icon size={22} /></span>{/if}
			<div class="titles">
				<h1>{title}</h1>
				{#if subtitle}<p>{subtitle}</p>{/if}
			</div>
		</div>
		{#if actions}<div class="actions">{@render actions()}</div>{/if}
	</div>
	{#if children}<div class="below">{@render children()}</div>{/if}
</header>

<style>
	.ph {
		margin-bottom: var(--space-6);
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-3) var(--space-4);
	}
	.main {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		min-width: 0;
		flex: 1 1 260px;
	}
	.ico {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		width: 40px;
		height: 40px;
		color: var(--color-accent-text);
		background: var(--color-accent-soft);
		border-radius: var(--radius-md);
	}
	.titles {
		min-width: 0;
	}
	h1 {
		font-size: var(--text-2xl);
		font-weight: var(--weight-semibold);
	}
	p {
		margin-top: var(--space-1);
		font-size: var(--text-md);
		color: var(--color-text-muted);
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: flex-end;
		gap: var(--space-2);
	}
	.below {
		margin-top: var(--space-4);
	}
	@media (max-width: 640px) {
		.ph {
			margin-bottom: var(--space-4);
		}
		h1 {
			font-size: var(--text-xl);
		}
		.actions {
			justify-content: flex-start;
			width: 100%;
		}
	}
</style>
