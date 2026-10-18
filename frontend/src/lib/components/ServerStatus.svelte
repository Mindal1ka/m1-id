<script lang="ts">
	import { Loader2, AlertTriangle } from '@lucide/svelte';
	import type { SyncState } from '$lib/api/client';
	import type { TransitionConfig } from 'svelte/transition';
	import { backOut, cubicIn } from 'svelte/easing';
	import { blurFade, motionOK } from '$lib/motion';

	/** Пружинний виїзд знизу; translateX(-50%) зберігаємо, бо елемент центрується ним. */
	function rise(_n: Element, { out = false }: { out?: boolean } = {}): TransitionConfig {
		if (!motionOK()) return { duration: 0 };
		return {
			duration: out ? 200 : 460,
			easing: out ? cubicIn : backOut,
			css: (t, u) => `opacity:${Math.min(1, t * 2)};transform:translateX(-50%) translateY(${u * 24}px) scale(${0.94 + 0.06 * t})`
		};
	}

	/** Поточний стан синку сервера (api.syncStatus / WS-пуш).
	 *  Пігулка з'являється ЛИШЕ коли сервер щось робить або синк впав:
	 *  idle/done — нічого не малюємо, спокій не потребує UI. */
	let { state = null }: { state?: SyncState | null } = $props();

	const shown = $derived(
		state != null &&
			(state.status === 'running' || state.status === 'error')
	);
	const busy = $derived(state?.status === 'running');
	const err = $derived(state?.status === 'error');
	const pct = $derived(
		shown && state!.status === 'running' && state!.progress
			? state!.progress.total > 0
				? Math.min(100, Math.round((state!.progress.done / state!.progress.total) * 100))
				: null
			: null
	);
</script>

{#if shown}
	<div class="srv" class:err={state!.status === 'error'} role="status"
		aria-live="polite" in:rise out:rise={{ out: true }}>
		<!-- стани (працює ↔ помилка) перетікають через blurFade -->
		{#key state!.status}
			<span class="inner" in:blurFade={{ duration: 280, amount: 5 }}>
				{#if state!.status === 'running'}
					<span class="spin"><Loader2 size={13} strokeWidth={2.4} /></span>
					<span class="lbl">{state!.current || 'Сервер працює'}</span>
					{#if pct != null}
						<span class="pct">{pct}%</span>
						<span class="bar"><span class="fill" style:transform={`scaleX(${pct / 100})`}></span></span>
					{/if}
				{:else if state!.status === 'error'}
					<span><AlertTriangle size={13} strokeWidth={2.4} /></span>
					<span class="lbl" title={state!.error ?? ''}>
						{state!.error ? `Помилка синку: ${state!.error}` : 'Помилка синку — оновіть сторінку пізніше'}</span>
				{/if}
			</span>
		{/key}
	</div>
{/if}

<style>
	.srv {
		position: fixed;
		left: 50%;
		transform: translateX(-50%);
		/* десктоп: низ екрана; мобільний — над нижньою панеллю (медіа нижче) */
		bottom: 12px;
		z-index: 30;
		display: inline-flex;
		align-items: center;
		gap: 8px;
		max-width: min(92vw, 420px);
		padding: 7px 14px;
		font-size: 12.5px;
		font-weight: 600;
		color: var(--text-dim);
		background: var(--surface-a94, var(--surface));
		border: 1px solid var(--glass-border);
		border-radius: 999px;
		/* без backdrop-filter: фон і так 94% непрозорий (surface-a94), а
		 esbuild-мініфікатор із парою blur-декларацій у Svelte-стилях з'їдає
		 одну з них — падав cssPrefixGuard. Скло лишається на .glass/.bottombar */
		box-shadow: 0 6px 24px rgba(0, 0, 0, 0.35);
	}

	.inner {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		min-width: 0;
	}

	.spin :global(svg) {
		animation: srv-spin 0.9s linear infinite;
	}
	@keyframes srv-spin {
		to { transform: rotate(360deg); }
	}
	:global(html[data-anim='off']) .spin :global(svg) {
		animation: none;
	}

	.srv.err {
		color: var(--danger);
		border-color: color-mix(in srgb, var(--danger) 35%, transparent);
	}

	.srv :global(svg) {
		flex-shrink: 0;
	}

	.lbl {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.pct {
		flex-shrink: 0;
		font-variant-numeric: tabular-nums;
		color: var(--text);
	}

	.bar {
		flex-shrink: 0;
		width: 44px;
		height: 4px;
		border-radius: 4px;
		background: var(--surface-2);
		overflow: hidden;
	}
	.fill {
		display: block;
		width: 100%;
		height: 100%;
		border-radius: 4px;
		background: var(--accent);
		transform-origin: left center;
		transition: transform 0.4s var(--ease-spring);
	}

	@media (max-width: 980px) {
		.srv {
			/* над bottombar (~64px) */
			bottom: calc(74px + env(safe-area-inset-bottom, 0px));
		}
	}
</style>
