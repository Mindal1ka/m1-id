<script lang="ts">
	import { TriangleAlert } from '@lucide/svelte';
	import { ease, motionOK, pressable } from '$lib/motion';
	import Dialog from './Dialog.svelte';
	import { confirmState, resolveConfirm, type ConfirmRequest } from './confirm.svelte';

	const cur = $derived(confirmState.current);

	// Знімок запиту: вміст не зникає, поки діалог програє анімацію виходу.
	let shown = $state<ConfirmRequest | null>(null);
	$effect(() => {
		if (cur) shown = cur;
	});

	/** Фокус після того, як focusTrap та portal відпрацюють (2 кадри). */
	function focusSoon(node: HTMLElement): { destroy(): void } {
		let r2 = 0;
		const r1 = requestAnimationFrame(() => {
			r2 = requestAnimationFrame(() => node.focus({ preventScroll: true }));
		});
		return {
			destroy(): void {
				cancelAnimationFrame(r1);
				cancelAnimationFrame(r2);
			}
		};
	}

	/** Іконка небезпеки "вистрибує": scale + легкий поворот пружиною. */
	function popIn(node: HTMLElement): void {
		if (!motionOK()) return;
		node.animate(
			[
				{ transform: 'scale(0.2) rotate(-18deg)', opacity: 0 },
				{ transform: 'scale(1) rotate(0deg)', opacity: 1 }
			],
			{ duration: 620, delay: 140, easing: ease('spring'), fill: 'backwards' }
		);
	}

	/** Одноразовий "пульс уваги" на кнопці підтвердження небезпечної дії. */
	function attention(node: HTMLElement): { destroy(): void } | void {
		if (!motionOK()) return;
		const id = setTimeout(() => {
			node.animate(
				[
					{ transform: 'scale(1)' },
					{ transform: 'scale(1.08)', offset: 0.35 },
					{ transform: 'scale(0.98)', offset: 0.65 },
					{ transform: 'scale(1)' }
				],
				{ duration: 640, easing: ease('out') }
			);
		}, 520);
		return { destroy: () => clearTimeout(id) };
	}

	function onKeydown(e: KeyboardEvent): void {
		if (!cur || cur.danger || e.key !== 'Enter' || e.defaultPrevented) return;
		// на кнопках Enter спрацьовує нативно
		if ((e.target as HTMLElement | null)?.closest('button, a, textarea')) return;
		e.preventDefault();
		resolveConfirm(true);
	}
</script>

<svelte:window onkeydown={onKeydown} />

<Dialog open={cur !== null} size="sm" title={shown?.title ?? ''} onclose={() => resolveConfirm(false)}>
	{#if shown?.danger}
		<span class="warn" use:popIn aria-hidden="true"><TriangleAlert size={26} /></span>
	{/if}
	{#if shown?.message}
		<p class="msg">{shown.message}</p>
	{/if}
	{#snippet footer()}
		{#if shown}
			{#if shown.danger}
				<button type="button" class="btn" use:focusSoon use:pressable onclick={() => resolveConfirm(false)}>
					{shown.cancelText}
				</button>
				<button type="button" class="btn danger" use:attention use:pressable onclick={() => resolveConfirm(true)}>
					{shown.confirmText}
				</button>
			{:else}
				<button type="button" class="btn" use:pressable onclick={() => resolveConfirm(false)}>
					{shown.cancelText}
				</button>
				<button type="button" class="btn primary" use:focusSoon use:pressable onclick={() => resolveConfirm(true)}>
					{shown.confirmText}
				</button>
			{/if}
		{/if}
	{/snippet}
</Dialog>

<style>
	.warn {
		display: grid;
		place-items: center;
		width: 48px;
		height: 48px;
		margin-bottom: var(--space-3);
		color: var(--color-danger);
		background: var(--color-danger-soft);
		border-radius: var(--radius-full);
	}

	.msg {
		font-size: var(--text-md);
		line-height: var(--leading-normal);
		color: var(--color-text-muted);
		overflow-wrap: anywhere;
		white-space: pre-line;
	}

	.btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-height: var(--control-h-md);
		padding: 0 var(--space-4);
		font: inherit;
		font-size: var(--text-md);
		font-weight: var(--weight-semibold);
		color: var(--color-text);
		background: var(--color-surface-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		cursor: pointer;
		transition:
			background var(--dur-fast) var(--ease-out),
			border-color var(--dur-fast) var(--ease-out);
	}

	.btn:hover {
		background: var(--color-hover);
		border-color: var(--color-border-strong);
	}

	.btn.primary {
		color: var(--color-text-on-accent);
		background: var(--color-accent);
		border-color: transparent;
	}

	.btn.primary:hover {
		background: var(--color-accent-hover);
	}

	.btn.danger {
		color: var(--color-text-on-accent);
		background: var(--color-danger);
		border-color: transparent;
	}

	.btn.danger:hover {
		background: color-mix(in srgb, var(--color-danger) 85%, #000);
	}
</style>
