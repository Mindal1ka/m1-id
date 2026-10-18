<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		label?: string;
		hint?: string;
		error?: string;
		required?: boolean;
		/** Власний id контролу; за замовчуванням генерується. */
		id?: string;
		children: Snippet<[{ id: string; describedBy: string | undefined; invalid: boolean }]>;
	}

	let { label, hint, error, required = false, id: idProp, children }: Props = $props();

	const uid = $props.id();
	const id = $derived(idProp ?? `f-${uid}`);
	const hintId = $derived(`${id}-hint`);
	const errorId = $derived(`${id}-err`);
	const invalid = $derived(!!error);
	const describedBy = $derived(
		[error ? errorId : null, hint && !error ? hintId : null].filter(Boolean).join(' ') || undefined
	);
</script>

<div class="field">
	{#if label}
		<label class="label" for={id}>
			{label}{#if required}<span class="req" aria-hidden="true">*</span>{/if}
		</label>
	{/if}
	{@render children({ id, describedBy, invalid })}
	{#if error}
		<p class="msg err" id={errorId} role="alert">{error}</p>
	{:else if hint}
		<p class="msg" id={hintId}>{hint}</p>
	{/if}
</div>

<style>
	.field {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		min-width: 0;
	}
	.label {
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
		color: var(--color-text);
	}
	.req {
		margin-left: 2px;
		color: var(--color-danger);
	}
	.msg {
		font-size: var(--text-xs);
		line-height: var(--leading-normal);
		color: var(--color-text-muted);
	}
	.err {
		color: var(--color-danger);
	}
</style>
