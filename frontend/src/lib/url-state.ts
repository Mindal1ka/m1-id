/**
 * Синхронізація стану вкладок/модалок з URL БЕЗ перезавантаження.
 *
 * Використовуємо нативний pushState/replaceState (не goto): SPA-сторінка
 * /app лишається змонтованою, SvelteKit-навігація не запускається,
 * адреса в браузері змінюється — назад/вперед працює через popstate
 * (обробник у +page.svelte).
 */
type Params = Record<string, string | null>;

function urlWith(params: Params): string {
	const url = new URL(location.href);
	for (const [k, v] of Object.entries(params)) {
		if (v === null || v === '') url.searchParams.delete(k);
		else url.searchParams.set(k, v);
	}
	return url.pathname + url.search;
}

/** Новий запис історії (кнопка «Назад» поверне попередній стан). */
export function pushUrl(params: Params): void {
	history.pushState({}, '', urlWith(params));
}

/** Тихе оновлення адреси без нового запису історії. */
export function replaceUrl(params: Params): void {
	history.replaceState({}, '', urlWith(params));
}

export function queryParam(key: string): string | null {
	return new URLSearchParams(location.search).get(key);
}
