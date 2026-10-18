<script lang="ts">
	import { onMount } from 'svelte';
	import { mountLandingMotion } from '$lib/landing/motion';
	import { fallback } from '$lib/landing/reveal';
	import '$lib/landing/motion.css';

	// Hero лендінгу з моушном: рекламне інтро на весь екран → збірка заголовка
	// → удар по «має» → при скролі літери розвалюються на скріншот застосунку.
	// Розмітка пререндериться (SEO, читається без JS); оживляє її $lib/landing/motion.ts.

	let root: HTMLElement | undefined = $state();
	let ad: HTMLElement | undefined = $state();
	let canvas: HTMLCanvasElement | undefined = $state();
	let skip: HTMLButtonElement | undefined = $state();

	// Інлайн-скрипт у <head>: ставить html.lh-anim / lh-ad-on ДО першого кадру,
	// щоб не блимав готовий заголовок. Запобіжник: якщо JS-бандл не стартував
	// за 4 с — знімаємо класи, і сторінка показується статично.
	const headScript =
		'<script>try{if(!matchMedia("(prefers-reduced-motion: reduce)").matches){' +
		'var h=document.documentElement;h.classList.add("lh-anim","lh-ad-on");' +
		'setTimeout(function(){if(!window.__lhMounted)h.classList.remove("lh-anim","lh-ad-on")},4000)}}catch(e){}<' +
		'/script>';

	onMount(() => {
		if (!root || !ad || !canvas || !skip) return;
		return mountLandingMotion({
			root,
			ad,
			canvas,
			skip,
			brand: document.querySelector<HTMLElement>('.landing .brand')
		});
	});
</script>

<svelte:head>
	{@html headScript}
</svelte:head>

<section class="lh-scroll" bind:this={root}>
	<div class="lh-stage">
		<h1 class="lh-title" aria-label="Твій MyStat. Нарешті такий, яким має бути.">
			<span class="lh-line lh-l1" aria-hidden="true">Твій MyStat.</span>
			<span class="lh-line lh-l2" aria-hidden="true">Нарешті такий,<span class="lh-scan"></span></span>
			<!-- «бути.» стоїть у тому ж рядку, якщо вміщається з найширшим словом барабана;
			     інакше (телефон) — окремим рядком від початку до кінця (рішення — motion.ts) -->
			<span class="lh-row34"><span class="lh-line lh-l3" aria-hidden="true"><span class="lh-w">яким</span><span class="lh-word lh-slotw"><span class="lh-ci lh-pi"><span class="lh-slot"><span class="lh-sw">має</span><span class="lh-strike"></span><span class="lh-mark"></span></span></span></span></span><span class="lh-line lh-l4" aria-hidden="true">бути.</span></span>
		</h1>
		<p class="lh-sub">
			<b>M1 ID</b> — один акаунт для MyStat. <b>Розклад, домашка, оцінки й харчування</b> — швидко,
			офлайн і без жодної зайвої кнопки.
		</p>
		<div class="lh-shot">
			<figure class="lh-shot-in">
				<picture>
					<!-- вертикальний телефон: мобільний кадр (tools/shots.mjs --mobile) -->
					<source media="(max-width: 760px) and (min-height: 501px)" srcset="/landing-shots/m-01-home.jpg" width="780" height="1688" />
					<img
						src="/landing-shots/01-home.jpg"
						alt="Головний екран M1 ID: віджети з розкладом, домашкою, оцінками та лідербордом"
						width="1920"
						height="1080"
						use:fallback
					/>
				</picture>
			</figure>
			<!-- підписи збоку від скріншота (як в оригінальному лендінгу) -->
			<ul class="lh-cos">
				<li class="lh-co lh-c1">Середній бал <b class="lh-avg">10.3</b> — одразу на головній, без зайвих переходів</li>
				<li class="lh-co lh-c3">Кристали, монети й бали — на одному екрані</li>
				<li class="lh-co lh-c2">Найближчі дедлайни й пари на сьогодні — перше, що бачиш</li>
			</ul>
		</div>
	</div>
</section>

<div class="lh-ad" aria-hidden="true" bind:this={ad}></div>
<canvas class="lh-fx" aria-hidden="true" bind:this={canvas}></canvas>
<button class="lh-skip" type="button" hidden bind:this={skip}>Пропустити →</button>
