<script lang="ts">
	interface Props {
		vertical?: boolean;
		spacing?: 'none' | 'sm' | 'md' | 'lg';
	}
	let { vertical = false, spacing = 'md' }: Props = $props();
</script>

<div
	class="divider s-{spacing}"
	class:vertical
	role="separator"
	aria-orientation={vertical ? 'vertical' : 'horizontal'}
></div>

<style>
	.divider {
		flex-shrink: 0;
		background: var(--color-border);
	}
	.divider:not(.vertical) {
		width: 100%;
		height: 1px;
	}
	.vertical {
		align-self: stretch;
		width: 1px;
	}
	.s-sm:not(.vertical) {
		margin: var(--space-2) 0;
	}
	.s-md:not(.vertical) {
		margin: var(--space-4) 0;
	}
	.s-lg:not(.vertical) {
		margin: var(--space-6) 0;
	}
	.s-sm.vertical {
		margin: 0 var(--space-2);
	}
	.s-md.vertical {
		margin: 0 var(--space-4);
	}
	.s-lg.vertical {
		margin: 0 var(--space-6);
	}
</style>
