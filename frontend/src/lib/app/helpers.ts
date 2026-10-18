/**
 * Чисті хелпери сторінки /app (форматування, розклад, фід нарахувань).
 * Без стану й побічних ефектів: їх спільно використовують вигляди вкладок.
 */
import type { ScheduleView } from '$lib/api/client';
import { MONTHS_UK } from '$lib/sections';
import {
	BookOpen,
	CalendarDays,
	CircleCheck,
	Coins,
	Gem,
	Medal,
	ShoppingBag
} from '@lucide/svelte';

/** Вкладки застосунку (/app). */
export type Tab =
	| 'home'
	| 'schedule'
	| 'homework'
	| 'marks'
	| 'shop'
	| 'nutrition'
	| 'payments'
	| 'clubs'
	| 'contacts'
	| 'notes'
	| 'board'
	| 'awards'
	| 'progress'
	| 'activity'
	| 'data'
	| 'telegram'
	| 'extras'
	| 'plugins';

export type SchedDay = ScheduleView['days'][number];
export type SchedLesson = SchedDay['lessons'][number];

export const BALANCE_ICONS: Record<string, typeof Coins> = {
	cristals: Gem,
	coins: Coins,
	achivements: Medal
};

export const WD_UK = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Нд'];

const MARK_LABELS: Record<number, string> = {
	1: 'Оцінка за урок',
	2: 'Оцінка за екзамен',
	3: 'Оцінка за самостійну роботу',
	4: 'Оцінка за лекцію',
	5: 'Оцінка за практичну роботу',
	6: 'Оцінка за лабораторну роботу',
	7: 'Оцінка за контрольну роботу'
};

/** Понеділок тижня заданої дати (локальний час). */
export function mondayOf(d: Date): Date {
	const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
	const dow = x.getDay(); // 0=Нд
	x.setDate(x.getDate() - dow + (dow === 0 ? -6 : 1));
	return x;
}

/** CSS-клас за оцінкою: hi (10+), mid (7+), low. */
export function mkCls(m: number | string | null): string {
	const v = Number(m);
	if (!Number.isFinite(v)) return '';
	return v >= 10 ? 'hi' : v >= 7 ? 'mid' : 'low';
}

export function markLabel(l: SchedLesson): string {
	if (l.exam) return 'Оцінка за екзамен';
	return MARK_LABELS[l.mark_type ?? 0] ?? 'Оцінка';
}

export function wasLabel(l: SchedLesson): string {
	if (l.was_type === 2) return 'Відвідано онлайн';
	if (l.was_type === 1) return 'Відвідано офлайн';
	return 'Був на занятті';
}

/** Іконка події фіду за текстом/нагородами: видно ЗМІСТ події,
 *  а не однаковий блідий календарик для всіх підряд. */
export function feedIcon(it: {
	title?: string | null;
	subtitle?: string | null;
	awards?: { alias: string }[];
}): [typeof Coins, string] {
	const t = `${it.title ?? ''} ${it.subtitle ?? ''}`.toLowerCase();
	if (/дз|домашк|здав|здал|homework/.test(t)) return [CircleCheck, 'ok'];
	if (/магазин|оплат|сплат|pay|shop|refund|поверн|антистрес/.test(t))
		return [ShoppingBag, 'shop'];
	if (/досягн|achiev|медал|medal|бонус/.test(t)) return [Medal, 'ach'];
	if (/кристал|gem|алмаз|діам/.test(t)) return [Gem, 'gem'];
	if (/урок|занятт|lesson|пара|курс|модул/.test(t)) return [BookOpen, 'lesson'];
	const aw = it.awards?.[0]?.alias;
	if (aw === 'achivements') return [Medal, 'ach'];
	if (aw === 'cristals') return [Gem, 'gem'];
	if (aw === 'coins') return [Coins, 'coin'];
	return [CalendarDays, ''];
}

/** ПІБ викладача для показу: без приписки «School» (у викладачів часто
 *  два акаунти — звичайний і «… School»). Лише відображення: бекенд
 *  зберігає й віддає ім'я як є. */
export function cleanTeacher(name: string | null | undefined): string {
	const s = (name ?? '').trim();
	// «school» з урахуванням кириличних двійників (с, о, һ, ѕ, ӏ) і невидимих символів
	const SCH = '[sѕ][cс][hһ][oо][oо][lӏ1i]';
	const out = s
		.replace(/[​-‏⁠﻿]/g, '')
		// на початку: «School Горбенко Ксенія» (так у живих даних MyStat)
		.replace(new RegExp(`^[([]?\\s*${SCH}\\s*[)\\]]?[\\s\\-–—_|·,:.]+`, 'i'), '')
		// у кінці: «Горбенко Ксенія School» / «… (School)»
		.replace(new RegExp(`[\\s\\-–—_|·,]+[([]?\\s*${SCH}\\s*[)\\]]?\\s*$`, 'i'), '')
		.trim();
	return out || s;
}

/** Місяці в родовому відмінку: «4 червня», а не «4 Червень». */
const MONTHS_GEN_UK = [
	'січня', 'лютого', 'березня', 'квітня', 'травня', 'червня',
	'липня', 'серпня', 'вересня', 'жовтня', 'листопада', 'грудня'
];

export function fmtDay(isoDate: string): string {
	const m = MONTHS_GEN_UK[Number(isoDate.slice(5, 7)) - 1] ?? '';
	return `${Number(isoDate.slice(8, 10))} ${m}`;
}

/** Людські назви правил нарахувань MyStat (поле name = `rule_name_*`).
 *  Лише підтверджені коди; невідомі — охайно з самого коду. */
const ACTIVITY_RULES: Record<string, string> = {
	refund_in_shop: 'Повернення коштів за замовлення в магазині',
	homework_mark: 'Оцінка за домашнє завдання'
};

export function activityLabel(raw: string | null | undefined): string {
	const s = (raw ?? '').trim();
	if (!s.startsWith('rule_name_')) return s;
	const code = s.slice('rule_name_'.length);
	if (ACTIVITY_RULES[code]) return ACTIVITY_RULES[code];
	const t = code.replace(/_/g, ' ');
	return t.charAt(0).toUpperCase() + t.slice(1);
}

export function fmtDate(d: string | null): string {
	return d ? `${d.slice(8, 10)}.${d.slice(5, 7)}.${d.slice(0, 4)}` : '—';
}

/** Українська множина: 1 урок / 2 уроки / 5 уроків (для віджета «Сьогодні»). */
export function lessonsWord(n: number): string {
	const m10 = n % 10;
	const m100 = n % 100;
	if (m10 === 1 && m100 !== 11) return 'урок';
	if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return 'уроки';
	return 'уроків';
}

/** Урок вже завершився? «Н» малюємо тільки якщо пара вже скінчилась. */
export function lessonOver(l: { end: string }): boolean {
	const p = (l.end || '').split(':');
	if (p.length !== 2) return true; // немає часу — показуємо як є
	const end = new Date();
	end.setHours(Number(p[0]), Number(p[1]), 0, 0);
	return Date.now() >= end.getTime();
}
