/** Стан сесії M1 ID (Svelte 5 runes) + персист у localStorage.
 *  Сесія має переживати закриття вкладки/браузера: refresh-токен живе
 *  30 днів на бекенді, тож зберігаємо пару токенів у localStorage —
 *  спільно між усіма вкладками. Авто-refresh на 401 (клієнт) оновлює
 *  access щомісячно непомітно; користувач логінеться лише раз.
 *  (Колишній sessionStorage-варіант і зумовлював «постійні вильоти»:
 *  будь-яке закриття вкладки = втрачена сесія.) */
import { browser } from '$app/environment';
import type { AuthPair, M1User } from '$lib/api/client';

const KEY = 'm1id.session.v1';

class AuthStore {
	user = $state<M1User | null>(null);
	accessToken = $state('');
	refreshToken = $state('');
	restored = $state(false);

	get isAuthed(): boolean {
		return Boolean(this.accessToken);
	}

	restore(): void {
		if (!browser || this.restored) return;
		try {
			// міграція зі старих ключів: sessionStorage + старий localStorage-ключ
			const legacySs = sessionStorage.getItem(KEY);
			if (legacySs && !localStorage.getItem(KEY)) {
				localStorage.setItem(KEY, legacySs);
			}
			sessionStorage.removeItem(KEY);
		} catch {
			/* ignore */
		}
		try {
			const raw = localStorage.getItem(KEY);
			if (raw) {
				const s = JSON.parse(raw);
				this.user = s.user ?? null;
				this.accessToken = s.access ?? '';
				this.refreshToken = s.refresh ?? '';
			}
		} catch {
			/* битий кеш — ігноруємо */
		}
		this.restored = true;
		this.listenStorage();
	}

	private listening = false;

	/** Синхронізація між вкладками: якщо інша вкладка оновила або
	 *  очистила сесію, підхоплюємо це через подію `storage`. Токени
	 *  refresh ротуються, тож стара копія в пам'яті стала б недійсною. */
	private listenStorage(): void {
		if (!browser || this.listening) return;
		this.listening = true;
		window.addEventListener('storage', (ev: StorageEvent) => {
			if (ev.key !== null && ev.key !== KEY) return;
			// запис зник (вихід в іншій вкладці) → скидаємо стан у пам'яті
			if (ev.newValue === null) {
				this.user = null;
				this.accessToken = '';
				this.refreshToken = '';
				return;
			}
			this.syncFromStorage();
		});
	}

	/** Перечитує сесію з localStorage. Повертає true, якщо підхопили
	 *  НОВІШУ пару токенів (refresh відрізняється від поточного).
	 *  Пам'ять не очищає: це робить лише подія `storage` з видаленням. */
	syncFromStorage(): boolean {
		if (!browser) return false;
		try {
			const raw = localStorage.getItem(KEY);
			// порожньо = немає що підхоплювати (у приватному режимі запис
			// міг не збережитись — сесію в пам'яті НЕ чіпаємо)
			if (!raw) return false;
			const s = JSON.parse(raw);
			const refresh: string = s.refresh ?? '';
			if (refresh && refresh !== this.refreshToken) {
				this.user = s.user ?? this.user;
				this.accessToken = s.access ?? '';
				this.refreshToken = refresh;
				return true;
			}
		} catch {
			/* битий запис або storage недоступний — лишаємо як є */
		}
		return false;
	}

	private persist(): void {
		if (!browser) return;
		try {
			localStorage.setItem(KEY, JSON.stringify({
				user: this.user,
				access: this.accessToken,
				refresh: this.refreshToken
			}));
		} catch {
			// приватний режим iOS / переповнення квоти: сесія в пам'яті
			// працює, просто не переживе перезавантаження
		}
	}

	setSession(pair: AuthPair): void {
		this.user = pair.user;
		this.accessToken = pair.access_token;
		this.refreshToken = pair.refresh_token;
		this.persist();
	}

	clear(): void {
		this.user = null;
		this.accessToken = '';
		this.refreshToken = '';
		if (browser) {
			try {
				localStorage.removeItem(KEY);
				sessionStorage.removeItem(KEY);
			} catch {
				// приватний режим iOS / відмова storage: сесія вже очищена
				// в пам'яті — падати тут не можна, інакше в doRefresh() виняток
				// піде у викликаючий запит замість ApiError, а JSON сесії
				// залишиться в localStorage (після reload — «ghost session»)
			}
		}
	}
}

export const auth = new AuthStore();
