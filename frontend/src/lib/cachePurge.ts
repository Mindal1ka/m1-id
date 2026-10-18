/** Повне чищення клієнтських кешів при зміні версії білда.
 *
 *  Викликається з +layout.svelte, коли /version.json відрізняється
 *  від __BUILD_STAMP__ (вшитого в бандл). Чиститься:
 *   1) service worker-и (unregister — щоб старий SW не віддав стару
 *      оболонку з власного кеша);
 *   2) усі записи Cache Storage (кеш SW: оболонка, чанки, шрифти);
 *   3) localStorage — ЛИШЕ кеш-ключі за префіксами (m1id.cache.*,
 *      fs_menu_*). Усе інше (сесія, акаунти, тема, звуки, віджети,
 *      режим розробника, посилання дашборду тощо) НЕ чіпаємо: так нові
 *      налаштування не доведеться щоразу додавати у «білий список».
 *
 *  Після purge caller робить location.replace('?v=...') — релоад
 *  гарантовано дає свіжу збірку, HTTP-кеш HTML збито ?v=.
 */

// Префікси localStorage-ключів, які є КЕШЕМ і підлягають видаленню
const CACHE_PREFIXES = ['m1id.cache.', 'fs_menu_'];

export async function purgeAllCaches(): Promise<void> {
	// 1) service worker-и
	if ('serviceWorker' in navigator) {
		try {
			const regs = await navigator.serviceWorker.getRegistrations();
			await Promise.allSettled(regs.map((r) => r.unregister()));
		} catch { /* не критично */ }
	}
	// 2) Cache Storage (кеші SW: оболонка + immutable-чанки)
	if ('caches' in window) {
		try {
			const keys = await caches.keys();
			await Promise.allSettled(keys.map((k) => caches.delete(k)));
		} catch { /* не критично */ }
	}
	// 3) localStorage — лише кеш-ключі за префіксами
	try {
		const doomed: string[] = [];
		for (let i = 0; i < localStorage.length; i++) {
			const k = localStorage.key(i);
			if (k && CACHE_PREFIXES.some((p) => k.startsWith(p))) doomed.push(k);
		}
		for (const k of doomed) localStorage.removeItem(k);
	} catch { /* приватний режим */ }
	// 4) sessionStorage — теж кеш
	try { sessionStorage.clear(); } catch { /* приватний режим */ }
	// 5) IndexedDB (якщо десь використовується) — видаляємо всі БД
	try {
		const dbs = (await indexedDB.databases?.()) ?? [];
		await Promise.allSettled(
			dbs.map((db) => {
			const name = db.name;
			if (!name) return Promise.resolve();
			return new Promise<void>((res) => {
				const rq = indexedDB.deleteDatabase(name);
				rq.onsuccess = rq.onerror = rq.onblocked = () => res();
			});
		})
		);
	} catch { /* браузер без databases() — пропускаємо */ }
	// фіксуємо поточну версію (для діагностики на боці клієнта)
	try {
		localStorage.setItem('m1id.build', __BUILD_STAMP__);
	} catch { /* noop */ }
}
