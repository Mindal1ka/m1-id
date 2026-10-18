<script lang="ts">
	import { Copy, Check } from '@lucide/svelte';
	import { showToast } from '$lib/stores/toast.svelte';
	import { pressable, pop } from '$lib/motion';

	interface Props {
		text: string;
		label?: string;
		variant?: 'icon' | 'button';
		/** Показати toast «Скопійовано». */
		toast?: boolean;
		size?: 'sm' | 'md';
		class?: string;
	}

	let {
		text,
		label = 'Копіювати',
		variant = 'icon',
		toast = false,
		size = 'md',
		class: klass = ''
	}: Props = $props();

	let copied = $state(false);
	let btn: HTMLButtonElement | undefined = $state();
	let timer: ReturnType<typeof setTimeout> | undefined;

	async function writeText(t: string): Promise<boolean> {
		try {
			if (navigator.clipboard?.writeText) {
				await navigator.clipboard.writeText(t);
				return true;
			}
		} catch {
			// пробуємо запасний варіант
		}
		try {
			const ta = document.createElement('textarea');
			ta.value = t;
			ta.setAttribute('readonly', '');
			ta.style.position = 'fixed';
			ta.style.opacity = '0';
			ta.style.top = '0';
			document.body.appendChild(ta);
			ta.select();
			const ok = document.execCommand('copy');
			document.body.removeChild(ta);
			return ok;
		} catch {
			return false;
		}
	}

	async function copy() {
		const ok = await writeText(text);
		if (!ok) return;
		copied = true;
		if (btn) pop(btn, 1.08);
		clearTimeout(timer);
		timer = setTimeout(() => (copied = false), 1500);
		if (toast) showToast('Скопійовано');
	}

	$effect(() => () => clearTimeout(timer));
</script>

<button
	bind:this={btn}
	use:pressable={{ scale: 0.92 }}
	type="button"
	class="cp v-{variant} s-{size} {klass}"
	class:done={copied}
	aria-label={variant === 'icon' ? (copied ? 'Скопійовано' : label) : undefined}
	title={variant === 'icon' ? label : undefined}
	onclick={copy}
>
	<!-- іконки накладені одна на одну: Copy згортається, Check розкривається з поворотом -->
	<span class="ico" aria-hidden="true">
		<span class="i i-copy"><Copy size={16} /></span>
		<span class="i i-check"><Check size={16} /></span>
	</span>
	{#if variant === 'button'}
		<span class="lbls">
			<span class="l l-a">{label}</span>
			<span class="l l-b" aria-hidden="true">Скопійовано</span>
		</span>
	{/if}
	<span class="sr-only" aria-live="polite">{copied ? 'Скопійовано' : ''}</span>
</button>

<style>
	.cp {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-2);
		flex-shrink: 0;
		font: inherit;
		font-weight: var(--weight-medium);
		color: var(--color-text-muted);
		background: transparent;
		border: 1px solid transparent;
		cursor: pointer;
		transition:
			background var(--dur-fast) ease,
			color var(--dur-fast) ease,
			border-color var(--dur-fast) ease;
	}
	.v-icon {
		border-radius: var(--radius-sm);
	}
	.v-icon.s-sm {
		width: var(--control-h-sm);
		height: var(--control-h-sm);
	}
	.v-icon.s-md {
		width: var(--control-h-md);
		height: var(--control-h-md);
	}
	.v-button {
		padding: 0 var(--space-4);
		color: var(--color-text);
		background: var(--color-surface-2);
		border-color: var(--color-border);
		border-radius: var(--radius-md);
		font-size: var(--text-md);
	}
	.v-button.s-sm {
		height: var(--control-h-sm);
		font-size: var(--text-sm);
	}
	.v-button.s-md {
		height: var(--control-h-md);
	}
	.cp:hover {
		color: var(--color-text);
		background: var(--color-hover);
	}
	.v-button:hover {
		border-color: var(--color-border-strong);
	}
	.cp.done {
		color: var(--color-success);
	}
	.ico {
		position: relative;
		display: inline-flex;
		width: 16px;
		height: 16px;
	}
	.i {
		position: absolute;
		inset: 0;
		display: inline-flex;
		transition:
			transform 420ms var(--ease-spring),
			opacity 160ms ease;
	}
	.i-copy {
		opacity: 1;
		transform: none;
	}
	.i-check {
		opacity: 0;
		transform: rotate(-90deg) scale(0.3);
	}
	.done .i-copy {
		opacity: 0;
		transform: rotate(90deg) scale(0.3);
	}
	.done .i-check {
		opacity: 1;
		transform: none;
	}
	/* підписи в одній комірці — ширина кнопки не стрибає */
	.lbls {
		display: inline-grid;
	}
	.l {
		grid-area: 1 / 1;
		text-align: center;
		transition:
			opacity 200ms ease,
			transform 320ms var(--ease-out);
	}
	.l-b,
	.done .l-a {
		opacity: 0;
		transform: translateY(6px);
	}
	.done .l-b {
		opacity: 1;
		transform: none;
	}
	.done .l-a {
		transform: translateY(-6px);
	}
	:global(html[data-anim='off']) .i,
	:global(html[data-anim='off']) .l {
		transition: none;
	}
	.cp:focus-visible {
		outline: 2px solid var(--color-accent);
		outline-offset: 2px;
	}
</style>
