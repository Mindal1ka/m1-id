/* M1 ID service worker: оболонка миттєво з кешу (навіть ОНЛАЙН), тиха
 * ревалідація у фоні. Вкладки далі прискорює клієнтський кеш appStore
 * (localStorage) — SW відповідає лише за фронтенд-оболонку та ассети.
 *
 * ВАЖЛИВО: це класичний скрипт (без type:'module') — чистий JS.
 * Помилка парсингу = воркер не живе = білий екран офлайн.
 *
 * Стратегії:
 *  • install — прекешуємо ОБОЛОНКУ: '/', '/app', PWA-статику та ВЕСЬ
 *    граф immutable-чанків (BFS по import()/url() у завантажених JS/CSS,
 *    шляхи контентно-хешовані → безпечно кеш-первим).
 *    У кеш потрапляють лише ok-відповіді БЕЗ редіректів; для HTML-оболонки
 *    потрібен text/html, для решти — НЕ text/html (SPA-фолбек віддає
 *    app.html на відсутній файл, його не можна класти замість ассета).
 *    → холодний офлайн-старт одразу після встановлення воркера.
 *  • /_app/immutable/*, шрифти — кеш-первим: спершу кеш ПОТОЧНОЇ версії,
 *    потім старі кеші (чанк старішої вкладки ще має віддаватись).
 *  • навігація та інші same-origin GET — stale-while-revalidate ЛИШЕ з
 *    кешу поточної версії: є → віддаємо МИТТЄВО, свіжу копію тягнемо
 *    тихо у фон (через event.waitUntil); немає → мережа → кеш; зовсім
 *    офлайн → кешований '/app' (SPA-роутер сам розрулить /app?...).
 *  • /api/*, /plugins/*, кореневі *.json — не кешуємо: дані вирішує клієнт.
 */
const VERSION = 'm1id-v17';
// Офлайн-фолбек навігацій — SPA-шелл '/app' (app.html).
// '/' тепер пререндерений ЛЕНДІНГ: він кешується як звичайна сторінка,
// але офлайн-шеллом йому бути не можна (гідратація на чужому шляху ламає роутер).
const SHELL_URL = '/app';
const SHELL_ROUTES = ['/', '/app'];
const STATIC_FILES = ['/manifest.webmanifest', '/icon.svg', '/icon-192.png', '/icon-512.png'];
const MAX_FILES = 800; // страховка від розгону краулера
// Ліміт «runtime»-записів поточного кешу (скріншоти лендінгу тощо):
// найстаріші понад ліміт видаляються.
const MAX_RUNTIME_ENTRIES = 60;

const isHtml = (res) => (res.headers.get('content-type') ?? '').includes('text/html');
/** Відповідь придатна для кешування: успішна, не opaque, без редіректу. */
const storable = (res) => Boolean(res) && res.ok && !res.redirected && res.type !== 'opaque';

self.addEventListener('install', (event) => {
	event.waitUntil(
		(async () => {
			const cache = await caches.open(VERSION);

			// PWA-статика (не критично, якщо чогось немає). Кладемо лише
			// не-HTML відповіді без редіректів.
			await Promise.allSettled(
				STATIC_FILES.map(async (u) => {
					const res = await fetch(u, { cache: 'no-cache' });
					if (storable(res) && !isHtml(res)) await cache.put(u, res);
				})
			);

			// SvelteKit віддає ВІДНОСНІ шляхи ('./_app/...', '../nodes/N.js'),
			// вхідні скрипти — в inline import("./..."). Ловимо будь-які рядки
			// виду ./path, ../path, /path і резолвимо відносно поточного файла.
			const RE = /["'(]((?:\.{0,2}\/)[^"'()\s]+)/g;
			const queue = [];
			const seen = new Set();

			/** Додає URL у чергу, якщо це same-origin immutable-ассет. */
			const push = (u) => {
				if (u.origin !== location.origin) return;
				if (!u.pathname.startsWith('/_app/immutable/')) return;
				const k = u.pathname;
				if (seen.has(k) || seen.size >= MAX_FILES) return;
				seen.add(k);
				queue.push(u.href);
			};

			/** Завантажити, покласти в кеш, повернути текст (для JS/CSS-скану). */
			const grab = async (href) => {
				try {
					const res = await fetch(href, { cache: 'no-cache' });
					if (!storable(res) || isHtml(res)) return null;
					await cache.put(href, res.clone());
					const ct = res.headers.get('content-type') ?? '';
					if (!/javascript|css/.test(ct)) return null;
					return await res.text();
				} catch {
					return null;
				}
			};

			// оболонка: HTML маршрутів — паралельно. Без оболонки оновлення
			// не приймаємо (перевірка нижче): краще лишитись на старій
			// версії, ніж «окирпичити» офлайн-старт
			let shellOk = 0;
			await Promise.all(
				SHELL_ROUTES.map(async (route) => {
					try {
						const res = await fetch(route, { cache: 'no-cache' });
						if (!storable(res) || !isHtml(res)) return;
						shellOk++;
						await cache.put(route, res.clone());
						const base = new URL(route, location.origin);
						const html = await res.text();
						for (const m of html.matchAll(RE)) {
							let u;
							try {
								u = new URL(m[1], base);
							} catch {
								continue;
							}
							push(u);
						}
					} catch {
						/* офлайн — докешує SWR при першому онлайні */
					}
				})
			);

			// BFS по чанках — ХВИЛЯМИ (фронтир цілком). Хвиля обмежена
			// 6 паралельними: на мобільному не душимо канал, щоб оновлення
			// не заважало живим /api-запитам сторінки
			const WAVE = 6;
			while (queue.length) {
				const wave = queue.splice(0, WAVE);
				const bodies = await Promise.all(wave.map((h) => grab(h)));
				wave.forEach((href, wi) => {
					const body = bodies[wi];
					if (!body) return;
					const base = new URL(href);
					for (const m of body.matchAll(RE)) {
						let u;
						try {
							u = new URL(m[1], base);
						} catch {
							return;
						}
						push(u);
					}
				});
			}

			// зрив встановлення, якщо оболонку завантажити не вдалося:
			// браузер відкине новий воркер, старий продовжить працювати
			if (shellOk === 0) {
				throw new Error('shell prefetch failed — keep old worker');
			}
			await self.skipWaiting();
		})()
	);
});

self.addEventListener('activate', (event) => {
	event.waitUntil(
		(async () => {
			// Тримаємо кеші ОСТАННІХ 3 версій (поточна + дві попередні):
			// вкладка двох генерацій тому після двох швидких деплоїв усе ще
			// може попросити свій чанк — динамічний import не має падати.
			const meta = await caches.open('m1id-meta');
			const list = await (async () => {
				try {
					const r = await meta.match('versions');
					if (!r) return [];
					return await r.json();
				} catch {
					return [];
				}
			})();
			// перша активність цієї системи — просто реєструємо VERSION
			const versions = Array.from(new Set([VERSION, ...list])).slice(0, 3);
			const keys = await caches.keys();
			// Лише 3 останні версії — усе інше (зокрема легасі-кеші зі старої
			// системи «prev») видаляємо.
			await Promise.all(
				keys
					.filter((k) => k !== 'm1id-meta' && !versions.includes(k))
					.map((k) => caches.delete(k))
			);
			await meta.put('versions', new Response(JSON.stringify(versions)));
			await self.clients.claim();
		})()
	);
});

self.addEventListener('message', (event) => {
	if (event.data === 'SKIP_WAITING') self.skipWaiting();
});

/** Обмежує кількість runtime-записів: видаляє найстаріші (за порядком
 *  вставки), не чіпаючи оболонку, PWA-статику та immutable-чанки. */
async function trimRuntime(cache) {
	try {
		const keep = new Set([...SHELL_ROUTES, ...STATIC_FILES]);
		const keys = await cache.keys();
		const runtime = keys.filter((r) => {
			const p = new URL(r.url).pathname;
			return !p.startsWith('/_app/immutable/') && !keep.has(p);
		});
		const extra = runtime.length - MAX_RUNTIME_ENTRIES;
		for (let i = 0; i < extra; i++) await cache.delete(runtime[i]);
	} catch {
		/* не критично */
	}
}

/** Тихе оновлення одного запису кешу. Ніколи не кидає. */
async function revalidate(request) {
	try {
		const res = await fetch(request);
		if (!storable(res)) return;
		const cache = await caches.open(VERSION);
		const url = new URL(request.url);
		if (isHtml(res)) {
			// HTML кладемо під ЧИСТИЙ pathname: раніше кешували під повний
			// URL з query (/app?account=5) — кожна навігація з новим query
			// плодила окрему копію шелла (некерований ріст кешу).
			if (url.pathname.startsWith('/_app/')) {
				await cache.put(request, res);
			} else {
				await cache.put(new Request(url.pathname), res);
			}
		} else {
			await cache.put(request, res);
		}
		await trimRuntime(cache);
		// ПРО ВЕРСІЮ клієнт дізнається через /version.json (детерміновано).
		// Пост-меседжі звідси прибрано: HTML з query-ключами (типу
		// /app?account=5) «відрізнявся» від кешу щоразу → спам тостами.
	} catch {
		/* офлайн — мовчки */
	}
}

self.addEventListener('fetch', (event) => {
	const req = event.request;
	if (req.method !== 'GET') return;

	const url = new URL(req.url);
	if (url.origin !== location.origin) return;
	// blob:, data:, about: тощо — НЕ перехоплюємо: objectURL в'ювера файлів
	// живе в реєстрі сторінки, SW його не віддасть (blob → ERR_FILE_NOT_FOUND
	// і «файл не відкривається»). Проксуємо лише звичайні http(s) GET.
	if (url.protocol !== 'http:' && url.protocol !== 'https:') return;
	if (url.pathname.startsWith('/api/')) return; // живі дані — лише мережа
	if (url.pathname === '/version.json') return; // прапор версії — завжди мережа

	// не кешуємо: каталог плагінів (великий і змінний) та кореневі *.json
	if (url.pathname.startsWith('/plugins/')) return;
	if (/^\/[^/]+\.json$/.test(url.pathname)) return;

	// страховка: dev/vite-модулі завжди з мережі
	if (
		url.pathname.startsWith('/@vite') ||
		url.pathname.startsWith('/@fs') ||
		url.pathname.startsWith('/@id') ||
		url.pathname.startsWith('/node_modules/') ||
		url.pathname.startsWith('/src/') ||
		url.searchParams.has('import')
	) {
		return;
	}

	// хешовані prod-ассети: незмінні → чистий кеш-первим
	const immutable =
		url.pathname.startsWith('/_app/immutable/') ||
		/\.(woff2?|webmanifest)$/.test(url.pathname);

	if (immutable) {
		event.respondWith(
			(async () => {
				// спершу кеш ПОТОЧНОЇ версії, потім старі (чанк старішої вкладки)
				const cur = await caches.open(VERSION);
				const hit = (await cur.match(req)) ?? (await caches.match(req));
				if (hit) return hit;
				const res = await fetch(req);
				if (storable(res) && !isHtml(res)) {
					const copy = res.clone();
					// waitUntil обов'язковий: respondWith уже розв'язано, SW може
					// вбити процес до завершення put — ассет назавжди не закешується
					event.waitUntil(cur.put(req, copy));
				}
				return res;
			})()
		);
		return;
	}

	// навігація та решта: SWR — миттєво з кешу ПОТОЧНОЇ версії, свіжість у фоні
	event.respondWith(
		(async () => {
			const cur = await caches.open(VERSION);
			const hit = await cur.match(req, { ignoreSearch: req.mode === 'navigate' });
			if (hit) {
				// «дзвінок серверу» за новою версією фронту; waitUntil не дає
				// браузеру вбити воркер до завершення ревалідації
				event.waitUntil(revalidate(req));
				return hit;
			}
			try {
				const res = await fetch(req);
				if (storable(res)) {
					const copy = res.clone();
					// HTML — під чистий pathname (без query): копій шелла
					// не плодиться на кожен /app?account=N
					const put =
						isHtml(res) && !url.pathname.startsWith('/_app/')
							? cur.put(new Request(url.pathname), copy)
							: cur.put(req, copy);
					event.waitUntil(put.then(() => trimRuntime(cur)));
				}
				return res;
			} catch {
				if (req.mode === 'navigate') {
					return (
						(await cur.match(SHELL_URL)) ??
						(await caches.match(SHELL_URL)) ??
						Response.error()
					);
				}
				return Response.error();
			}
		})()
	);
});
