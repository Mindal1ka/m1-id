<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { ActionReturn } from 'svelte/action';
	import { pressable, spotlight as spotlightAction, tilt as tiltAction } from '$lib/motion';

	interface Props {
		padding?: 'none' | 'sm' | 'md' | 'lg';
		interactive?: boolean;
		header?: Snippet;
		title?: string;
		subtitle?: string;
		actions?: Snippet;
		children?: Snippet;
		onclick?: (e: MouseEvent) => void;
		href?: string;
		/** Світло й підсвічена рамка за курсором. */
		spotlight?: boolean;
		/** 3D-нахил за курсором (помірно — для «геройських» карток). */
		tilt?: boolean;
		class?: string;
		[key: string]: unknown;
	}

	let {
		padding = 'md',
		interactive = false,
		header,
		title,
		subtitle,
		actions,
		children,
		onclick,
		href,
		spotlight = false,
		tilt = false,
		class: klass = '',
		...rest
	}: Props = $props();

	const tag = $derived(href ? 'a' : onclick ? 'button' : 'section');
	const isInteractive = $derived(interactive || !!href || !!onclick);
	type Fx = { press: boolean; spot: boolean; tilt: boolean };

	/** Збирає потрібні motion-actions залежно від пропсів (перебудовується в update). */
	function fx(node: HTMLElement, o: Fx) {
		let subs: ActionReturn[] = [];
		const setup = (f: Fx) => {
			const add = (r: unknown) => {
				if (r) subs.push(r as ActionReturn);
			};
			if (f.press) add(pressable(node, { scale: 0.985 }));
			if (f.spot) add(spotlightAction(node));
			if (f.tilt) add(tiltAction(node, { max: 4 }));
		};
		const teardown = () => {
			subs.forEach((s) => s.destroy?.());
			subs = [];
		};
		setup(o);
		return {
			update(n: Fx) {
				teardown();
				setup(n);
			},
			destroy: teardown
		};
	}

	const fxOpts = $derived<Fx>({ press: isInteractive, spot: spotlight, tilt });
	const hasHeader = $derived(!!(header || title || subtitle || actions));
</script>

<svelte:element
	this={tag}
	class="card p-{padding} {klass}"
	class:interactive={isInteractive}
	class:lift={isInteractive && !tilt}
	use:fx={fxOpts}
	href={tag === 'a' ? href : undefined}
	type={tag === 'button' ? 'button' : undefined}
	onclick={tag === 'section' ? undefined : onclick}
	{...rest}
>
	{#if hasHeader}
		<div class="head">
			{#if header}
				{@render header()}
			{:else}
				<div class="titles">
					{#if title}<h2>{title}</h2>{/if}
					{#if subtitle}<p>{subtitle}</p>{/if}
				</div>
				{#if actions}<div class="actions">{@render actions()}</div>{/if}
			{/if}
		</div>
	{/if}
	{@render children?.()}
</svelte:element>

<style>
	.card {
		display: block;
		width: 100%;
		min-width: 0;
		font: inherit;
		text-align: left;
		color: var(--color-text);
		text-decoration: none;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		box-shadow: var(--shadow-card);
	}
	.p-none {
		padding: 0;
	}
	.p-sm {
		padding: var(--space-3);
	}
	.p-md {
		padding: var(--space-5);
	}
	.p-lg {
		padding: var(--space-8);
	}
	@media (max-width: 640px) {
		.p-md {
			padding: var(--space-4);
		}
		.p-lg {
			padding: var(--space-5);
		}
	}
	.interactive {
		cursor: pointer;
		transition:
			background var(--dur-fast) var(--ease-out),
			border-color var(--dur-fast) var(--ease-out),
			box-shadow var(--dur-base) ease,
			transform 420ms var(--ease-spring);
	}
	.interactive:hover {
		background: var(--color-surface-2);
		border-color: var(--color-border-strong);
	}
	/* lite / сенсорні: без анімації box-shadow (перемальовування) */
	:global(html[data-perf='lite']) .interactive {
		transition:
			background var(--dur-fast) var(--ease-out),
			border-color var(--dur-fast) var(--ease-out),
			transform 420ms var(--ease-spring);
	}
	@media (hover: none), (pointer: coarse) {
		.interactive {
			transition:
				background var(--dur-fast) var(--ease-out),
				border-color var(--dur-fast) var(--ease-out),
				transform 420ms var(--ease-spring);
		}
	}
	.head {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-3);
		margin-bottom: var(--space-4);
	}
	.titles {
		min-width: 0;
	}
	h2 {
		font-size: var(--text-lg);
		font-weight: var(--weight-semibold);
	}
	p {
		margin-top: var(--space-1);
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}
	.actions {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		flex-shrink: 0;
	}
</style>
