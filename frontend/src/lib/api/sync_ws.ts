/**
 * Живий пуш стану синку через WebSocket /api/ws/sync.
 *
 * Протокол:
 *  - клієнт відкриває `wss://<api>/api/ws/sync` БЕЗ токена в URL (токен у
 *    query потрапляв би в логи проксі та історію);
 *  - ПЕРШИМ повідомленням після open клієнт шле текстовий JSON-кадр
 *    `{"type":"auth","token":"<access_token>"}`;
 *  - сервер перевіряє токен: невалідний/протермінований access → закриває
 *    сокет з кодом 4401 (також 1008 розглядаємо як відмову автентифікації);
 *    клієнт тоді оновлює токен (refresh) і перепідключається;
 *  - після успішної автентифікації сервер шле стартові стани всіх акаунтів
 *    (JSON `{account, status, ...SyncState}`), далі пушить зміни;
 *  - keepalive: текстовий кадр «p» кожні 20 с (шлеться лише після auth-кадру);
 *  - обрив → автореконект із бекофом (0.5 с → 30 с);
 *  - поки WS не підключений, викликач може тримати полінг-фолбек
 *    (див. onStatus(false) у +page.svelte).
 */
import { auth } from '$lib/stores/auth.svelte';
import { API_BASE } from '$lib/config';
import { tryRefresh, type SyncState } from './client';

/** Коди закриття, що означають «токен не прийнято». */
const AUTH_CLOSE_CODES = new Set([4401, 1008]);

/** WS-хост API: з API_BASE (https://mapi.m1id.xyz → wss://mapi.m1id.xyz),
 *  а не location.host — статик-хост сайту не має бекенда за собою. */
function wsBase(): string {
	if (API_BASE) return API_BASE.replace(/^http/, 'ws');
	// API на тому самому хості (mapi.<зона> / дев-проксі)
	const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
	return `${proto}//${location.host}`;
}

export interface SyncWsHandle {
	close(): void;
}

export function openSyncWs(
	onState: (accountSeq: number, st: SyncState) => void,
	onStatus: (connected: boolean) => void
): SyncWsHandle {
	let ws: WebSocket | null = null;
	let closed = false;
	let retry = 0;
	let ping: ReturnType<typeof setInterval> | undefined;
	let retryTimer: ReturnType<typeof setTimeout> | undefined;

	const cleanup = (): void => {
		if (ping) clearInterval(ping);
		ping = undefined;
	};

	/** Єдина точка планування реконекту: повторний виклик, поки таймер
	 *  уже стоїть, ігнорується (інакше connect-catch + onclose давали б
	 *  два паралельні з'єднання). */
	const scheduleRetry = (): void => {
		if (closed || retryTimer) return;
		retry = Math.min(retry + 1, 6);
		retryTimer = setTimeout(() => {
			retryTimer = undefined;
			connect();
		}, Math.min(30_000, 500 * 2 ** retry));
	};

	const connect = (): void => {
		if (closed) return;
		let sock: WebSocket;
		try {
			sock = new WebSocket(`${wsBase()}/api/ws/sync`);
		} catch {
			onStatus(false);
			scheduleRetry();
			return;
		}
		ws = sock;
		sock.onopen = () => {
			if (ws !== sock) return;
			// ПЕРШЕ повідомлення — автентифікація (див. протокол вище)
			try {
				sock.send(JSON.stringify({ type: 'auth', token: auth.accessToken }));
			} catch {
				/* сокет уже мертвий — onclose зробить реконект */
				return;
			}
			retry = 0;
			onStatus(true);
			ping = setInterval(() => {
				try {
					sock.send('p');
				} catch {
					/* сокет уже мертвий — onclose зробить реконект */
				}
			}, 20_000);
		};
		sock.onmessage = (ev: MessageEvent): void => {
			try {
				const msg = JSON.parse(ev.data) as { account?: number } & SyncState;
				if (msg && typeof msg.account === 'number' && msg.status) {
					onState(msg.account, msg);
				}
			} catch {
				/* «p»-відповіді/сміття — ігноруємо */
			}
		};
		sock.onclose = async (ev: CloseEvent) => {
			if (ws !== sock) return; // застарілий сокет
			cleanup();
			ws = null;
			onStatus(false);
			if (closed) return;
			if (AUTH_CLOSE_CODES.has(ev.code)) {
				// access протермінувався → оновлюємо токен перед реконектом
				try {
					await tryRefresh();
				} catch {
					/* помилка refresh — реконект усе одно спробуємо за бекофом */
				}
				if (closed) return;
			}
			scheduleRetry();
		};
		sock.onerror = () => {
			/* onclose прийде сам */
		};
	};

	connect();
	return {
		close(): void {
			closed = true;
			cleanup();
			if (retryTimer) clearTimeout(retryTimer);
			retryTimer = undefined;
			try {
				ws?.close();
			} catch {
				/* вже закрито */
			}
		}
	};
}
