<script lang="ts">
	import { blurFade } from '$lib/motion';

	// Анімація «кубика» з онбордінгу: показуємо під час холодного
	// завантаження /app (без клієнтського кешу), поки дані їдуть з MyStat.
	// `note` — поточна фаза («отримую акаунти…», «збираю дані з MyStat…»);
	// при зміні фраза перетікає (blur-кросфейд), як раніше на онбордінгу.
	let {
		note = 'Ми готуємо все для вас…',
		progress = null
	}: { note?: string; progress?: number | null } = $props();

	const pct = $derived(progress == null ? null : Math.max(0, Math.min(1, progress)));
</script>

<div class="stage" role="status">
	<div class="glow" aria-hidden="true"></div>

	<div class="mark breathe-mark" aria-hidden="true">
		<div class="spinner">
			<div></div>
			<div></div>
			<div></div>
			<div></div>
			<div></div>
			<div></div>
		</div>
	</div>

	<span class="brand brand-font" aria-hidden="true">M1 ID</span>

	<!-- фрази накладаються в одній клітинці: стара тане, нова проявляється -->
	<div class="phrases">
		{#key note}
			<p
				class="phrase"
				in:blurFade={{ duration: 420, amount: 8, y: 6, delay: 120 }}
				out:blurFade={{ duration: 260, amount: 8, y: -6 }}
			>
				{note}
			</p>
		{/key}
	</div>

	<div
		class="bar"
		class:indet={pct == null}
		role="progressbar"
		aria-valuenow={pct == null ? undefined : Math.round(pct * 100)}
	>
		{#if pct != null}
			<div class="bar-fill" style:transform={`scaleX(${pct})`}></div>
		{:else}
			<div class="bar-run"></div>
		{/if}
	</div>
</div>

<style>
	.stage {
		min-height: 100dvh;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 26px;
		perspective: 900px;
		position: relative;
	}

	/* м'яке сяйво за маркою: «дихає» */
	.glow {
		position: absolute;
		top: 50%;
		left: 50%;
		width: 360px;
		height: 360px;
		margin: -230px 0 0 -180px;
		border-radius: 50%;
		background: radial-gradient(circle, color-mix(in srgb, var(--accent) 22%, transparent), transparent 68%);
		pointer-events: none;
		animation: glow-breathe 3.2s ease-in-out infinite;
	}
	@keyframes glow-breathe {
		0%, 100% { opacity: 0.55; transform: scale(0.9); }
		50% { opacity: 1; transform: scale(1.08); }
	}

	.mark {
		animation: mark-breathe 3.2s ease-in-out infinite;
	}
	@keyframes mark-breathe {
		0%, 100% { transform: scale(0.94); }
		50% { transform: scale(1.06); }
	}

	.brand {
		font-size: 13px;
		font-weight: 700;
		letter-spacing: 0.32em;
		text-indent: 0.32em;
		color: var(--text-faint, var(--text));
		opacity: 0.8;
		animation: brand-breathe 3.2s ease-in-out infinite;
	}
	@keyframes brand-breathe {
		0%, 100% { opacity: 0.45; }
		50% { opacity: 0.95; }
	}

	/* ── 3D-куб (анімація з онбордінгу, у палітрі M1 ID) ── */
	.spinner {
		width: 72px;
		height: 72px;
		--clr: var(--accent); /* акцент теми (дефолт — «має» з лендінгу) */
		--clr-alpha: color-mix(in srgb, var(--accent) 10%, transparent);
		animation: spinner 1.6s infinite ease;
		transform-style: preserve-3d;
		position: relative;
	}

	.spinner > div {
		background-color: var(--clr-alpha);
		height: 100%;
		position: absolute;
		width: 100%;
		border: 3.5px solid var(--clr);
	}

	.spinner div:nth-of-type(1) {
		transform: translateZ(-36px) rotateY(180deg);
	}

	.spinner div:nth-of-type(2) {
		transform: rotateY(-270deg) translateX(50%);
		transform-origin: top right;
	}

	.spinner div:nth-of-type(3) {
		transform: rotateY(270deg) translateX(-50%);
		transform-origin: center left;
	}

	.spinner div:nth-of-type(4) {
		transform: rotateX(90deg) translateY(-50%);
		transform-origin: top center;
	}

	.spinner div:nth-of-type(5) {
		transform: rotateX(-90deg) translateY(50%);
		transform-origin: bottom center;
	}

	.spinner div:nth-of-type(6) {
		transform: translateZ(36px);
	}

	@keyframes spinner {
		0% {
			transform: rotate(45deg) rotateX(-25deg) rotateY(25deg);
		}
		50% {
			transform: rotate(45deg) rotateX(-385deg) rotateY(25deg);
		}
		100% {
			transform: rotate(45deg) rotateX(-385deg) rotateY(385deg);
		}
	}

	.phrases {
		display: grid;
		justify-items: center;
		min-height: 1.4em;
	}

	.phrase {
		grid-area: 1 / 1;
		font-family: var(--font-display);
		font-weight: 700;
		font-size: clamp(18px, 4vw, 26px);
		color: var(--text);
		text-align: center;
		min-height: 1.4em;
		margin: 0;
	}

	/* ── прогрес-бар: scaleX-заповнення + шимер; без значення — біжить смужка ── */
	.bar {
		position: relative;
		width: min(320px, 70vw);
		height: 6px;
		border-radius: 999px;
		background: var(--surface-2);
		overflow: hidden;
	}

	.bar-fill {
		position: absolute;
		inset: 0;
		background: var(--accent);
		border-radius: inherit;
		transform-origin: left center;
		transition: transform 0.5s var(--ease-spring);
	}
	/* шимер, що біжить по заповненню */
	.bar::after {
		content: '';
		position: absolute;
		inset: 0;
		transform: translateX(-100%);
		background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.45), transparent);
		animation: bar-shimmer 1.4s ease-in-out infinite;
	}
	@keyframes bar-shimmer {
		to { transform: translateX(100%); }
	}

	.bar-run {
		position: absolute;
		top: 0;
		bottom: 0;
		left: 0;
		width: 40%;
		border-radius: inherit;
		background: var(--accent);
		animation: bar-run 1.3s cubic-bezier(0.65, 0, 0.35, 1) infinite;
	}
	@keyframes bar-run {
		from { transform: translateX(-100%); }
		to { transform: translateX(250%); }
	}

	@media (prefers-reduced-motion: reduce) {
		.spinner {
			animation-duration: 6s;
		}
	}
	/* «Анімація появи» = Вимк: статична марка, без дихання/шимеру */
	/* lite: куб і біжуча смужка лишаються, декоративні «дихання» й шимер — ні */
	:global(html[data-perf='lite']) :is(.glow, .brand) {
		animation: none;
	}
	:global(html[data-perf='lite']) .bar::after {
		display: none;
	}
	:global(html[data-anim='off']) :is(.glow, .mark, .brand, .bar-run) {
		animation: none;
	}
	:global(html[data-anim='off']) .bar::after {
		animation: none;
	}
	:global(html[data-anim='off']) .spinner {
		animation-duration: 6s;
	}
</style>
