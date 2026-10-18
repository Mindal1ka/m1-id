<script lang="ts">
	interface Props {
		size?: number;
		label?: string;
	}
	let { size = 16, label = 'Завантаження' }: Props = $props();
</script>

<!-- Дуга «дихає» (stroke-dasharray) і водночас обертається — плавніше за звичайний rotate -->
<svg
	class="spinner"
	viewBox="0 0 24 24"
	width={size}
	height={size}
	role="status"
	aria-label={label}
	fill="none"
>
	<circle class="track" cx="12" cy="12" r="9.5" pathLength="100" />
	<circle class="arc" cx="12" cy="12" r="9.5" pathLength="100" />
</svg>

<style>
	.spinner {
		display: inline-block;
		flex-shrink: 0;
		color: inherit;
		animation: sp-rot 1.4s linear infinite;
	}
	circle {
		stroke: currentColor;
		stroke-width: 2.5;
	}
	.track {
		opacity: 0.22;
	}
	.arc {
		stroke-linecap: round;
		stroke-dasharray: 38 100;
		transform-origin: 50% 50%;
		animation: sp-dash 1.4s cubic-bezier(0.45, 0, 0.35, 1) infinite;
	}
	/* reduced-motion: статична дуга замість обриву анімації на 1-й ітерації */
	@media (prefers-reduced-motion: reduce) {
		.spinner,
		.arc {
			animation: none !important;
		}
	}
	@keyframes sp-rot {
		to {
			transform: rotate(360deg);
		}
	}
	@keyframes sp-dash {
		0% {
			stroke-dasharray: 4 100;
			stroke-dashoffset: 0;
		}
		50% {
			stroke-dasharray: 62 100;
			stroke-dashoffset: -16;
		}
		100% {
			stroke-dasharray: 4 100;
			stroke-dashoffset: -98;
		}
	}
</style>
