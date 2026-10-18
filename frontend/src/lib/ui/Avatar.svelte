<script lang="ts">
	interface Props {
		src?: string | null;
		name?: string;
		size?: 'xs' | 'sm' | 'md' | 'lg' | 'xl' | number;
	}
	let { src = null, name = '', size = 'md' }: Props = $props();

	const sizes = { xs: 24, sm: 32, md: 40, lg: 56, xl: 80 };
	const px = $derived(typeof size === 'number' ? size : sizes[size]);
	const initials = $derived(
		name
			.trim()
			.split(/\s+/)
			.filter(Boolean)
			.slice(0, 2)
			.map((w) => Array.from(w)[0]?.toUpperCase() ?? '')
			.join('') || '?'
	);
	let failed = $state(false);
	let loaded = $state(false);
	// Скидаємо помилку/завантаження лише при СПРАВЖНІЙ зміні src. Раніше ефект
	// спрацьовував і на першому рендері — ПІСЛЯ onload фото з кешу — і фото
	// назавжди лишалось прозорим (opacity 0).
	let prevSrc: string | null | undefined = undefined;
	$effect.pre(() => {
		if (prevSrc !== undefined && prevSrc !== src) {
			failed = false;
			loaded = false;
		}
		prevSrc = src;
	});

	// Картинка могла завантажитися з кешу до підключення обробника
	function check(img: HTMLImageElement) {
		if (img.complete && img.naturalWidth > 0) loaded = true;
	}
</script>

<span
	class="avatar"
	style:width="{px}px"
	style:height="{px}px"
	style:font-size="{Math.max(10, Math.round(px * 0.38))}px"
>
	{#if src && !failed}
		<img
			{src}
			alt={name}
			class:loaded
			use:check
			onload={() => (loaded = true)}
			onerror={() => (failed = true)}
		/>
	{:else}
		<span aria-label={name || undefined}>{initials}</span>
	{/if}
</span>

<style>
	.avatar {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		overflow: hidden;
		font-weight: var(--weight-semibold);
		line-height: 1;
		color: var(--color-accent-text);
		background: var(--color-accent-soft);
		border: 1px solid var(--color-border);
		border-radius: 50%;
		user-select: none;
	}
	/* фото «проявляється»: з розмиття й легкого збільшення */
	img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		opacity: 0;
		filter: blur(8px);
		transform: scale(1.12);
		transition:
			opacity 380ms var(--ease-out),
			filter 520ms var(--ease-out),
			transform 520ms var(--ease-out);
	}
	img.loaded {
		opacity: 1;
		filter: none;
		transform: none;
	}
	:global(html[data-anim='off']) img {
		opacity: 1;
		filter: none;
		transform: none;
		transition: none;
	}
</style>
