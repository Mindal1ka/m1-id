/** Місяці укр. (Січень…) — для підписів періодів. */
export const MONTHS_UK = [
	'Січень', 'Лютий', 'Березень', 'Квітень', 'Травень', 'Червень',
	'Липень', 'Серпень', 'Вересень', 'Жовтень', 'Листопад', 'Грудень'
];

/** Підписи секцій снапшотів для UI. */
export const SECTION_LABELS: Record<string, string> = {
	profile: 'Профіль',
	config: 'Налаштування філії',
	counters: 'Лічильники сторінок',
	balances: 'Баланси (кристали/монети)',
	schedule_month: 'Розклад — місяць',
	schedule_week: 'Розклад — тиждень',
	hw_pending: 'Домашка: до виконання',
	hw_checking: 'Домашка: на перевірці',
	hw_done: 'Домашка: виконано',
	hw_retake: 'Домашка: ретейк',
	stat_marks: 'Оцінки за місяць',
	stat_attendance: 'Відвідування',
	stat_progress: 'Прогрес',
	news: 'Новини',
	shop_products: 'Магазин: товари',
	shop_orders: 'Магазин: замовлення',
	awards_items: 'Нагороди: предмети',
	awards_balance: 'Нагороди: баланс'
};

export function sectionLabel(section: string): string {
	return SECTION_LABELS[section] ?? section;
}

/** Ініціали для аватара без фото. */
export function initials(fio: string): string {
	return fio
		.split(/\s+/)
		.filter(Boolean)
		.slice(0, 2)
		.map((p) => p[0]?.toUpperCase() ?? '')
		.join('');
}
