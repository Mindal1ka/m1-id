/* ═══════════════════════════════════════════════════════════════
   M1 ID · Консольні скрипти для розкладки віджетів Головної

   Використання: відкрити застосунок → F12 → Console → вставити скрипт.

   SCRIPT 1 (DUMP)  — показати й вивантажити поточну розкладку (JSON).
   SCRIPT 2 (RESTORE) — відновити розкладку з JSON.

   Розкладка живе в localStorage: ключ 'm1id.homeWidgets.v1',
   формат: [{ key, span (1-12 колонок), h (px, опційно) }, ...]
   Порядок масиву = порядок відображення в CSS-grid.
   Для серверної частини: зберігати JSON як є на користувача
   (users.id → home_widgets JSON), при логіні віддавати, при зміні — аплоадити.
   ═══════════════════════════════════════════════════════════════ */

/* ─────── SCRIPT 1 · DUMP (показати + скопіювати) ─────── */
(() => {
	const LS = 'm1id.homeWidgets.v1';
	const LABELS = {
		stats: 'Показники', deadlines: 'Дедлайни',
		lessons: 'Сьогодні', marks: 'Оцінки',
		activity: 'Нарахування', news: 'Новини', board: 'Лідери'
	};

	const raw = localStorage.getItem(LS);
	const stored = raw ? JSON.parse(raw) : [];
	const grid = document.querySelector('.grid');
	const items = grid ? [...grid.querySelectorAll(':scope > .w-item')] : [];

	const measured = items.map((el, i) => {
		const key = el.dataset.wkey;
		const cfg = stored.find((c) => c.key === key);
		const r = el.getBoundingClientRect();
		return {
			order: i + 1,
			key,
			label: LABELS[key] ?? key,
			span: cfg?.span ?? null,   // колонок із 12
			h_px: cfg?.h ?? null,      // фікс. висота (null = авто)
			rect: {                    // фактичне місце за поточної ширини
				x: Math.round(r.x), y: Math.round(r.y + scrollY),
				w: Math.round(r.width), h: Math.round(r.height)
			}
		};
	});

	const out = {
		app: 'M1 ID',
		lsKey: LS,
		savedAt: new Date().toISOString(),
		account: localStorage.getItem('m1id.lastAccount'),
		viewport: { w: innerWidth, h: innerHeight },
		layout: stored.map((c, i) => ({
			order: i + 1, key: c.key,
			label: LABELS[c.key] ?? c.key,
			span: c.span, h_px: c.h ?? null
		})),
		measured
	};

	console.log('%c M1 ID · розкладка віджетів ',
		'background:#6c7cff;color:#fff;padding:2px 8px;border-radius:4px;font-weight:700');
	console.table(out.layout);
	console.log('Фактичні позиції (px, за поточної ширини вікна):');
	console.table(measured.map((m) => ({
		order: m.order, key: m.key,
		x: m.rect.x, y: m.rect.y, w: m.rect.w, h: m.rect.h
	})));
	console.log('Повний JSON (для серверної частини):', out);
	window.__m1widgets = out;
	try {
		copy(JSON.stringify(out, null, 2));
		console.log('%c✓ JSON скопійовано в буфер обміну',
			'color:#7ee787;font-weight:700');
	} catch {
		console.warn('copy() недоступний — JSON вище, скопіюйте вручну');
	}
	return out;
})();

/* ─────── SCRIPT 2 · RESTORE (відновити з JSON) ───────
(() => {
	// Варіант А: JSON уже в буфері/змінній
	const src = window.__m1widgets;
	// Варіант Б: вставити рядок JSON вручну:
	// const src = JSON.parse(`{...}`);

	if (!src?.layout) { console.error('Немає JSON розкладки'); return; }
	const cfg = src.layout.map((l) => ({
		key: l.key, span: l.span, ...(l.h_px ? { h: l.h_px } : {})
	}));
	localStorage.setItem('m1id.homeWidgets.v1', JSON.stringify(cfg));
	console.log('✓ Розкладку відновлено:', cfg);
	location.reload();
})();
*/
