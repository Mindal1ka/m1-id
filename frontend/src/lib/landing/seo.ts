// SEO лендінгу: заголовок, опис, ключові варіанти назв, FAQ і JSON-LD.
// Одне місце правди — Landing.svelte лише рендерить це в <head> і в блок FAQ.
//
// Варіанти, якими люди шукають (саме так їх пишуть у пошуку):
//   MyStat → «майстат», «май стат», «мистат», «mystat itstep», «мій стат»
//   M1 ID  → «м1 айді», «м1 айди», «m1id», «м1 ід», «ем1 айді»
// Їх згадуємо природно у видимому тексті (FAQ, підвал) і в alternateName JSON-LD —
// пошуковики довіряють видимому тексту більше, ніж прихованим тегам.

export const SITE_URL = 'https://m1id.xyz';
export const OG_IMAGE = `${SITE_URL}/og.jpg`;

export const SEO_TITLE = 'M1 ID (М1 Айді) — швидкий клієнт MyStat (Майстат) для IT STEP';
export const SEO_DESCRIPTION =
	'M1 ID — неофіційний клієнт MyStat (Майстат) для студентів IT STEP: розклад, домашка, ' +
	'оцінки й Telegram-бот в одному акаунті. Швидко, офлайн, на телефоні й ПК.';
export const SEO_KEYWORDS = [
	'M1 ID',
	'м1 айді',
	'м1 айди',
	'm1id',
	'MyStat',
	'майстат',
	'май стат',
	'мистат',
	'mystat itstep',
	'mystat IT STEP',
	'розклад IT STEP',
	'домашка mystat',
	'оцінки mystat',
	'IT STEP Academy',
	'IT STEP School'
].join(', ');

export const ALT_NAMES = ['М1 Айді', 'М1 Айди', 'M1ID', 'М1 ID', 'M1 ID MyStat'];

export interface Faq {
	q: string;
	a: string;
}

// Відповіді — правдиві й короткі: їх же Google може показати прямо у видачі.
export const FAQ: Faq[] = [
	{
		q: 'Що таке M1 ID (М1 Айді)?',
		a:
			'M1 ID — це швидкий і зручний клієнт для MyStat (Майстат), щоденника студентів IT STEP. ' +
			'Розклад, домашні завдання, оцінки, харчування, магазин і нагороди — в одному застосунку, ' +
			'який відкривається миттєво й працює навіть офлайн. Назву пишуть по-різному: M1 ID, М1 Айді, М1 Айди.'
	},
	{
		q: 'Чим M1 ID відрізняється від MyStat?',
		a:
			'Дані ті самі, що й у MyStat, але інтерфейс швидший і простіший: головний екран із віджетами, ' +
			'які налаштовуєш під себе, домашка за статусами й дедлайнами, розклад на тиждень одним рухом ' +
			'і Telegram-бот, що сам пише про нові оцінки й домашні завдання.'
	},
	{
		q: 'Це офіційний застосунок MyStat чи IT STEP?',
		a:
			'Ні. M1 ID — незалежний неофіційний проєкт і не пов’язаний з IT STEP. ' +
			'Ти входиш своїм логіном MyStat, а M1 ID лише показує твої дані зручніше.'
	},
	{
		q: 'Чи безпечно входити в M1 ID з паролем від MyStat?',
		a:
			'Пароль MyStat не зберігається: сервер один раз отримує токен доступу і тримає його зашифрованим. ' +
			'Для самого M1 ID у тебе окремий акаунт, до якого можна підключити один або кілька акаунтів MyStat.'
	},
	{
		q: 'Чи працює M1 ID на телефоні?',
		a:
			'Так. M1 ID — це PWA: відкрий m1id.xyz у браузері телефона й додай на головний екран — ' +
			'він запускатиметься як звичайний застосунок і показуватиме останні дані навіть без інтернету.'
	}
];

/** JSON-LD (@graph): сайт, вебзастосунок і FAQ. `<` екрануємо — безпечно для <script>. */
export function jsonLd(): string {
	const data = {
		'@context': 'https://schema.org',
		'@graph': [
			{
				'@type': 'WebSite',
				'@id': `${SITE_URL}/#website`,
				url: `${SITE_URL}/`,
				name: 'M1 ID',
				alternateName: ALT_NAMES,
				inLanguage: 'uk'
			},
			{
				'@type': 'WebApplication',
				'@id': `${SITE_URL}/#app`,
				name: 'M1 ID',
				alternateName: ALT_NAMES,
				url: `${SITE_URL}/`,
				description: SEO_DESCRIPTION,
				applicationCategory: 'EducationalApplication',
				operatingSystem: 'Web, Android, iOS, Windows, macOS',
				browserRequirements: 'Сучасний браузер; встановлюється як PWA',
				inLanguage: 'uk',
				image: OG_IMAGE,
				screenshot: `${SITE_URL}/landing-shots/01-home.jpg`,
				keywords: SEO_KEYWORDS,
				isPartOf: { '@id': `${SITE_URL}/#website` }
			},
			{
				'@type': 'FAQPage',
				'@id': `${SITE_URL}/#faq`,
				mainEntity: FAQ.map((f) => ({
					'@type': 'Question',
					name: f.q,
					acceptedAnswer: { '@type': 'Answer', text: f.a }
				}))
			}
		]
	};
	return JSON.stringify(data).replace(/</g, '\\u003c');
}
