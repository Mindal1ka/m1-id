/** Headless-перевірка кліків/скролу кошика «Харчування» (портал + slide).
 *  Запуск: node tests/nutrition-check.mjs  (спершу npm run build) */
import { chromium } from 'playwright';
import { createServer } from 'node:http';

// міні-статик-сервер для build/
const ROOT = new URL('../build/', import.meta.url).pathname
	.split('/').map((s) => decodeURIComponent(s)).join('/')
	.replace(/^\/([A-Za-z]:)/, '$1');
const srv = createServer((req, res) => {
	(async () => {
		const fs = await import('node:fs');
		const path = await import('node:path');
		let p = decodeURIComponent(req.url.split('?')[0]);
		if (p.endsWith('/')) p += 'index.html';
		let file = path.join(ROOT, p);
		if (!fs.existsSync(file) || fs.statSync(file).isDirectory())
			file = path.join(ROOT, 'index.html'); // SPA fallback
		const data = fs.readFileSync(file);
		const ext = path.extname(file);
		res.writeHead(200, { 'content-type': ext === '.html' ? 'text/html'
			: ext === '.js' ? 'text/javascript' : ext === '.css' ? 'text/css'
			: ext === '.webp' ? 'image/webp' : 'application/octet-stream' });
		res.end(data);
	})();
});
await new Promise((r) => srv.listen(4599, r));

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });

// мок бекенда
await ctx.route('**/api/**', (route) => {
	const url = route.request().url();
	console.log('[mock]', route.request().method(), url);
	const ok = (data) => route.fulfill({
		contentType: 'application/json',
		body: JSON.stringify({ ok: true, data, meta: null, error: null })
	});
	if (url.includes('/api/app/dashboard')) return ok({
		user: { id: 1, fio: 'Тест' }, balances: { items: [], unread_counters: {} },
		homework_counts: {}, nearest_deadlines: [], today_lessons: [],
		week_lessons_total: 0, marks_summary: { overall_avg: null, recent: [] },
		meta: {}
	});
	if (url.includes('/api/app/homework')) return ok({
		items: [], counts: {}, subjects: [], total: 0, nearest_deadlines: []
	});
	if (url.includes('/api/app/schedule')) return ok({
		kind: 'week', range: {}, days: [], total_lessons: 0
	});
	if (url.includes('/api/app/marks')) return ok({
		overall_avg: null, total_marks: 0, subjects: [], recent: [], items: []
	});
	if (url.includes('/api/app/activity')) return ok({ items: [], total: 0 });
	if (url.includes('/api/nutrition/config')) return ok({
		supplier: 'dumpling', password_set: true,
		auto: { enabled: true, mode: 'random', fixed_variation_id: null,
			order_time: '08:00', notify_minutes: 60, allow_weekends: false, skip_dates: [] },
		variations: []
	});
	if (url.includes('/api/nutrition/menu')) return ok({
		supplier: 'dumpling', supplier_title: 'Полтавські Галушки',
		dishes: [
			{ id: 1, title: 'Суп', price: 62, weight: '300 гр', image: null },
			{ id: 2, title: 'Борщ', price: 62, weight: '300 гр', image: null }
		],
		categories: [
			{ name: 'Перші страви', dishes: [
				{ id: 1, title: 'Суп', price: 62, weight: '300 гр', image: null },
				{ id: 2, title: 'Борщ', price: 62, weight: '300 гр', image: null }
			] }
		]
	});
	if (url.includes('/api/nutrition/orders')) return ok({ orders: [] });
	if (url.includes('/api/nutrition/calendar')) return ok({ ordered: {} });
	if (url.includes('/api/accounts')) return ok([{
		id: 1, label: 'Тест', branch_alias: 'kyiv', logbook_id: '1',
		id_user_storage: '1', fio: 'Тест Тестовий', login: 'test',
		photo_url: '', status: 'ok', language: 'ua',
		last_synced_at: null, sync_status: 'ok'
	}]);
	if (url.includes('/api/widgets/layouts')) return ok({});
	return ok([]);
});

const page = await ctx.newPage({ viewport: { width: 1024, height: 539 } });
page.on('console', (m) => { if (m.type() === 'error') console.log('[console.error]', m.text()); });
page.on('pageerror', (e) => console.log('[pageerror]', e.message));
page.on('requestfailed', (r) => console.log('[reqfailed]', r.method(), r.url(), r.failure()?.errorText));

await page.goto('http://localhost:4599/app');
await page.evaluate(() => {
	localStorage.setItem('m1id.session.v1',
		JSON.stringify({ access: 'a'.repeat(20), refresh: 'b'.repeat(20) }));
});
await page.reload();
await page.waitForTimeout(2500);

await page.waitForTimeout(2500);
await page.screenshot({ path: 'tests/step0.png' });
const nutBtn = page.locator('button', { hasText: 'Харчування' }).first();
await nutBtn.click({ force: true, timeout: 5000 }).catch((e) => console.log('[tab click]', e.message));
await page.waitForTimeout(1200);

// клікаємо страву → зʼявляється кошик
await page.locator('.fs-card').first().click();
await page.waitForTimeout(600);
const bar = page.locator('.cartbar');
console.log('cartbar count:', await bar.count());
if (await bar.count()) {
	console.log('cartbar in body?', await bar.evaluate((el) => el.parentElement === document.body));
	console.log('cartbar rect:', JSON.stringify(await bar.evaluate((el) => {
		const r = el.getBoundingClientRect();
		return { x: r.x, y: r.y, w: r.width, h: r.height, docH: document.body.scrollHeight };
	})));
	// розгортаємо панель
	await page.locator('.cartbar-head').click();
	await page.waitForTimeout(800);
	// клікаємо дату в календарі
	const cell = page.locator('.fscal-cell:not(.past):not(.weekend):not(.empty)').first();
	console.log('cell count:', await page.locator('.fscal-cell').count());
	await cell.click();
	await page.waitForTimeout(400);
	const sel = await page.locator('.fscal-cell.sel').count();
	console.log('selected cells after click:', sel);
	// навігація місяців
	const label0 = await page.locator('.fscal-month').innerText();
	await page.locator('.fscal-nav').nth(1).click();
	await page.waitForTimeout(300);
	const label1 = await page.locator('.fscal-month').innerText();
	console.log('month nav:', JSON.stringify({ label0, label1 }));
	// клікаємо +/− у кошику
	const plus = page.locator('.cart-ctl button').nth(1);
	await plus.click();
	await page.waitForTimeout(300);
	console.log('badge after plus:', await page.locator('.fs-badge').innerText().catch(() => 'n/a'));
	// скрол panel
	const scrollable = await page.locator('.cartbar-body').evaluate((el) => {
		el.scrollTop = 500;
		return { scrollTop: el.scrollTop, scrollHeight: el.scrollHeight, clientHeight: el.clientHeight };
	});
	console.log('cartbar-body scroll:', JSON.stringify(scrollable));
	console.log('cartbar rect:', JSON.stringify(await bar.evaluate((el) => {
		const r = el.getBoundingClientRect();
		return { x: r.x, y: r.y, w: r.width, h: r.height, winH: innerHeight };
	})));
	// чи немає елемента над кошиком у точці кліку
	const topEl = await page.evaluate(() => {
		const cell2 = document.querySelector('.fscal-cell:not(.past):not(.weekend):not(.empty)');
		if (!cell2) return 'no cell';
		const r = cell2.getBoundingClientRect();
		const el = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
		return el ? el.className || el.tagName : 'none';
	});
	console.log('elementFromPoint over cell:', topEl);
	await page.screenshot({ path: 'tests/nutrition-shot.png' });
}
await browser.close();
srv.close();
process.exit(0);
