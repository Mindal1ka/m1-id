/**
 * Рендер скріншотів ПК-версії (1920×1080 @2x) для лендінгу.
 *
 * Як це працює:
 *  1. Піднімаємо `vite preview` (прод-збірка build/) на порті 4199.
 *  2. Playwright відкриває /app, СЕАНС підробляється у localStorage,
 *     а КОЖЕН запит /api/** перехоплюється і віддає фейкові дані
 *     (правдоподібні, українською) — реальний бек не потрібен.
 *  3. Клікаємо вкладки як живий юзер, чекаємо дані, знімаємо кадри
 *     у static/landing-shots/*.jpg.
 *
 * Перерендерити після змін: `node tools/shots.mjs` (потребує prod-білд).
 *   --mobile  — лише мобільні кадри (390×844 @2x, префікс m-*, для лендінгу на телефоні)
 *   --all     — і ПК-, і мобільні кадри
 * Оновити дані: правте SHOT_DATA нижче — це ЄДИНЕ місце правди.
 */
import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const BUILD = join(ROOT, 'build');
const OUT = join(ROOT, 'static', 'landing-shots');
const PORT = 4199;
const W = 1920, H = 1080, SCALE = 2;
// мобільні кадри: розмір типового телефона; навігація — нижня панель
const MW = 390, MH = 844, MSCALE = 2;
const ARGS = process.argv.slice(2);
const DO_MOBILE = ARGS.includes('--mobile') || ARGS.includes('--all');
const DO_DESKTOP = !ARGS.includes('--mobile');

mkdirSync(OUT, { recursive: true });

// ---------- ЖИВІ ДАНІ з акаунта юзера (санація імен у _live_dump.py) ----------
// tools/live_schedule.json (mapi get-month type=week) + tools/live_hw.json
// (homework/list, усі статуси). Якщо файла нема — фолбек на синтетику нижче.

const mapiLesson = (l) => ({
	date: l.date, weekday: null, lesson_no: l.lesson, start: (l.started_at ?? '').slice(0, 5),
	end: (l.finished_at ?? '').slice(0, 5), subject: l.subject_name, theme: l.lesson_theme,
	teacher: l.teacher_name, room: l.room_name, mark: l.mark ?? null,
	attendance: l.attendance ?? null, was: l.was, was_type: l.was_type,
	mark_type: l.mark_type, homeworks: [], video: !!l.is_video_available,
	exam: Array.isArray(l.exam) ? l.exam.length > 0 : !!l.exam });

const HW_STATUS_LABEL = { 1: 'Виконано', 2: 'На перевірці', 3: 'До виконання', 5: 'Ретейк' };
const mapiHw = (h) => ({
	id: h.id, subject: h.name_spec, title: h.theme || h.name_spec || 'Без назви', teacher: h.fio_teach,
	assigned: (h.creation_time ?? '').slice(0, 10), due: (h.overdue_time ?? '').slice(0, 10),
	status: h._status ?? h.status,
	status_label: HW_STATUS_LABEL[h._status ?? h.status] ?? '',
	mark: h.homework_stud?.mark ?? null, attachment: !!h.file_path,
	answer: (h.homework_stud?.status ?? 6) === 1,
	is_test: false, is_retake: (h._status ?? h.status) === 5,
	overdue_days: 0, late_penalty: 0 });

let LIVE_SCHEDULE = null, LIVE_HW = null;
try {
	LIVE_SCHEDULE = JSON.parse(readFileSync(join(ROOT, 'tools', 'live_schedule.json'), 'utf8'));
	console.log(`[shots] живий розклад: ${LIVE_SCHEDULE.data.length} уроків ✔`);
} catch { console.warn('[shots] live_schedule.json нема — синтетичний розклад'); }
try {
	LIVE_HW = JSON.parse(readFileSync(join(ROOT, 'tools', 'live_hw.json'), 'utf8'));
	console.log(`[shots] жива домашка: ${LIVE_HW.length} робіт ✔`);
} catch { console.warn('[shots] live_hw.json нема — синтетична домашка'); }

/* ==================== ПІДРОБЛЕНІ ДАНІ ==================== */
// Імена — ЛИШЕ плейсхолдери. Предмети/теми — з живого дампу юзера.

const T1 = 'Викладач 1';
const T2 = 'Викладач 2';
const T3 = 'Викладач 3';
const STUDENT = 'Імʼя Прізвище';

// Пн–Пт: предмети/теми як у юзера (IT-академія), оцінки вигадані
const SUBJECTS = [
	['Розробка додатків на Python', 'Tkinter: вікна та віджети'],
	['AI-геймплей', 'Реалізація руху гравця'],
	['Розробка додатків на Python', 'Класи та обʼєкти'],
	['AI-геймплей', 'Реалізація першого рівня'],
	['Розробка додатків на C#', 'Масиви та колекції'],
	['AI-геймплей', 'Хакатон: підготовка'],
	['Розробка додатків на Python', 'Робота з файлами'],
	['AI-геймплей', 'Анімації та ефекти'],
	['Розробка додатків на C#', 'LINQ запити'],
	['UX/UI дизайн', 'Прототипування в Figma']
];

// Дні тижня від «сьогодні» — щоб скрін не виглядав застиглим.
const D = (off) => {
	const d = new Date();
	d.setDate(d.getDate() + off);
	return d.toISOString().slice(0, 10);
};
const tomorrow = D(1), today = D(0);

const OK = (data) => ({ status: 200, contentType: 'application/json',
	body: JSON.stringify({ ok: true, data, meta: null, error: null }) });

const USER = {
	id: 1, username: 'student', email: 'student@m1id.xyz',
	created_at: '2025-09-01T08:00:00Z', email_verified: true };

const ACCOUNT = {
	id: 1, label: 'Основний', branch_alias: 'm1-school',
	logbook_id: 'LB-00001', id_user_storage: 'US-00001',
	fio: STUDENT, login: 'student', photo_url: '',
	status: 'active', language: 'uk', last_synced_at: new Date().toISOString(),
	sync_status: 'done' };

const lesson = (no, start, end, subject, theme, mark = null, room = '201 ауд.', si = 0) => ({
	date: today, weekday: null, lesson_no: no, start, end, subject, theme,
	teacher: [T1, T2, T3][si % 3], room, mark, attendance: null, was: null,
	was_type: null, mark_type: null, homeworks: [], video: false, exam: false });

// розклад Пн–Пт: 2 пари на день, як у юзера (15:20 / 16:50 формат 80 хв)
const WEEK_PLAN = [
	[0, 6, [['Розробка додатків на Python', 'Tkinter: вікна та віджети', 11], ['AI-геймплей', 'Реалізація руху гравця', 10]]],
	[1, 6, [['Розробка додатків на Python', 'Класи та обʼєкти', 12], ['AI-геймплей', 'Реалізація першого рівня', 11]]],
	[2, 6, [['Розробка додатків на C#', 'Масиви та колекції', null], ['AI-геймплей', 'Анімації та ефекти', 12]]],
	[3, 6, [['Розробка додатків на C#', 'LINQ запити', 10], ['UX/UI дизайн', 'Прототипування в Figma', null]]],
	[4, 6, [['Розробка додатків на Python', 'Робота з файлами', 11], ['AI-геймплей', 'Хакатон: підготовка', null]]]
];

const TODAY_LESSONS = WEEK_PLAN.map(([off, , ls], di) =>
	ls.map(([s, t, m], i) => lesson(i + 1, ['15:20', '16:50'][i], ['16:40', '18:10'][i],
		s, t, m, '201 ауд.', di + i)))[new Date().getDay() === 0 || new Date().getDay() === 6
	? 0 : new Date().getDay() - 1];

const weekDay = (off, wd, planIdx) => {
	const plan = WEEK_PLAN[planIdx % WEEK_PLAN.length][2];
	const ls = plan.map(([s, t, m], i) => ({
		...lesson(i + 1, ['15:20', '16:50'][i], ['16:40', '18:10'][i], s, t,
			m, '201 ауд.', planIdx + i), date: D(off) }));
	return { date: D(off), weekday: wd, lessons: ls };
};

const SCHEDULE_WEEK = {
	kind: 'week',
	range: { start: D(0), end: D(4) },
	days: [
		weekDay(0, 'Пн', 0), weekDay(1, 'Вт', 1), weekDay(2, 'Ср', 2),
		weekDay(3, 'Чт', 3), weekDay(4, 'Пт', 4),
		{ date: D(5), weekday: 'Сб', lessons: [] }, { date: D(6), weekday: 'Нд', lessons: [] }
	],
	total_lessons: 10
};

const hw = (id, subject, title, due, status, mark = null, overdue = 0) => ({
	id, subject, title, teacher: T1, assigned: D(-2),
	due, status, status_label: ['Виконано', 'На перевірці', 'До виконання', '', 'Ретейк'][status - 1] ?? '',
	mark, attachment: true, answer: status === 1, is_test: false, is_retake: status === 5,
	overdue_days: overdue, late_penalty: 0 });

const HW_ITEMS = [
	hw(101, 'Розробка додатків на Python', 'Tkinter: вікна та віджети', tomorrow, 3),
	hw(102, 'AI-геймплей', 'Реалізація руху гравця', D(-1), 3, null, 1),
	hw(103, 'Розробка додатків на C#', 'Масиви та колекції', D(2), 3),
	hw(104, 'AI-геймплей', 'Реалізація першого рівня', D(3), 3),
	hw(105, 'Розробка додатків на C#', 'LINQ запити', D(-1), 2),
	hw(106, 'UX/UI дизайн', 'Прототипування в Figma', D(-1), 2),
	hw(107, 'Розробка додатків на Python', 'Робота з файлами', D(-4), 1, 11),
	hw(108, 'AI-геймплей', 'Анімації та ефекти', D(-5), 1, 12),
	hw(109, 'Розробка додатків на Python', 'Класи та обʼєкти', D(-6), 1, 10)
];
// бек віддає сортованим за найближчим дедлайном — мок має відповідати
const byDue = (a, b) => {
	const da = a.due || '9999-12-31', db = b.due || '9999-12-31';
	return da < db ? -1 : da > db ? 1 : 0;
};
HW_ITEMS.sort(byDue);

const MARK_RECENT = (d, m, s, t, tw = 5) => ({ date: d, mark: m, subject: s, theme: t, teacher: T1, photo: null, comment: null, type_work: tw });

const MARKS = {
	overall_avg: 10.8, total_marks: 214,
	subjects: [
		{ subject: 'Розробка додатків на Python', avg: 11.2, count: 24, best: 12, worst: 9 },
		{ subject: 'AI-геймплей', avg: 10.4, count: 21, best: 12, worst: 8 },
		{ subject: 'Розробка додатків на C#', avg: 10.9, count: 18, best: 12, worst: 9 },
		{ subject: 'UX/UI дизайн', avg: 11.1, count: 12, best: 12, worst: 10 }
	],
	recent: [
		MARK_RECENT(today, 12, 'Розробка додатків на Python', 'Tkinter: практична', 5),
		MARK_RECENT(today, 11, 'AI-геймплей', 'Реалізація руху гравця', 5),
		MARK_RECENT(D(-1), 10, 'Розробка додатків на C#', 'Масиви та колекції', 0),
		MARK_RECENT(D(-2), 11, 'AI-геймплей', 'Анімації', 3),
		MARK_RECENT(D(-3), 9, 'UX/UI дизайн', 'Макет головного екрану', 6),
		MARK_RECENT(D(-4), 11, 'Розробка додатків на Python', 'Робота з файлами', 1),
		MARK_RECENT(D(-5), 10, 'AI-геймплей', 'Тематична', 7)
	],
	items: []
};
MARKS.items = MARKS.recent;

const WD_UK = ['Нд', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];

// ---------- оверрайд живими даними ----------
if (LIVE_SCHEDULE) {
	const byDate = new Map();
	for (const l of LIVE_SCHEDULE.data) {
		const key = l.date;
		if (!byDate.has(key)) byDate.set(key, []);
		byDate.get(key).push(mapiLesson(l));
	}
	const days = [...byDate.entries()]
		.sort(([a], [b]) => (a < b ? -1 : 1))
		.map(([d, lessons]) => ({
			date: d, weekday: WD_UK[new Date(d).getDay()], lessons }));
	SCHEDULE_WEEK.days = days;
	SCHEDULE_WEEK.range = { start: LIVE_SCHEDULE.start_day, end: LIVE_SCHEDULE.end_date };
	SCHEDULE_WEEK.total_lessons = days.reduce((n, d) => n + d.lessons.length, 0);
	TODAY_LESSONS.length = 0;
	TODAY_LESSONS.push(...(byDate.get(today) ?? []));
}
if (LIVE_HW) {
	HW_ITEMS.length = 0;
	HW_ITEMS.push(...LIVE_HW.map(mapiHw).sort(byDue));
}

// ---------- оцінки / нарахування / лідерборд / баланси (живі) ----------
try {
	const raw = JSON.parse(readFileSync(join(ROOT, 'tools', 'live_marks.json'), 'utf8'));
	const items = raw.map((m) => ({
		date: (m.mark_date ?? '').slice(0, 10), mark: Number(m.mark), subject: m.name_spec,
		theme: m.theme, teacher: m.fio_teach, photo: null, comment: m.comment ?? null,
		type_work: m.type_work ?? null }))
		.sort((a, b) => (a.date < b.date ? -1 : 1));
	const avg = items.reduce((s, i) => s + i.mark, 0) / (items.length || 1);
	const subj = new Map();
	for (const i of items) {
		if (!subj.has(i.subject)) subj.set(i.subject, []);
		subj.get(i.subject).push(i.mark);
	}
	MARKS.overall_avg = Math.round(avg * 10) / 10;
	MARKS.total_marks = items.length;
	MARKS.subjects = [...subj.entries()].map(([subject, ms]) => ({
		subject, avg: Math.round((ms.reduce((s, v) => s + v, 0) / ms.length) * 100) / 100,
		count: ms.length, best: Math.max(...ms), worst: Math.min(...ms) }));
	MARKS.recent = items.slice(-10).reverse();
	MARKS.items = items;
	console.log(`[shots] живі оцінки: ${items.length}, середній ${MARKS.overall_avg} ✔`);
} catch (e) { console.warn('[shots] live_marks.json:', e.message.split('\n')[0]); }

// лічильники статусів — з живого списку
const hwCount = (st) => HW_ITEMS.filter((h) => h.status === st).length;

const DASHBOARD = {
	user: { fio: STUDENT, photo_url: '', branch_alias: 'm1-school',
		logbook_id: ACCOUNT.logbook_id, id_user_storage: ACCOUNT.id_user_storage,
		lang: 'uk', group_name: 'Група П-24' },
	balances: { items: [
		{ key: 'cristals', icon: 'cristals', value: 1240, rating: 3 },
		{ key: 'coins', icon: 'coins', value: 8720, rating: 12 },
		{ key: 'beavers', icon: 'beavers', value: 46, rating: null }
	], unread_counters: { news: 2 } },
	homework_counts: { pending: hwCount(3), checking: hwCount(2), done: hwCount(1) },
	nearest_deadlines: HW_ITEMS.filter((h) => h.status === 3).slice(0, 4),
	today_lessons: TODAY_LESSONS,
	week_lessons_total: 28,
	marks_summary: { overall_avg: 10.8, recent: MARKS.recent.slice(0, 5) },
	meta: {}
};

// ЖИВІ баланси (mapi gaming/get-balances): cristals/coins/beavers як є
try {
	const bal = JSON.parse(readFileSync(join(ROOT, 'tools', 'live_balances.json'), 'utf8'));
	const byAlias = new Map(bal.map((b) => [b.alias, b]));
	DASHBOARD.balances.items = ['cristals', 'coins', 'beavers']
		.filter((k) => byAlias.has(k))
		.map((k) => ({ key: k, icon: k, value: byAlias.get(k).value,
			rating: byAlias.get(k).rating ?? null }));
	console.log('[shots] живі баланси:', DASHBOARD.balances.items.map((b) => `${b.key}=${b.value}`).join(' '));
	DASHBOARD.marks_summary.overall_avg = MARKS.overall_avg;
	DASHBOARD.marks_summary.recent = MARKS.recent.slice(0, 5);
} catch (e) { console.warn('[shots] live_balances.json:', e.message.split('\n')[0]); }

const SHOP = {
	products: [
		{ id: 1, title: 'Кристал ×10', text: 'Пачка з десятьма кристалами', image: null, quantity: 10,
			price: '120', min_price: '100', currency: 'coins',
			prices: [{ price: '120', min_price: '100', currency: 'coins' }], properties: [] },
		{ id: 2, title: 'Тема оформлення «Аврора»', text: 'Ексклюзивна тема для профілю', image: null, quantity: 1,
			price: '350', min_price: '300', currency: 'coins',
			prices: [{ price: '350', min_price: '300', currency: 'coins' }], properties: [] },
		{ id: 3, title: 'Аватар-рамка «Золото»', text: 'Рамка профілю на 30 днів', image: null, quantity: 1,
			price: '25', min_price: '20', currency: 'cristals',
			prices: [{ price: '25', min_price: '20', currency: 'cristals' }], properties: [] }
	],
	orders: [
		{ id: 9, uuid: 'u-9', status: 1, status_label: 'Виконується', cancelled: false, archived: false,
			created_at: new Date().toISOString(), can_discard: true,
			items: [{ product_id: 1, title: 'Кристал ×10', quantity: 1, image: null, price: 120, currency: 'coins' }],
			total: 120, currency: 'coins', totals: [{ price: 120, currency: 'coins' }] },
		{ id: 8, uuid: 'u-8', status: 2, status_label: 'Виконано', cancelled: false, archived: true,
			created_at: D(-3), can_discard: false,
			items: [{ product_id: 3, title: 'Аватар-рамка «Золото»', quantity: 1, image: null, price: 25, currency: 'cristals' }],
			total: 25, currency: 'cristals', totals: [{ price: 25, currency: 'cristals' }] }
	]
};

// НУТРИШН — НЕ фейковий: реальне меню foodstep.online (дамп:
// backend + python ../frontend/tools/_fs_dump.py → fs_menu_real.json)
let FS_MENU = null;
try {
	FS_MENU = JSON.parse(readFileSync(join(ROOT, 'tools', 'fs_menu_real.json'), 'utf8'));
	// фото страв — відносні шляхи ('/...') → абсолютизуємо до foodstep.online
	for (const d of FS_MENU.dishes) {
		if (d.image && d.image.startsWith('/')) d.image = `https://foodstep.online${d.image}`;
	}
	console.log(`[shots] реальне меню FoodStep: ${FS_MENU.dishes.length} страв ✔`);
} catch {
	FS_MENU = { supplier: 'dumpling', supplier_title: 'FoodStep', categories: [], dishes: [] };
	console.warn('[shots] fs_menu_real.json не знайдено — порожнє меню (запусти _fs_dump.py)');
}

const FS_CONFIG = {
	supplier: 'foodstep', password_set: true,
	auto: { enabled: true, mode: 'random', fixed_variation_id: null,
		order_time: '08:00', notify_minutes: 120, allow_weekends: false, skip_dates: [] },
	variations: [
		{ id: 1, name: 'Стандарт', supplier: 'foodstep', items: [{ id: 4, count: 1 }, { id: 7, count: 1 }] },
		{ id: 2, name: 'Лайт', supplier: 'foodstep', items: [{ id: 6, count: 1 }, { id: 8, count: 1 }] }
	]
};

const AWARDS = {
	beavers: 46,
	categories: [
		{ key: 'frames', items: [
			{ id: 1, img: '', price: 25, currency: 'cristals', purchased: true, equipped: true, free: false },
			{ id: 2, img: '', price: 40, currency: 'cristals', purchased: false, equipped: false, free: false } ] },
		{ key: 'themes', items: [
			{ id: 3, img: '', price: 0, currency: 'coins', purchased: true, equipped: false, free: true },
			{ id: 4, img: '', price: 350, currency: 'coins', purchased: false, equipped: false, free: false } ] }
	]
};

const L = (fio, amount, pos) => ({ id: null, fio, photo: null, amount, position: pos, is_new: false });
const LB_STUDENTS = Array.from({ length: 10 }, (_, i) =>
	L(`Учень ${i + 1}`, 5310 - i * 145, i + 1));
const LEADERBOARD = {
	points: { total: 4820, position: 4, week_diff: 2, month_diff: 5 },
	sliding_rating: true, branch: 'school',
	scopes: [{ key: 'group', label: 'Група', periods: [{ key: 'month', label: 'Місяць' }, { key: 'semester', label: 'Семестр' }] }],
	sections: { group: { month: {
		top: LB_STUDENTS.slice(0, 3),
		nearby: LB_STUDENTS.slice(3),
		new_students: [] } } }
};

const PROGRESS = {
	charts: [
		{ chart_type: 1, average: 10.8, prev_average: 10.2,
			points: [ 'Січень','Лютий','Березень','Квітень','Травень','Вересень' ]
				.map((m, i) => ({ month: m, points: [9.8, 10.4, 10.1, 11.0, 10.6, 10.8][i], prev: [9.5, 9.9, 10.2, 10.4, 10.5, 10.2][i] })) }
	],
	total_average: 10.8, prev_total_average: 10.2
};

const PAYMENTS = {
	full_name: ACCOUNT.fio, one_c_code: '10293', online_link: '', instruction_link: '',
	student_cost: 4800, debtor_status: 0, debt_amount: 0, next_date: D(9),
	next_critical: null,
	history: [
		{ date: D(-21), amount: 4800, currency: 'UAH', description: 'Плата за навчання' },
		{ date: D(-52), amount: 4800, currency: 'UAH', description: 'Плата за навчання' },
		{ date: D(-83), amount: 5200, currency: 'UAH', description: 'Плата за навчання + гурток' }
	],
	schedule: null
};

const NEWS = {
	unread: 2,
	items: [
		{ id: 1, title: 'День знань: розклад урочистої лінії', preview: 'Запрошуємо учнів та батьків...', image: null, is_viewed: false, published_at: D(-1), author: 'Адміністрація', mark: null },
		{ id: 2, title: 'Олімпіада з інформатики — реєстрація відкрита', preview: 'Реєстрація до 15 жовтня...', image: null, is_viewed: false, published_at: D(-3), author: 'Кафедра ІТ', mark: null }
	]
};

const ACTIVITY = {
	items: [
		{ id: 1, date: today, title: 'Отримано оцінку 12', subtitle: 'Розробка додатків на Python · Tkinter', mark: 12, icon: null, awards: [{ alias: 'cristals', value: 2 }] },
		{ id: 2, date: today, title: 'Домашку перевірено', subtitle: 'Розробка додатків на Python · Робота з файлами', mark: 11, icon: null, awards: [{ alias: 'coins', value: 15 }] },
		{ id: 3, date: D(-1), title: 'Отримано оцінку 10', subtitle: 'AI-геймплей · Анімації', mark: 10, icon: null, awards: [] }
	],
	page: 1, per_page: 20, total_pages: 1, total_count: 3, has_more: false };

// ЖИВІ нарахування (progress/activity)
try {
	const raw = JSON.parse(readFileSync(join(ROOT, 'tools', 'live_activity.json'), 'utf8'));
	const items = raw.map((a) => ({
		id: a.id, date: (a.created_at ?? '').slice(0, 10),
		title: a.name ?? 'Нарахування', subtitle: a.lesson_name ?? '',
		mark: a.mark ?? null, icon: a.icon ?? null,
		awards: (a.awards ?? []).map((w) => ({ alias: w.award_alias, value: w.award_value })) }));
	ACTIVITY.items = items;
	ACTIVITY.total_count = items.length;
	ACTIVITY.total_pages = 1; ACTIVITY.page = 1; ACTIVITY.has_more = false;
	console.log(`[shots] живі нарахування: ${items.length} ✔`);
} catch (e) { console.warn('[shots] live_activity.json:', e.message.split('\n')[0]); }

// ЖИВИЙ лідерборд (leader-points + leader-table), власник — перший
try {
	const raw = JSON.parse(readFileSync(join(ROOT, 'tools', 'live_leader.json'), 'utf8'));
	const PERIOD_LABEL = { month: 'Місяць', semester: 'Семестр', year: 'Рік', all_time: 'Весь час' };
	const row = (r) => ({ id: r.id_stud, fio: r.fio_stud, photo: null,
		amount: r.amount, position: r.position, is_new: !!r.is_new });
	const scopes = raw.table ?? {};
	const sections = {};
	const scopeMetas = [];
	for (const [scope, periods] of Object.entries(scopes)) {
		if (!periods || typeof periods !== 'object') continue;
		const periodMetas = [];
		sections[scope] = {};
		for (const [period, blocks] of Object.entries(periods)) {
			if (!blocks || typeof blocks !== 'object' || !blocks.top) continue;
			periodMetas.push({ key: period, label: PERIOD_LABEL[period] ?? period });
			const all = [
				...(blocks.top ?? []), ...(blocks.other ?? []),
				...(blocks.nearby ?? []), ...(blocks.new_students ?? [])];
			// власник скріна — НА ПЕРШОМУ МІСЦІ, решта щільно за ним
			const me = all.find((r) => r._me) ?? all[0];
			const rest = all.filter((r) => r !== me);
			// власник #1: очки — максимум списку
			me.amount = Math.max(...all.map((r) => r.amount ?? 0)) + 15;
			me.position = 1;
			rest.forEach((r, i) => { r.position = i + 2; });
			sections[scope][period] = {
				top: [me, ...rest.slice(0, 2)].map(row),
				nearby: rest.slice(2, 10).map(row),
				new_students: (blocks.new_students ?? []).map(row) };
		}
		if (periodMetas.length) scopeMetas.push({ key: scope, label: scope === 'group' ? 'Група' : scope === 'stream' ? 'Потік' : scope, periods: periodMetas });
	}
	LEADERBOARD.scopes = scopeMetas;
	LEADERBOARD.sections = sections;
	const pts = raw.points ?? {};
	LEADERBOARD.points = Object.fromEntries(Object.entries(pts).map(([scope, p]) =>
		[scope, { total: null, position: p.studentPosition,
			week_diff: p.weekDiff, month_diff: p.monthDiff }]));
	console.log(`[shots] живий лідерборд: ${scopeMetas.map(s => s.key).join('/')} ✔`);
} catch (e) { console.warn('[shots] live_leader.json:', e.message.split('\n')[0]); }

const TG_STATUS = { linked: true, bot_configured: true, bot_running: true,
	bot_username: 'm1id_bot', deep_link: null, qr_data_uri: null,
	site_url: 'https://m1id.xyz', linked_at: D(-30), accounts: [] };
const EXTRAS = { available: true, accounts: [] };

/** Головна мапа: URL-ключ → тіло. Порядок = пріоритет. */
// Кастомна розкладка віджетів користувача (tools/layouts.json, дамп з
// widget_layouts прода) — якщо є, рендеримо скрини з НЕЮ, а не з дефолту.
let LAYOUTS = { layouts: {}, updated_at: null };
try {
	const { readFileSync } = await import('node:fs');
	const raw = readFileSync(join(ROOT, 'tools', 'layouts.json'), 'utf8');
	const parsed = JSON.parse(raw);
	const arr = Array.isArray(parsed) ? parsed : [parsed];
	const merged = {};
	for (const row of arr) {
		if (!row) continue;
		let ly = row.layout ?? row.layouts ?? {};
		if (typeof ly === 'string') { try { ly = JSON.parse(ly); } catch { ly = {}; } }
		Object.assign(merged, ly);
	}
	LAYOUTS = { layouts: merged, updated_at: arr[0]?.updated_at ?? null };
	console.log('[shots] кастомна розкладка віджетів: tools/layouts.json ✔');
} catch { /* нема файла — рендеримо дефолт */ }

const ROUTES = [
	[/\/api\/auth\/me$/, USER],
	[/\/api\/auth\/sessions/, []],
	[/\/api\/accounts$/, [ACCOUNT]],
	[/\/api\/accounts\/\d+\/sync\/status$/, { status: 'done', steps: [], progress: { done: 1, total: 1 } }],
	[/\/api\/accounts\/\d+\/snapshots$/, []],
	[/\/api\/app\/dashboard/, DASHBOARD],
	[/\/api\/app\/homework$/, { items: HW_ITEMS, counts: { pending: hwCount(3), checking: hwCount(2), done: hwCount(1) }, subjects: [...new Set(HW_ITEMS.map((h) => h.subject))], total: HW_ITEMS.length, nearest_deadlines: HW_ITEMS.filter((h) => h.status === 3).slice(0, 4) }],
	[/\/api\/app\/homework\/\d+$/, { id: 101, subject: 'Розробка додатків на Python', title: 'Tkinter: вікна та віджети', teacher: T1, teach_photo: null, status: 3, status_label: 'До виконання', assigned: D(-2), due: tomorrow, completed: null, description: 'Створити вікно за макетом: панель інструментів, список віджетів, обробники подій.', attachment: null, mark: null, answer_text: '', answer_files: [], submitted_at: null, coins: null, is_test: false, autotest_status: null, autotest_result: null, teacher_comment: '', history: [], submission_id: null }],
	[/\/api\/app\/schedule/, SCHEDULE_WEEK],
	[/\/api\/app\/marks/, MARKS],
	[/\/api\/app\/activity/, ACTIVITY],
	[/\/api\/app\/news$/, NEWS],
	[/\/api\/app\/news\/\d+$/, { ...NEWS.items[0], text: NEWS.items[0].preview }],
	[/\/api\/app\/shop/, SHOP],
	[/\/api\/app\/payments/, PAYMENTS],
	[/\/api\/app\/clubs/, { clubs: [], abonements: [], balance: 0, transactions: [] }],
	[/\/api\/app\/contacts/, {}],
	[/\/api\/app\/awards/, AWARDS],
	[/\/api\/app\/progress/, PROGRESS],
	[/\/api\/app\/leaderboard/, LEADERBOARD],
	[/\/api\/app\/qr$/, { qr: 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="40" height="40"%3E%3Crect width="40" height="40" fill="%23111"/%3E%3C/svg%3E' }],
	[/\/api\/nutrition\/menu/, FS_MENU],
	[/\/api\/nutrition\/config$/, FS_CONFIG],
	[/\/api\/nutrition\/orders/, { orders: [] }],
	[/\/api\/nutrition\/calendar/, { ordered: {}, cancelled: {} }],
	[/\/api\/telegram\/status/, TG_STATUS],
	[/\/api\/telegram\/settings/, { homework_new: true, deadlines: true }],
	[/\/api\/extras\/status/, EXTRAS],
	[/\/api\/widgets\/layouts/, LAYOUTS],
	[/\/api\/plugins$/, []],
	[/\/api\/system\/spec\/stats/, { openapi: '', title: 'M1 ID', version: '1.0', paths: 0, operations: 0, schemas: 0, tags: 0, by_tag: {}, loaded_from: null }]
];

/* ==================== РЕНДЕР ==================== */

const server = createServer(async (req, res) => {
	try {
		let p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
		if (p.endsWith('/')) p += 'index.html';
		const fp = join(BUILD, p);
		let st = await stat(fp).catch(() => null);
		if (!st || st.isDirectory()) {
			// SPA-фолбек: /app → app.html (лендінг у index.html — не чіпати),
			// /version.json → заглушка
			if (p === '/version.json') {
				res.writeHead(200, { 'Content-Type': 'application/json' });
				return res.end('{"v":"shot"}');
			}
			if (p === '/sw.js') {
				res.writeHead(200, { 'Content-Type': 'text/javascript' });
				return res.end('');
			}
			p = '/app.html';
		}
		const buf = await readFile(join(BUILD, p));
		const ext = p.split('.').pop() ?? '';
		const mime = { html: 'text/html', js: 'text/javascript', css: 'text/css',
			jpg: 'image/jpeg', png: 'image/png', svg: 'image/svg+xml',
			json: 'application/json', woff2: 'font/woff2', woff: 'font/woff' }[ext]
			?? 'application/octet-stream';
		res.writeHead(200, { 'Content-Type': mime });
		res.end(buf);
	} catch (e) {
		res.writeHead(500); res.end(String(e));
	}
});
server.listen(PORT);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitServer() {
	for (let i = 0; i < 60; i++) {
		try {
			const r = await fetch(`http://localhost:${PORT}/index.html`);
			if (r.ok) return;
		} catch { /* ще не піднявся */ }
		await sleep(500);
	}
	throw new Error('статик-сервер не піднявся');
}

/** Один прохід зйомки: ПК (бічне меню) або телефон (нижня панель). */
async function pass(browser, { vw, vh, scale, mobile }) {
	const ctx = await browser.newContext({
		viewport: { width: vw, height: vh },
		deviceScaleFactor: scale,
		isMobile: mobile,
		hasTouch: mobile,
		locale: 'uk-UA',
		reducedMotion: 'reduce'
	});

	// Сеанс підробляється ДО будь-якого скрипту сторінки
	await ctx.addInitScript(([acc]) => {
		localStorage.setItem('m1id.session.v1', JSON.stringify({
			user: { id: 1, username: 'student', email: 'student@m1id.xyz', created_at: null, email_verified: true },
			access: 'fake.access.token', refresh: 'fake.refresh.token' }));
		localStorage.setItem('m1id.lastAccount', String(acc));
	}, [1]);

	// Перехоплення ВСІХ /api/** — дані з ROUTES
	await ctx.route('**/api/**', (route) => {
		const url = new URL(route.request().url());
		// фото їжі — прозорий проксі на foodstep.online (фронт ходить
		// через /api/nutrition/img?src=… — без цього кадри без фото)
		if (url.pathname === '/api/nutrition/img') {
			const src = url.searchParams.get('src') ?? '';
			const abs = src.startsWith('http') ? src
				: `https://foodstep.online${src.startsWith('/') ? '' : '/'}${src}`;
			return (async () => {
				try {
					const imgRes = await fetch(abs, { headers: {
						'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' } });
					if (!imgRes.ok) throw new Error(String(imgRes.status));
					const body = Buffer.from(await imgRes.arrayBuffer());
					return route.fulfill({ status: 200,
						contentType: imgRes.headers.get('content-type') ?? 'image/jpeg',
						body });
				} catch (e) {
					console.warn(`[shots] img ${src}: ${e.message}`);
					return route.fulfill({ status: 404, body: '' });
				}
			})();
		}
		for (const [re, data] of ROUTES) {
			if (re.test(url.pathname)) {
				if (route.request().method() !== 'GET') {
					return route.fulfill(OK(typeof data === 'object' ? data : {}));
				}
				return route.fulfill(OK(data));
			}
		}
		// невідомий GET: порожній конверт без даних (компоненти мають толерувати null)
		return route.fulfill(OK(null));
	});
	// version.json: той самий штамп, що у бандлі → модалку оновлення не показуємо
	await ctx.route('**/version.json', (route) => route.fulfill({
		status: 200, contentType: 'application/json', body: '{"v":"shot"}' }));
	// Сервіс-воркер у прев'ю не потрібен
	await ctx.route('**/sw.js', (route) => route.fulfill({ status: 200, contentType: 'text/javascript', body: '' }));

	const page = await ctx.newPage();
	const pre = mobile ? 'm-' : '';
	page.on('pageerror', (e) => console.warn('[shots] pageerror:', e.message.slice(0, 160)));

	await page.goto(`http://localhost:${PORT}/app?account=1`, { waitUntil: 'networkidle' });
	await page.waitForTimeout(1800);

	const shot = async (name) => {
		await page.waitForTimeout(700);
		await page.screenshot({ path: join(OUT, `${pre}${name}.jpg`), type: 'jpeg', quality: 88 });
		console.log(`[shots] ✔ ${pre}${name}.jpg`);
	};

	// Прибрати модалку оновлення/привітання, якщо з'явилась
	await page.keyboard.press('Escape').catch(() => {});

	await shot('01-home');

	const clickTab = async (label) => {
		// ПК — бічне меню; телефон — нижня панель
		const btn = page.locator(`${mobile ? '.bottombar' : '.side-nav'} button:has-text("${label}")`);
		await btn.first().click({ timeout: 5000 });
		await page.waitForLoadState('networkidle');
	};
	const tryTab = async (label, name) => {
		try { await clickTab(label); await shot(name); }
		catch (e) { console.warn(`[shots] ✖ ${name}: ${e.message.split('\n')[0]}`); }
	};

	// ЗНІМАЄМО ЛИШЕ ВИБРАНІ КАДРИ (для лендінгу на зараз):
	// home · homework (фільтр «До виконання») · nutrition · widget-editor.
	// Решта вкладок — вимкнено до окремого рішення (згідно з LANDING.md).
	await tryTab('Розклад', '02-schedule');
	await tryTab('Домашка', '03-homework');
	try {
		await page.locator('button:has-text("До виконання")').first()
			.click({ timeout: 5000 });
		await page.waitForTimeout(700);
		await page.screenshot({ path: join(OUT, `${pre}03-homework.jpg`), type: 'jpeg', quality: 88 });
		console.log(`[shots] ✔ ${pre}03-homework.jpg (фільтр «До виконання»)`);
	} catch (e) { console.warn(`[shots] ✖ hw filter: ${e.message.split('\n')[0]}`); }

	if (!mobile) await tryTab('Харчування', '06-nutrition');

	// Редактор віджетів: повертаємось на Головну і тиснемо кнопку «Віджети»
	try {
		await clickTab('Головна');
		await page.locator('button[aria-label="Віджети"]').click({ timeout: 5000 });
		await page.waitForTimeout(700);
		await page.screenshot({ path: join(OUT, `${pre}10-widget-editor.jpg`), type: 'jpeg', quality: 88 });
		console.log(`[shots] ✔ ${pre}10-widget-editor.jpg`);
		await page.keyboard.press('Escape').catch(() => {});
	} catch (e) { console.warn(`[shots] ✖ editor: ${e.message.split('\n')[0]}`); }
	await ctx.close();
}

try {
	await waitServer();
	console.log(`[shots] статик-сервер на http://localhost:${PORT}`);

	const browser = await chromium.launch();
	if (DO_DESKTOP) await pass(browser, { vw: W, vh: H, scale: SCALE, mobile: false });
	if (DO_MOBILE) await pass(browser, { vw: MW, vh: MH, scale: MSCALE, mobile: true });

	await browser.close();
	console.log('[shots] готово →', OUT);
} finally {
	try { server.close(); } catch { /* ignore */ }
}
