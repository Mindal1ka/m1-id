<script lang="ts">
	import type { HTMLTextareaAttributes } from 'svelte/elements';
	import { shake } from '$lib/motion';

	interface Props extends Omit<HTMLTextareaAttributes, 'value'> {
		value?: string;
		rows?: number;
		/** Росте разом із вмістом до maxRows. */
		autoresize?: boolean;
		maxRows?: number;
		showCount?: boolean;
		invalid?: boolean;
		el?: HTMLTextAreaElement | null;
	}

	let {
		value = $bindable(''),
		rows = 3,
		autoresize = false,
		maxRows = 10,
		showCount = false,
		invalid = false,
		el = $bindable(null),
		maxlength,
		class: klass = '',
		...rest
	}: Props = $props();

	function resize() {
		if (!autoresize || !el) return;
		el.style.height = 'auto';
		const cs = getComputedStyle(el);
		const line = parseFloat(cs.lineHeight) || 20;
		const pad = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
		const max = line * maxRows + pad;
		el.style.height = `${Math.min(el.scrollHeight, max)}px`;
		el.style.overflowY = el.scrollHeight > max ? 'auto' : 'hidden';
	}

	let fieldEl: HTMLDivElement | undefined = $state();
	let prevInvalid: boolean | undefined;
	// помилка з'явилась (false → true) — поле «трясеться»
	$effect(() => {
		const inv = invalid;
		if (prevInvalid === false && inv && fieldEl) shake(fieldEl);
		prevInvalid = inv;
	});

	$effect(() => {
		void value;
		void autoresize;
		void maxRows;
		resize();
	});
</script>

<div class="box {klass}">
	<div bind:this={fieldEl} class="field" class:invalid>
	<textarea
		bind:this={el}
		bind:value
		{rows}
		{maxlength}
		class="ta"
		class:invalid
		class:auto={autoresize}
		aria-invalid={invalid || undefined}
		{...rest}
	></textarea>
	</div>
	{#if showCount && maxlength}
		<span class="count" aria-live="polite">{(value ?? '').length} / {maxlength}</span>
	{/if}
</div>

<style>
	.box {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		width: 100%;
	}
	.field {
		--ring: color-mix(in srgb, var(--color-accent) 25%, transparent);
		position: relative;
		display: flex;
		width: 100%;
	}
	.field.invalid {
		--ring: color-mix(in srgb, var(--color-danger) 25%, transparent);
	}
	/* кільце фокуса «виростає» з рамки (transform + opacity) */
	.field::after {
		content: '';
		position: absolute;
		inset: -4px;
		border: 3px solid var(--ring);
		border-radius: calc(var(--radius-md) + 3px);
		opacity: 0;
		transform: scale(0.985);
		pointer-events: none;
		transition:
			opacity 200ms var(--ease-out),
			transform 420ms var(--ease-spring);
	}
	.field:focus-within::after {
		opacity: 1;
		transform: scale(1);
	}
	:global(html[data-perf='lite']) .field::after {
		transition: opacity 160ms var(--ease-out);
	}
	:global(html[data-anim='off']) .field::after {
		transition: none;
	}
	.ta {
		width: 100%;
		padding: var(--space-3);
		font: inherit;
		font-size: var(--text-md);
		line-height: var(--leading-normal);
		color: var(--color-text);
		background: var(--color-surface-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		resize: vertical;
		transition: border-color var(--dur-fast) ease;
	}
	.ta.auto {
		resize: none;
	}
	.ta::placeholder {
		color: var(--color-text-subtle);
	}
	.ta:hover:not(:disabled) {
		border-color: var(--color-border-strong);
	}
	.ta:focus {
		border-color: var(--color-accent);
		outline: 0;
	}
	.ta.invalid {
		border-color: var(--color-danger);
	}
	.ta:disabled {
		opacity: 0.55;
		cursor: not-allowed;
	}
	.count {
		align-self: flex-end;
		font-size: var(--text-xs);
		color: var(--color-text-subtle);
	}
</style>
