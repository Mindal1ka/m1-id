<script lang="ts">
	import type { Component, Snippet } from 'svelte';
	import type { HTMLInputAttributes } from 'svelte/elements';
	import { Eye, EyeOff } from '@lucide/svelte';
	import { shake } from '$lib/motion';

	interface Props extends Omit<HTMLInputAttributes, 'size' | 'value'> {
		value?: string | number | null;
		size?: 'sm' | 'md' | 'lg';
		invalid?: boolean;
		icon?: Component<any>;
		trailing?: Snippet;
		el?: HTMLInputElement | null;
	}

	let {
		value = $bindable(''),
		type = 'text',
		size = 'md',
		invalid = false,
		icon,
		trailing,
		el = $bindable(null),
		class: klass = '',
		...rest
	}: Props = $props();

	let shown = $state(false);
	const isPassword = $derived(type === 'password');
	const realType = $derived(isPassword && shown ? 'text' : type);
	const Icon = $derived(icon);

	let wrapEl: HTMLDivElement | undefined = $state();
	let prevInvalid: boolean | undefined;
	// помилка з'явилась (false → true) — поле «трясеться»
	$effect(() => {
		const inv = invalid;
		if (prevInvalid === false && inv && wrapEl) shake(wrapEl);
		prevInvalid = inv;
	});
</script>

<div bind:this={wrapEl} class="wrap s-{size} {klass}" class:invalid class:disabled={rest.disabled}>
	{#if Icon}
		<span class="lead" aria-hidden="true"><Icon size={16} /></span>
	{/if}
	<input
		bind:this={el}
		bind:value
		type={realType}
		class="inp"
		aria-invalid={invalid || undefined}
		{...rest}
	/>
	{#if isPassword}
		<button
			type="button"
			class="tr-btn"
			aria-label={shown ? 'Сховати пароль' : 'Показати пароль'}
			aria-pressed={shown}
			disabled={rest.disabled}
			onclick={() => (shown = !shown)}
		>
			<span class="eye" class:shown>
				<span class="e e-open"><Eye size={16} /></span>
				<span class="e e-off"><EyeOff size={16} /></span>
			</span>
		</button>
	{/if}
	{#if trailing}
		<span class="trail">{@render trailing()}</span>
	{/if}
</div>

<style>
	.wrap {
		--ring: color-mix(in srgb, var(--color-accent) 25%, transparent);
		position: relative;
		display: flex;
		align-items: center;
		gap: var(--space-2);
		width: 100%;
		min-width: 0;
		padding: 0 var(--space-3);
		background: var(--color-surface-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		color: var(--color-text);
		transition: border-color var(--dur-fast) ease;
	}
	/* кільце фокуса «виростає» з рамки (transform + opacity) */
	.wrap::after {
		content: '';
		position: absolute;
		inset: -4px;
		border: 3px solid var(--ring);
		border-radius: calc(var(--radius-md) + 3px);
		opacity: 0;
		transform: scale(0.97);
		pointer-events: none;
		transition:
			opacity 200ms var(--ease-out),
			transform 420ms var(--ease-spring);
	}
	.wrap:focus-within::after {
		opacity: 1;
		transform: scale(1);
	}
	:global(html[data-perf='lite']) .wrap::after {
		transition: opacity 160ms var(--ease-out);
	}
	:global(html[data-anim='off']) .wrap::after {
		transition: none;
	}
	.s-sm {
		height: var(--control-h-sm);
		font-size: var(--text-sm);
	}
	.s-md {
		height: var(--control-h-md);
		font-size: var(--text-md);
	}
	.s-lg {
		height: var(--control-h-lg);
		font-size: var(--text-base);
	}
	.wrap:hover:not(.disabled) {
		border-color: var(--color-border-strong);
	}
	.wrap:focus-within {
		border-color: var(--color-accent);
	}
	.wrap.invalid {
		--ring: color-mix(in srgb, var(--color-danger) 25%, transparent);
		border-color: var(--color-danger);
	}
	.wrap.disabled {
		opacity: 0.55;
		cursor: not-allowed;
	}
	.inp {
		flex: 1;
		min-width: 0;
		height: 100%;
		padding: 0;
		font: inherit;
		color: inherit;
		background: transparent;
		border: 0;
		outline: 0;
	}
	.inp::placeholder {
		color: var(--color-text-subtle);
	}
	.inp:disabled {
		cursor: not-allowed;
	}
	.lead,
	.trail {
		display: inline-flex;
		align-items: center;
		flex-shrink: 0;
		color: var(--color-text-subtle);
	}
	.tr-btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		width: 28px;
		height: 28px;
		margin-right: -6px;
		color: var(--color-text-muted);
		background: transparent;
		border: 0;
		border-radius: var(--radius-sm);
		cursor: pointer;
	}
	.tr-btn:hover:not(:disabled) {
		background: var(--color-hover);
		color: var(--color-text);
	}
	/* іконка ока «перевертається» навколо вертикальної осі */
	.eye {
		position: relative;
		display: inline-flex;
		width: 16px;
		height: 16px;
		perspective: 60px;
	}
	.e {
		position: absolute;
		inset: 0;
		display: inline-flex;
		transition:
			transform 380ms var(--ease-spring),
			opacity 180ms ease;
	}
	.e-open {
		opacity: 1;
		transform: rotateY(0);
	}
	.e-off {
		opacity: 0;
		transform: rotateY(-90deg) scale(0.6);
	}
	.eye.shown .e-open {
		opacity: 0;
		transform: rotateY(90deg) scale(0.6);
	}
	.eye.shown .e-off {
		opacity: 1;
		transform: rotateY(0);
	}
	:global(html[data-anim='off']) .e {
		transition: none;
	}
	@media (max-width: 640px) {
		.tr-btn {
			width: 36px;
			height: 36px;
		}
	}
</style>
