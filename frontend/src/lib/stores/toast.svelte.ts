/** Сповіщення — стек пігулок (можна декілька одночасно).
 *  Використання з будь-якого компонента:
 *    import { showToast } from '$lib/stores/toast.svelte';
 *    showToast('Замовлено, 288 грн');
 *    showToast('Збережено', 2500, 'success');
 */
export type ToastTone = 'success' | 'error' | 'info';
/** `ms` — тривалість показу (для смужки прогресу); 0 = не зникає саме. */
export type Toast = { id: number; msg: string; tone: ToastTone; ms: number };

export const toasts = $state<{ list: Toast[] }>({ list: [] });

interface Timer {
	handle: ReturnType<typeof setTimeout> | null;
	remaining: number;
	startedAt: number;
}

let nextId = 0;
const timers = new Map<number, Timer>();

function arm(id: number, t: Timer): void {
	t.startedAt = Date.now();
	t.handle = setTimeout(() => {
		timers.delete(id);
		toasts.list = toasts.list.filter((x) => x.id !== id);
	}, t.remaining);
}

function drop(id: number): void {
	const t = timers.get(id);
	if (t?.handle) clearTimeout(t.handle);
	timers.delete(id);
}

export function showToast(msg: string, ms = 3500, tone: ToastTone = 'info'): void {
	if (!msg) return;
	const id = ++nextId;
	toasts.list = [...toasts.list, { id, msg, tone, ms }];
	// стек не розростається: максимум 4 одночасно
	if (toasts.list.length > 4) {
		const removed = toasts.list.slice(0, -4);
		toasts.list = toasts.list.slice(-4);
		for (const r of removed) drop(r.id);
	}
	if (ms > 0) {
		const t: Timer = { handle: null, remaining: ms, startedAt: 0 };
		timers.set(id, t);
		arm(id, t);
	}
}

/** Пауза автозакриття (hover / утримання). Повторний виклик ігнорується. */
export function pauseToast(id: number): void {
	const t = timers.get(id);
	if (!t?.handle) return;
	clearTimeout(t.handle);
	t.handle = null;
	t.remaining = Math.max(0, t.remaining - (Date.now() - t.startedAt));
}

/** Відновити автозакриття після паузи. */
export function resumeToast(id: number): void {
	const t = timers.get(id);
	if (!t || t.handle) return;
	arm(id, t);
}

/** Закрити тост вручну (хрестик, свайп). */
export function closeToast(id: number): void {
	drop(id);
	toasts.list = toasts.list.filter((x) => x.id !== id);
}
