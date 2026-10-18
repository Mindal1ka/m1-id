<script lang="ts">
	import type { TransitionConfig } from 'svelte/transition';
	import { backOut, cubicIn } from 'svelte/easing';
	import { blurFade, motionOK, pressable } from '$lib/motion';

	/** Пружинний виїзд зверху (вхід) / швидке втягування (вихід). Лише transform+opacity. */
	function drop(_n: Element, { out = false }: { out?: boolean } = {}): TransitionConfig {
		if (!motionOK()) return { duration: 0 };
		return {
			duration: out ? 220 : 480,
			easing: out ? cubicIn : backOut,
			css: (t, u) => `opacity:${Math.min(1, t * 2)};transform:translateY(${-u * 64}px) scale(${0.94 + 0.06 * t})`
		};
	}

	let {
		show = false,
		offline = false,
		refreshing = false,
		onclose
	}: {
		show?: boolean;
		offline?: boolean;
		refreshing?: boolean;
		onclose?: () => void;
	} = $props();
</script>

<div class="banner-stack">
	{#if show}
		<div
			class="stale glass"
			class:offline
			in:drop
			out:drop={{ out: true }}
			role="status"
		>
			{#if offline}
				<span class="dot-off"></span>
				<b>Офлайн</b>
				<span class="text-dim">показуємо збережені дані</span>
			{:else}
				<span class="mini-spin" aria-hidden="true"></span>
				<!-- текст стану перетікає при зміні: оновлюємо ↔ з кешу -->
				{#key refreshing}
					<span class="txt" in:blurFade={{ duration: 300, amount: 5, delay: 60 }}>
						<b>{refreshing ? 'Оновлюємо дані…' : 'Дані з кешу'}</b>
						<span class="text-dim">
							{refreshing ? 'це займе пару секунд' : 'можуть бути застарілими'}</span
						>
					</span>
				{/key}
			{/if}
			<button
				class="x"
				use:pressable={{ scale: 0.85 }}
				aria-label="Приховати"
				onclick={() => onclose?.()}>×</button
			>
		</div>
	{/if}

	<!-- тости тепер рендерить $lib/ui/ToastHost (у +layout) -->
</div>

<style>
	/* спільний контейнер: статус-банер + тости — та сама вертикальна
	   стопка пігулок по центру зверху */
	.banner-stack {
		position: fixed;
		top: 14px;
		left: 50%;
		transform: translateX(-50%);
		z-index: 100;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 8px;
		max-width: calc(100vw - 32px);
		pointer-events: none;
	}

	.stale {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 10px 14px;
		border-radius: 999px;
		font-size: 13.5px;
		box-shadow: 0 8px 28px rgba(0, 0, 0, 0.45);
		white-space: nowrap;
		max-width: calc(100vw - 32px);
		pointer-events: auto;
	}

	.stale.offline {
		border-color: rgba(255, 180, 84, 0.4);
	}

	.txt {
		display: inline-flex;
		align-items: center;
		gap: 10px;
	}

	/* офлайн-точка «дихає» (scale + opacity) */
	.dot-off {
		width: 9px;
		height: 9px;
		border-radius: 50%;
		background: var(--amber);
		animation: dot-breathe 2s ease-in-out infinite;
	}
	@keyframes dot-breathe {
		0%, 100% { opacity: 1; transform: scale(1); }
		50% { opacity: 0.45; transform: scale(0.7); }
	}
	:global(html[data-anim='off']) .dot-off,
	:global(html[data-anim='off']) .mini-spin {
		animation: none;
	}

	.mini-spin {
		width: 15px;
		height: 15px;
		border-radius: 50%;
		border: 2px solid var(--accent-soft);
		border-top-color: var(--accent);
		animation: rot 0.8s linear infinite;
		flex-shrink: 0;
	}

	@keyframes rot {
		to {
			transform: rotate(360deg);
		}
	}

	.x {
		background: none;
		border: none;
		color: var(--text-faint);
		font-size: 16px;
		cursor: pointer;
		padding: 0 2px;
		line-height: 1;
	}

	.x:hover {
		color: var(--text);
	}
</style>
