<script lang="ts">
	import { browser } from '$app/environment';
	import { PROJECT_NAME } from '$lib/config';
	import '@fontsource-variable/golos-text';
	import LandingHero from './LandingHero.svelte';
	import { wipe, words, chars, parallax, story, fallback } from '$lib/landing/reveal';
	import {
		SITE_URL,
		OG_IMAGE,
		SEO_TITLE,
		SEO_DESCRIPTION,
		SEO_KEYWORDS,
		FAQ,
		jsonLd
	} from '$lib/landing/seo';

	// JSON-LD як готовий <script>; закриваючий тег зібрано з частин, щоб не
	// зламати <script> самого компонента
	const ldScript = '<script type="application/ld+json">' + jsonLd() + '<' + '/script>';

	// Мобільна сцена «айфон» (лише ≤760px; на ПК — секції .cut нижче).
	// Перемикання — стрілками, крапками або свайпом по екрану телефона.
	// m — вертикальний мобільний кадр (tools/shots.mjs --mobile), d — запасний
	// ПК-кадр, pos — яку частину ПК-кадру показати в екрані телефона.
	const STORY: { title: string; text: string; m: string; d: string; pos: string; fit?: 'contain' }[] = [
		{
			title: 'Домашка, яку не губиш',
			text: 'Статуси замість хаосу. Найближчі дедлайни — нагорі, протерміноване чекає на роботу.',
			m: '/landing-shots/m-03-homework.jpg',
			d: '/landing-shots/03-homework.jpg',
			pos: '16% 0'
		},
		{
			title: 'Тиждень одним рухом',
			text: 'Листання тижнів і місяців, пари на сьогодні — у першому віджеті.',
			m: '/landing-shots/m-02-schedule.jpg',
			d: '/landing-shots/02-schedule.jpg',
			pos: '30% 0'
		},
		{
			title: 'Головний екран — твій',
			text: 'Рухай віджети, міняй розмір, ховай зайве. Це не фіча, це принцип.',
			m: '/landing-shots/m-10-widget-editor.jpg',
			d: '/landing-shots/10-widget-editor.jpg',
			pos: '16% 0'
		},
		{
			title: 'Бот, що пише першим',
			text: 'Дедлайн, нова домашка, свіжа оцінка — Telegram-бот повідомляє одразу.',
			m: '/landing-shots/11-telegram.png',
			d: '/landing-shots/11-telegram.png',
			pos: '50% 50%',
			// скрін чату ширший за екран телефона — показуємо цілком (фон у нього чорний)
			fit: 'contain'
		}
	];

	// Єдиний лендінг-компонент: рендериться з routes/+page.svelte ("/",
	// з автологіном) та routes/landing/+page.svelte ("/landing", без
	// редіректу). Сам компонент нічого не знає про auth і не редіректить.

	// Поява блоків при скролі — IntersectionObserver (працює скрізь,
	// на відміну від CSS scroll-driven, який зʼїв мініфікатор/старі браузери)
	function rv(node: HTMLElement, delay: number = 0): { destroy?: () => void } {
		if (!browser || matchMedia('(prefers-reduced-motion: reduce)').matches) return {};
		node.classList.add('rv');
		if (delay) node.style.transitionDelay = `${delay}ms`;
		let done = false;
		const io = new IntersectionObserver(
			(es) => {
				if (!es.some((e) => e.isIntersecting)) return;
				done = true;
				node.classList.add('rv-in');
				io.disconnect();
			},
			{ threshold: 0.18 }
		);
		io.observe(node);
		return { destroy: () => !done && io.disconnect() };
	}

</script>

<svelte:head>
	<title>{SEO_TITLE}</title>
	<meta name="description" content={SEO_DESCRIPTION} />
	<meta name="keywords" content={SEO_KEYWORDS} />
	<meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1" />
	<meta name="application-name" content={PROJECT_NAME} />
	<meta name="apple-mobile-web-app-title" content={PROJECT_NAME} />
	<!-- «/» і «/landing» — той самий лендінг: канонічна адреса одна -->
	<link rel="canonical" href="https://m1id.xyz/" />
	<link rel="alternate" hreflang="uk" href="https://m1id.xyz/" />
	<link rel="alternate" hreflang="x-default" href="https://m1id.xyz/" />

	<!-- прев'ю посилань: Telegram, Viber, Facebook, X -->
	<meta property="og:type" content="website" />
	<meta property="og:site_name" content={PROJECT_NAME} />
	<meta property="og:locale" content="uk_UA" />
	<meta property="og:url" content="{SITE_URL}/" />
	<meta property="og:title" content={SEO_TITLE} />
	<meta property="og:description" content={SEO_DESCRIPTION} />
	<meta property="og:image" content={OG_IMAGE} />
	<meta property="og:image:width" content="1200" />
	<meta property="og:image:height" content="630" />
	<meta property="og:image:alt" content="M1 ID — твій MyStat, нарешті такий, яким має бути" />
	<meta name="twitter:card" content="summary_large_image" />
	<meta name="twitter:title" content={SEO_TITLE} />
	<meta name="twitter:description" content={SEO_DESCRIPTION} />
	<meta name="twitter:image" content={OG_IMAGE} />

	{@html ldScript}
</svelte:head>

<div class="landing">
	<!-- ── навігація ── -->
	<nav class="lnav">
		<a class="brand" href="/">M1 ID</a>
		<div class="links">
			<a class="quiet" href="/login" data-sveltekit-reload>Увійти</a>
			<a class="go" href="/app" data-sveltekit-reload>Перейти&nbsp;→</a>
		</div>
	</nav>

	<!-- ── сцена 1 · відкриття: моушн-інтро + hero (LandingHero.svelte) ── -->
	<LandingHero />

	<!-- ── сцена 2 (телефон) · «айфон»: знизу виїжджає телефон, зверху текст,
	     гортання прокручує екран. На ПК прихована — там секції .cut ── -->
	<section class="story" aria-label="Можливості M1 ID" use:story>
		<div class="st-texts" aria-live="polite">
			{#each STORY as s, i (s.title)}
				<div class="st-txt" class:on={i === 0}>
					<span class="st-idx">0{i + 1} / 0{STORY.length}</span>
					<h2>{s.title}</h2>
					<p>{s.text}</p>
				</div>
			{/each}
		</div>
		<div class="st-stage">
			<button class="st-arrow st-prev" type="button" aria-label="Попередній розділ">‹</button>
			<div class="st-phone">
				<div class="st-screen">
					{#each STORY as s (s.title)}
						<img
							class="st-shot"
							class:tg={s.fit === 'contain'}
							src={s.m}
							data-fallback={s.d}
							style="--pos: {s.pos}"
							alt={s.title}
							loading="lazy"
							draggable="false"
							use:fallback
						/>
					{/each}
				</div>
				<span class="st-island" aria-hidden="true"></span>
			</div>
			<button class="st-arrow st-next" type="button" aria-label="Наступний розділ">›</button>
		</div>
		<div class="st-dots">
			{#each STORY as s, i (s.title)}
				<button type="button" class:on={i === 0} aria-label="Розділ {i + 1}: {s.title}"></button>
			{/each}
		</div>
	</section>

	<!-- ── сцена 3 · врізки (ПК) ── -->
	<section class="cut" aria-label="Домашнє завдання">
		<span class="idx" aria-hidden="true" use:wipe={'up'} use:parallax={0.16}>01</span>
		<figure class="frame" use:wipe={'left'} use:parallax={-0.05}>
			<img
				src="/landing-shots/03-homework.jpg"
				alt="Домашка за статусами: вкладка «До виконання»"
				width="1920"
				height="1080"
				loading="lazy"
			/>
		</figure>
		<div class="txt">
			<h2 use:words={180}>Домашка, яку не губиш</h2>
			<p use:rv={420}>
				Статуси замість хаосу: до виконання, на перевірці, виконано.
				Найближчі дедлайни — нагорі. Протерміноване не зникає, а чекає на роботу.
			</p>
		</div>
	</section>

	<section class="cut flip" aria-label="Розклад">
		<span class="idx" aria-hidden="true" use:wipe={'up'} use:parallax={0.16}>02</span>
		<figure class="frame" use:wipe={'right'} use:parallax={-0.05}>
			<img
				src="/landing-shots/02-schedule.jpg"
				alt="Тижневий розклад із листанням тижнів"
				width="1920"
				height="1080"
				loading="lazy"
			/>
		</figure>
		<div class="txt">
			<h2 use:words={180}>Тиждень одним рухом</h2>
			<p use:rv={420}>
				Листання тижнів і місяців, пари на сьогодні — у першому віджеті.
				Нічого відкривати більше не треба.
			</p>
		</div>
	</section>

	<section class="cut" aria-label="Редактор віджетів">
		<span class="idx" aria-hidden="true" use:wipe={'up'} use:parallax={0.16}>03</span>
		<figure class="frame" use:wipe={'left'} use:parallax={-0.05}>
			<img
				src="/landing-shots/10-widget-editor.jpg"
				alt="Редактор головного екрана: віджети, які рухаються і змінюють розмір"
				width="1920"
				height="1080"
				loading="lazy"
			/>
		</figure>
		<div class="txt">
			<h2 use:words={180}>Інтерфейс, який налаштовуєш під себе</h2>
			<p use:rv={420}>
				Рухай віджети, міняй розмір, ховай зайве. Головний екран — твій,
				а не наш. Це не фіча, це принцип.
			</p>
		</div>
	</section>

	<section class="cut phone flip" aria-label="Telegram-бот">
		<span class="idx" aria-hidden="true" use:wipe={'up'} use:parallax={0.16}>04</span>
		<figure class="frame tel" use:wipe={'up'}>
			<img
				src="/landing-shots/11-telegram.png"
				alt="Повідомлення Telegram-бота M1 ID: наближається дедлайн, нові домашні завдання, нові оцінки"
				width="898"
				height="1372"
				loading="lazy"
			/>
		</figure>
		<div class="txt">
			<h2 use:words={180}>Бот, що пише першим</h2>
			<p use:rv={420}>
				Наближається дедлайн, нові домашки, свіжі оцінки — Telegram-бот
				M1 ID повідомляє одразу, як тільки щось змінюється. Щоб дізнатись
				нове, не треба відкривати MyStat «просто глянути».
			</p>
		</div>
	</section>

	<!-- ── FAQ: видимий текст із варіантами назв (MyStat/Майстат, M1 ID/М1 Айді)
	     + розмітка FAQPage у JSON-LD (seo.ts) ── -->
	<section class="faq" aria-labelledby="faq-h">
		<div class="faq-head">
			<h2 id="faq-h" use:words>Питання про M1 ID</h2>
			<p class="faq-intro" use:rv={200}>
				Що це, чим відрізняється від MyStat і чи безпечно ним користуватись — коротко.
			</p>
			<a class="faq-ask" href="https://mindal1ka.com" target="_blank" rel="noopener" use:rv={320}>
				Не знайшов відповіді? <span>Напиши автору →</span>
			</a>
		</div>
		<div class="faq-list">
			{#each FAQ as f, i (f.q)}
				<details class="faq-item" use:rv={i * 80}>
					<summary><span class="faq-n">0{i + 1}</span><span class="faq-q">{f.q}</span></summary>
					<p>{f.a}</p>
				</details>
			{/each}
		</div>
	</section>

	<!-- ── сцена 4 · фінал ── -->
	<section class="final">
		<p class="whisper" use:rv>Досить читати.</p>
		<a class="mega" href="/app" data-sveltekit-reload aria-label="Перейти до застосунку">
			<span class="mega-t" use:chars={120}>Перейти</span><span class="mega-arr" aria-hidden="true" use:rv={520}>→</span>
		</a>
		<a class="quiet big-quiet" href="/login" data-sveltekit-reload use:rv={700}>або створи акаунт</a>
	</section>

	<footer class="lfoot" use:rv>
		<span>© {new Date().getFullYear()} {PROJECT_NAME}</span>
		<span class="sep" aria-hidden="true">·</span>
		<a href="https://t.me/M1_IDBOT" target="_blank" rel="noopener">Telegram-бот</a>
		<p class="lfoot-note">
			M1 ID (М1 Айді) — неофіційний клієнт MyStat (Майстат) для студентів IT STEP. Не пов’язаний з IT
			STEP; MyStat — назва їхнього сервісу.
		</p>
	</footer>
</div>

<style>
	/* Лендінг живе у власній палітрі продукту (темній),
	 незалежно від тем застосунку: чорний «графіт», сланцеві панелі,
	 один фіолетовий акцент — як у M1 ID усередині бота. */
	.landing {
		--lbg: #0a0c10;
		--lpanel: #161a23;
		--lline: rgba(255, 255, 255, 0.09);
		--lac: #9d8cff;
		--ltext: #e9ecf4;
		--ldim: #8b93a6;

		min-height: 100dvh;
		background: var(--lbg);
		color: var(--ltext);
		font-family: 'Golos Text Variable', var(--font-body);
		overflow-x: clip;
	}

	/* ── поява при скролі (класи ставить use:rv) ── */
	/* одна плавність на весь лендінг — та сама «експо», що й у hero */
	:global(.landing .rv) {
		opacity: 0;
		transform: translateY(28px);
		transition:
			opacity 0.8s ease,
			transform 1s cubic-bezier(0.16, 1, 0.3, 1);
	}

	:global(.landing .rv.rv-in) {
		opacity: 1;
		transform: none;
	}

	/* ── навігація ── */
	.lnav {
		position: fixed;
		top: 0;
		left: 0;
		right: 0;
		z-index: 20;
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 18px clamp(20px, 5vw, 72px);
		/* плоска підкладка під кольором фону: навігація читається
		 над кадрами застосунку, без скла й блюру */
		background: rgba(10, 12, 16, 0.82);
	}

	.brand {
		font-family: var(--font-display);
		font-weight: 700;
		font-size: 17px;
		color: var(--ltext);
		text-decoration: none;
		letter-spacing: 0.02em;
	}

	.links {
		display: flex;
		align-items: center;
		gap: 22px;
	}

	.quiet {
		color: var(--ldim);
		text-decoration: none;
		font-size: 15px;
		transition: color 0.2s ease;
	}
	.quiet:hover {
		color: var(--ltext);
	}

	.go {
		font-family: var(--font-display);
		font-weight: 600;
		font-size: 14px;
		color: var(--lbg);
		background: var(--lac);
		padding: 10px 20px;
		border-radius: 12px;
		text-decoration: none;
		transition: transform 0.2s ease, background 0.2s ease;
	}
	.go:hover {
		background: #b4a8ff;
		transform: translateY(-1px);
	}

	/* ── кадри застосунку ── */
	.frame {
		margin: 0;
		border-radius: 18px;
		overflow: hidden;
		border: 1px solid var(--lline);
		box-shadow: 0 40px 120px rgba(0, 0, 0, 0.55);
		background: var(--lpanel);
	}

	.frame img {
		display: block;
		width: 100%;
		height: auto;
		transition: transform 0.9s cubic-bezier(0.16, 1, 0.3, 1);
	}


	/* телефон з ботом після появи м'яко погойдується */
	:global(.landing .frame.tel.rv-done) {
		animation: m1-tel-float 5.5s ease-in-out infinite;
	}

	/* -global-: ім'я не скоупиться, бо використовується в :global-правилі */
	@keyframes -global-m1-tel-float {
		0%,
		100% {
			translate: 0 0;
			rotate: 0deg;
		}
		50% {
			translate: 0 -10px;
			rotate: -0.6deg;
		}
	}

	/* ── сцена 3 · врізки ── */
	.cut {
		position: relative;
		min-height: 88vh;
		display: grid;
		grid-template-columns: repeat(12, 1fr);
		align-items: center;
		gap: clamp(24px, 4vw, 56px);
		padding: clamp(48px, 8vh, 96px) clamp(20px, 5vw, 72px);
		max-width: 1440px;
		margin: 0 auto;
	}

	.cut .frame {
		grid-column: 1 / 8;
		width: 100%;
	}

	.cut .txt {
		grid-column: 9 / 13;
	}

	.cut.flip .frame {
		grid-column: 6 / 13;
		grid-row: 1;
	}

	.cut.flip .txt {
		grid-column: 1 / 5;
		grid-row: 1;
	}

	/* асиметрія: непарні кадри трохи підняті */
	.cut:nth-of-type(odd) .frame {
		translate: 0 -3vh;
	}

	/* сцена з TG-ботом: вузький «телефонний» кадр */
	.cut.phone .frame.tel {
		grid-column: 2 / 6;
		width: min(360px, 78vw);
		justify-self: center;
		border-radius: 28px;
	}

	.cut.phone .txt {
		grid-column: 7 / 12;
	}

	/* бот праворуч — щоб кадри чергувались: ліво, право, ліво, право */
	.cut.phone.flip .frame.tel {
		grid-column: 8 / 12;
		grid-row: 1;
	}

	.cut.phone.flip .txt {
		grid-column: 2 / 7;
		grid-row: 1;
	}

	.idx {
		position: absolute;
		top: clamp(16px, 4vh, 48px);
		font-family: var(--font-display);
		font-weight: 900;
		font-size: clamp(72px, 10vw, 160px);
		line-height: 1;
		color: transparent;
		-webkit-text-stroke: 1px rgba(255, 255, 255, 0.13);
		pointer-events: none;
		user-select: none;
	}

	.cut .idx {
		left: clamp(20px, 5vw, 72px);
	}
	.cut.flip .idx {
		left: auto;
		right: clamp(20px, 5vw, 72px);
	}
	.cut.phone .idx {
		left: clamp(20px, 5vw, 72px);
	}
	.cut.phone.flip .idx {
		left: auto;
		right: clamp(20px, 5vw, 72px);
	}

	.txt h2 {
		font-family: var(--font-display);
		font-weight: 800;
		font-size: clamp(26px, 3vw, 44px);
		line-height: 1.12;
		letter-spacing: -0.01em;
		text-wrap: balance;
	}

	.txt p {
		margin-top: 18px;
		color: var(--ldim);
		font-size: clamp(15px, 1.4vw, 18px);
		line-height: 1.65;
		max-width: 40ch;
	}

	/* ── сцена 4 · фінал ── */
	.final {
		min-height: 92vh;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 28px;
		text-align: center;
		padding: 80px 20px;
	}

	.whisper {
		color: var(--ldim);
		font-size: 15px;
		letter-spacing: 0.24em;
		text-transform: uppercase;
	}

	/* велика кнопка: при наведенні фон заливається зліва направо, стрілка
	 зсувається; сама кнопка нікуди не рухається — hover не «блимає» */
	.mega {
		position: relative;
		isolation: isolate;
		display: inline-flex;
		align-items: baseline;
		gap: 0.28em;
		font-family: var(--font-display);
		font-weight: 900;
		font-size: clamp(52px, 11vw, 168px);
		line-height: 1;
		color: var(--ltext);
		text-decoration: none;
		padding: 0.1em 0.26em 0.14em;
		border-radius: 0.18em;
		transition: color 0.35s ease;
	}

	.mega::before {
		content: '';
		position: absolute;
		inset: 0;
		z-index: -1;
		border-radius: inherit;
		background: var(--lac);
		transform: scaleX(0);
		transform-origin: left;
		transition: transform 0.55s cubic-bezier(0.16, 1, 0.3, 1);
	}

	/* hover — лише там, де є миша: на телефонах він «залипає» після тапу */
	@media (hover: hover) {
		.mega:hover {
			color: var(--lbg);
		}

		.mega:hover::before {
			transform: scaleX(1);
		}

		.mega:hover .mega-arr {
			translate: 0.14em 0;
		}

		.frame:hover img {
			transform: scale(1.025);
		}
	}

	.mega:focus-visible {
		color: var(--lbg);
	}

	.mega:focus-visible::before {
		transform: scaleX(1);
	}

	.mega-arr {
		display: inline-block;
		transition: translate 0.45s cubic-bezier(0.16, 1, 0.3, 1);
	}



	.big-quiet {
		font-size: 17px;
	}

	/* ── FAQ ── */
	.faq {
		max-width: 1240px;
		margin: 0 auto;
		padding: clamp(64px, 12vh, 140px) clamp(20px, 5vw, 72px) 0;
	}

	.faq-head h2 {
		font-family: var(--font-display);
		font-weight: 800;
		font-size: clamp(28px, 4vw, 52px);
		line-height: 1.08;
		letter-spacing: -0.015em;
		text-wrap: balance;
	}

	.faq-intro {
		margin-top: 16px;
		max-width: 34ch;
		color: var(--ldim);
		font-size: clamp(15px, 1.3vw, 17px);
		line-height: 1.6;
	}

	.faq-ask {
		display: inline-block;
		margin-top: 22px;
		color: var(--ldim);
		font-size: 14px;
		text-decoration: none;
	}

	.faq-ask span {
		color: var(--lac);
		transition: color 0.2s ease;
	}

	.faq-list {
		display: flex;
		flex-direction: column;
		margin-top: clamp(24px, 4vh, 40px);
		border-top: 1px solid var(--lline);
	}

	.faq-item {
		position: relative;
		border-bottom: 1px solid var(--lline);
	}

	/* фіолетова лінія зліва у відкритого питання */
	.faq-item::before {
		content: '';
		position: absolute;
		left: 0;
		top: -1px;
		bottom: -1px;
		width: 2px;
		background: var(--lac);
		transform: scaleY(0);
		transform-origin: top;
		transition: transform 0.45s cubic-bezier(0.16, 1, 0.3, 1);
	}

	.faq-item[open]::before {
		transform: scaleY(1);
	}

	.faq-item summary {
		list-style: none;
		cursor: pointer;
		display: flex;
		align-items: center;
		gap: 18px;
		padding: 22px 0 22px 18px;
		color: var(--ltext);
		transition: color 0.2s ease;
	}

	.faq-item summary::-webkit-details-marker {
		display: none;
	}

	.faq-n {
		flex: none;
		width: 2ch;
		font-family: var(--font-display);
		font-weight: 800;
		font-size: 13px;
		letter-spacing: 0.06em;
		color: var(--ldim);
		transition: color 0.2s ease;
	}

	.faq-q {
		flex: 1;
		font-family: var(--font-display);
		font-weight: 700;
		font-size: clamp(16px, 1.6vw, 20px);
		line-height: 1.3;
	}

	/* «+», що повертається на «×» */
	.faq-item summary::after {
		content: '+';
		flex: none;
		display: grid;
		place-items: center;
		width: 34px;
		height: 34px;
		border-radius: 50%;
		border: 1px solid var(--lline);
		font-family: var(--font-body);
		font-weight: 400;
		font-size: 22px;
		line-height: 1;
		color: var(--lac);
		transition:
			rotate 0.35s cubic-bezier(0.16, 1, 0.3, 1),
			background 0.2s ease,
			border-color 0.2s ease;
	}

	.faq-item[open] summary::after {
		rotate: 45deg;
		background: rgba(157, 140, 255, 0.12);
		border-color: rgba(157, 140, 255, 0.4);
	}

	.faq-item[open] .faq-n {
		color: var(--lac);
	}

	@media (hover: hover) {
		.faq-item summary:hover {
			color: var(--lac);
		}

		.faq-item summary:hover::after {
			border-color: rgba(157, 140, 255, 0.4);
		}

		.faq-ask:hover span {
			color: var(--ltext);
		}
	}

	.faq-item summary:focus-visible {
		outline: 2px solid var(--lac);
		outline-offset: -2px;
		border-radius: 6px;
	}

	.faq-item p {
		padding: 0 52px 24px calc(18px + 2ch + 18px);
		max-width: 72ch;
		color: var(--ldim);
		font-size: clamp(15px, 1.3vw, 17px);
		line-height: 1.7;
	}

	/* плавне розгортання відповіді (Chrome/Edge 131+; інші — без анімації) */
	@supports (interpolate-size: allow-keywords) {
		.faq {
			interpolate-size: allow-keywords;
		}

		.faq-item::details-content {
			block-size: 0;
			overflow: clip;
			transition:
				block-size 0.45s cubic-bezier(0.16, 1, 0.3, 1),
				content-visibility 0.45s allow-discrete;
		}

		.faq-item[open]::details-content {
			block-size: auto;
		}
	}

	/* ПК: дві колонки — заголовок «прилипає» ліворуч, питання праворуч */
	@media (min-width: 961px) {
		.faq {
			display: grid;
			grid-template-columns: minmax(0, 0.85fr) minmax(0, 1.6fr);
			gap: clamp(40px, 6vw, 96px);
			align-items: start;
		}

		.faq-head {
			position: sticky;
			top: 120px;
		}

		.faq-list {
			margin-top: 0;
		}
	}

	@media (max-width: 640px) {
		.faq-item summary {
			gap: 12px;
			padding-left: 14px;
		}

		.faq-q {
			font-size: 15px;
		}

		.faq-item summary::after {
			width: 30px;
			height: 30px;
			font-size: 20px;
		}

		.faq-item p {
			padding: 0 8px 22px 14px;
		}
	}

	/* ── футер ── */
	.lfoot {
		display: flex;
		flex-wrap: wrap;
		justify-content: center;
		align-items: center;
		gap: 12px;
		padding: 28px 20px 36px;
		color: var(--ldim);
		font-size: 13px;
		border-top: 1px solid var(--lline);
	}

	.lfoot-note {
		flex-basis: 100%;
		text-align: center;
		font-size: 12px;
		line-height: 1.5;
		opacity: 0.75;
	}

	.lfoot a {
		color: var(--ldim);
		text-decoration: none;
	}
	.lfoot a:hover {
		color: var(--ltext);
	}

	/* ── планшет ── */
	@media (max-width: 1100px) {
		.cut.phone .frame.tel {
			grid-column: 1 / 7;
		}

		.cut.phone .txt {
			grid-column: 8 / 13;
		}

		.cut.phone.flip .frame.tel {
			grid-column: 7 / 13;
		}

		.cut.phone.flip .txt {
			grid-column: 1 / 6;
		}
	}

	/* ── мобільний ── */
	@media (max-width: 960px) {
		.cut {
			grid-template-columns: 1fr;
			min-height: 0;
		}

		.cut .frame,
		.cut.flip .frame {
			grid-column: 1;
			grid-row: 2;
			width: 100%;
		}

		.cut .txt,
		.cut.flip .txt,
		.cut.phone .txt {
			grid-column: 1;
			grid-row: 1;
		}

		.cut.phone .frame.tel,
		.cut.phone.flip .frame.tel {
			grid-column: 1;
			grid-row: 2;
			justify-self: center;
		}

		.cut.phone.flip .txt {
			grid-column: 1;
			grid-row: 1;
		}

		.idx {
			font-size: 64px;
		}
	}

	/* ── телефон: сцена «айфон» замість секцій .cut ── */
	.story {
		display: none;
	}

	@media (max-width: 760px) {
		.cut {
			display: none;
		}

		.story {
			display: block;
			position: relative;
			overflow: hidden;
			padding: clamp(56px, 9svh, 96px) 20px 0;
		}

		/* тексти розділів — в одній клітинці сітки, висота = найвищий */
		.st-texts {
			display: grid;
			margin-bottom: 26px;
		}

		.st-txt {
			grid-area: 1 / 1;
			opacity: 0;
			visibility: hidden;
			transform: translateY(10px);
			transition:
				opacity 0.35s ease,
				transform 0.5s cubic-bezier(0.16, 1, 0.3, 1),
				visibility 0s linear 0.35s;
		}

		.st-txt:global(.on) {
			opacity: 1;
			visibility: visible;
			transform: none;
			transition:
				opacity 0.4s ease 0.08s,
				transform 0.6s cubic-bezier(0.16, 1, 0.3, 1) 0.08s;
		}

		.st-idx {
			display: block;
			font-family: var(--font-display);
			font-weight: 900;
			font-size: 13px;
			letter-spacing: 0.1em;
			color: var(--lac);
			margin-bottom: 10px;
		}

		.st-txt h2 {
			font-family: var(--font-display);
			font-weight: 800;
			font-size: clamp(22px, 6.6vw, 30px);
			line-height: 1.12;
			letter-spacing: -0.01em;
			text-wrap: balance;
		}

		.st-txt p {
			margin-top: 12px;
			color: var(--ldim);
			font-size: 15px;
			line-height: 1.55;
			max-width: 36ch;
		}

		/* телефон зі стрілками по боках; низ телефона ховається під край секції */
		.st-stage {
			position: relative;
			display: flex;
			align-items: flex-start;
			justify-content: center;
			gap: 10px;
			height: min(118vw, 520px);
			-webkit-mask-image: linear-gradient(#000 78%, transparent);
			mask-image: linear-gradient(#000 78%, transparent);
		}

		.st-arrow {
			flex: none;
			align-self: center;
			margin-top: -40px;
			width: 44px;
			height: 44px;
			border-radius: 50%;
			border: 1px solid var(--lline);
			background: rgba(255, 255, 255, 0.04);
			color: var(--ltext);
			font: 400 26px/1 var(--font-body);
			display: grid;
			place-items: center;
			cursor: pointer;
			z-index: 2;
			transition:
				background 0.2s ease,
				transform 0.2s ease;
		}

		.st-arrow:active {
			transform: scale(0.92);
			background: rgba(157, 140, 255, 0.18);
		}

		.st-arrow:focus-visible {
			outline: 2px solid var(--lac);
			outline-offset: 2px;
		}

		.st-phone {
			position: relative;
			flex: none;
			width: min(62vw, 290px);
			aspect-ratio: 9 / 19;
			border-radius: 44px;
			background: #05060a;
			border: 1px solid rgba(255, 255, 255, 0.14);
			box-shadow:
				0 0 0 6px #11141b,
				0 0 0 7px rgba(255, 255, 255, 0.1),
				0 -30px 80px rgba(157, 140, 255, 0.12);
			touch-action: pan-y;
			transform: translateY(40%);
			opacity: 0;
			transition:
				transform 1s cubic-bezier(0.16, 1, 0.3, 1),
				opacity 0.6s ease;
		}

		/* телефон «вилазить» знизу, коли секція доїхала до екрана */
		.story:global(.st-in) .st-phone {
			transform: none;
			opacity: 1;
		}

		.st-screen {
			position: absolute;
			inset: 8px;
			border-radius: 36px;
			overflow: hidden;
			background: #000;
		}

		.st-shot {
			position: absolute;
			inset: 0;
			width: 100%;
			height: 100%;
			object-fit: cover;
			object-position: 50% 0;
			-webkit-user-select: none;
			user-select: none;
			transition: transform 0.55s cubic-bezier(0.16, 1, 0.3, 1);
			will-change: transform;
		}

		/* ПК-кадр як запасний: показуємо потрібну смугу */
		.st-shot:global(.is-crop) {
			object-position: var(--pos);
		}

		/* скрін Telegram: цілком, з чорними полями — без обрізання тексту */
		.st-shot.tg {
			object-fit: contain;
			object-position: 50% 50%;
		}

		.st-dots {
			display: flex;
			justify-content: center;
			gap: 2px;
			padding: 14px 0 clamp(40px, 7svh, 72px);
		}

		/* кнопка 28×28 (зручно влучити пальцем), видима «пігулка» — всередині */
		.st-dots button {
			display: grid;
			place-items: center;
			width: 28px;
			height: 28px;
			padding: 0;
			border: 0;
			background: none;
			cursor: pointer;
		}

		.st-dots button::before {
			content: '';
			width: 6px;
			height: 6px;
			border-radius: 3px;
			background: rgba(255, 255, 255, 0.22);
			transition:
				width 0.35s cubic-bezier(0.16, 1, 0.3, 1),
				background 0.35s ease;
		}

		.st-dots button:global(.on)::before {
			width: 20px;
			background: var(--lac);
		}

		.st-dots button:focus-visible {
			outline: 2px solid var(--lac);
			border-radius: 6px;
		}

		.st-island {
			position: absolute;
			top: 15px;
			left: 50%;
			width: 30%;
			height: 20px;
			translate: -50% 0;
			border-radius: 12px;
			background: #000;
		}
	}

	@media (max-width: 640px) {
		.lnav {
			padding: 14px 20px;
		}

		.go {
			padding: 9px 16px;
			font-size: 13px;
		}

		.links {
			gap: 16px;
		}

		.cut {
			padding: 56px 20px;
		}

		.frame {
			border-radius: 12px;
		}

		.frame.tel {
			border-radius: 22px;
		}

		.lfoot {
			flex-wrap: wrap;
			text-align: center;
		}
	}

	/* ── рушій поважає користувача ── */
	@media (prefers-reduced-motion: reduce) {
		:global(.landing .frame.tel.rv-done) {
			animation: none;
		}

		:global(.landing .rv) {
			opacity: 1;
			transform: none;
			transition: none;
		}

		.mega::before,
		.mega-arr {
			transition: none;
		}
	}
</style>
