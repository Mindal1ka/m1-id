/** Режим розробника: показує технічну вкладку «Дані» (снапшоти кешу).
 *  За замовчуванням ВИМКНЕНИЙ; звичайному користувачу не потрібно,
 *  але хто хоче - нехай увімкне в налаштуваннях. */
import { browser } from '$app/environment';

const KEY = 'm1id.devmode';

class DevStore {
	enabled = $state(false);

	constructor() {
		if (!browser) return;
		try {
			this.enabled = localStorage.getItem(KEY) === '1';
		} catch {
			/* приватний режим / бітий кеш - вимкнено */
		}
	}

	set(v: boolean): void {
		this.enabled = v;
		if (!browser) return;
		try {
			localStorage.setItem(KEY, v ? '1' : '0');
		} catch {
			/* quota - режим просто не переживе перезавантаження */
		}
	}
}

export const dev = new DevStore();
