/** API-клієнт M1 ID: конверт {ok,data,meta,error}, Bearer, авто-refresh на 401. */
import { auth } from '$lib/stores/auth.svelte';
import { API_BASE } from '$lib/config';

export interface EnvelopeError {
	field: string;
	message: string;
	code?: string;
}

interface Envelope<T> {
	ok: boolean;
	data: T;
	meta: unknown | null;
	error: EnvelopeError[] | null;
}

export interface Health {
	service: string;
	version: string;
	time: string;
}

export interface SpecStats {
	openapi: string;
	title: string;
	version: string;
	paths: number;
	operations: number;
	schemas: number;
	tags: number;
	by_tag: Record<string, number>;
	loaded_from: string | null;
}

export interface SpecOperation {
	method: string;
	path: string;
	operation_id: string;
	tag: string;
	summary: string;
	params: string[];
	secured: boolean;
}

export interface M1User {
	id: number;
	username: string;
	email: string;
	created_at: string | null;
	email_verified: boolean;
}

export interface AuthPair {
	access_token: string;
	refresh_token: string;
	user: M1User;
}

export type AccountStatus = 'active' | 'needs_relogin' | 'disabled';

/** Жива сесія (кермо пристрою) зі списку /api/auth/sessions. */
export interface SessionInfo {
	id: string;
	current: boolean;
	user_agent: string;
	created_at: string | null;
	last_seen_at: string | null;
	expires_at: string | null;
}

export interface AccountOut {
	id: number;
	label: string;
	branch_alias: string;
	/** Назва міста філії (бекенд мапить лише відомі коди: pl → Полтава). */
	branch_name?: string | null;
	logbook_id: string;
	id_user_storage: string;
	fio: string;
	login: string;
	photo_url: string;
	status: AccountStatus;
	language: string;
	last_synced_at: string | null;
	sync_status: string;
}

export interface SyncStep {
	section: string;
	label: string;
	status: 'pending' | 'running' | 'done' | 'failed';
	error?: string;
}

export interface SyncState {
	status: 'idle' | 'running' | 'done' | 'error';
	steps: SyncStep[];
	current?: string | null;
	progress?: { done: number; total: number };
	error?: string | null;
}

export interface SnapshotMeta {
	section: string;
	fetched_at: string | null;
	size_bytes: number;
}

// ---------- наш агрегований формат (/api/app/*) ----------

export interface DashUser {
	fio: string;
	photo_url: string;
	branch_alias: string;
	/** Назва міста філії, якщо код відомий бекенду. */
	branch_name?: string | null;
	logbook_id: string;
	id_user_storage: string;
	lang: string;
	group_name?: string;
}

export interface BalanceItem {
	key: string;
	icon: string;
	value: number;
	rating?: number | null;
}

export interface M1LinkView {
	slug: string;
	url: string;
	kind: 'url' | 'file';
	target_url: string;
	homework_id: number;
	hw_title: string;
	hw_subject: string;
	media: { name: string; ext: string }[] | null;
	gallery: boolean;
	active: boolean;
	opens: number;
	last_opened_at: string | null;
	created_at: string | null;
}

export interface HwItem {
	id: number;
	subject: string;
	title: string;
	teacher: string;
	assigned: string | null;
	due: string | null;
	status: number;
	status_label: string;
	mark: number | string | null;
	attachment: boolean;
	answer: boolean;
	is_test: boolean;
	/** есе (is_autotest = 2): відповідь лише текстом */
	is_essay?: boolean;
	/** тип ДЗ англійським ключем: essay | test | independent_work | practice_work | type_N */
	kind?: string;
	is_retake: boolean;
	overdue_days: number;
	/** монет за здачу давно простроченого ДЗ (−20), 0 якщо безкоштовно */
	late_penalty: number;
	/** монет за запит на перездачу виконаного ДЗ (−2) */
	retake_cost?: number;
}

/** Повна картка ДЗ (модалка деталей) — наш формат з homework_card_view. */
export interface HwCard {
	id: number;
	subject: string;
	title: string;
	teacher: string;
	teach_photo: string | null;
	status: number;
	status_label: string;
	assigned: string | null;
	due: string | null;
	completed: string | null;
	description: string;
	attachment: string | null;
	mark: number | string | null;
	answer_text: string;
	answer_files: string[];
	submitted_at: string | null;
	coins: number | null;
	late_penalty?: number;
	retake_cost?: number;
	is_test: boolean;
	is_essay?: boolean;
	kind?: string;
	autotest_status: number | null;
	autotest_result: string | null;
	teacher_comment: string;
	history: { type: string | null; text: string | null; date: string | null; file: string | null }[];
	submission_id: number | null;
}

export type HomeworkCounts = Record<'pending' | 'checking' | 'done', number>;

export interface Lesson {
	date: string;
	weekday: string | null;
	lesson_no: number;
	start: string;
	end: string;
	subject: string;
	theme: string;
	teacher: string;
	room: string;
	mark: number | null;
	/** ±19 у MyStat — «не допущено до екзамену» (показуємо «н/д») */
	not_allowed?: boolean;
	attendance: string | number | null;
	was: number | null;
	was_type: number | null;
	mark_type: number | null;
	homeworks: {
		id: string | number | null;
		mark: string | null;
		status: string | null;
	}[];
	video: boolean;
	exam: boolean;
}

export interface ScheduleDay {
	date: string;
	weekday: string | null;
	lessons: Lesson[];
}

export interface ScheduleView {
	kind: string;
	range: Record<string, string | null>;
	days: ScheduleDay[];
	total_lessons: number;
}

export interface MarkItem {
	date: string;
	mark: number;
	subject: string;
	theme: string;
	teacher: string;
	/** Фото вчителя (photo_pas). */
	photo?: string | null;
	comment?: string | null;
	/** Тип роботи з бандла MyStat: 0 testing · 1 coursework · 2 exam ·
	 *  3 home_work · 4 practice · 5 classwork · 6 control_work ·
	 *  7 thematic_work (рядок або null). */
	type_work?: string | number | null;
}

export interface MarksSubject {
	subject: string;
	avg: number;
	count: number;
	best: number;
	worst: number;
}

export interface MarksView {
	overall_avg: number | null;
	total_marks: number;
	subjects: MarksSubject[];
	recent: MarkItem[];
	items: MarkItem[];
}

export interface Dashboard {
	user: DashUser;
	balances: { items: BalanceItem[]; unread_counters: Record<string, number> };
	homework_counts: HomeworkCounts;
	nearest_deadlines: HwItem[];
	today_lessons: Lesson[];
	week_lessons_total: number;
	marks_summary: { overall_avg: number | null; recent: MarkItem[] };
	meta: Record<string, string | null>;
}

export interface HomeworkView {
	items: HwItem[];
	counts: HomeworkCounts;
	subjects: string[];
	total: number;
	nearest_deadlines: HwItem[];
}

export type ActivityAlias = 'cristals' | 'coins' | 'achivements' | string;

export interface ActivityItem {
	id: number;
	date: string;
	title: string;
	subtitle: string;
	mark: number | null;
	/** Картинка-іконка події з MyStat (може бути відсутня/не завантажитись). */
	icon?: string | null;
	awards: { alias: ActivityAlias; value: number }[];
}

export interface ActivityPage {
	items: ActivityItem[];
	page: number;
	per_page: number;
	total_pages: number;
	total_count: number;
	has_more: boolean;
}

// ------------------------------------------------------------ ядро

const REFRESH_LOCK = 'm1id-refresh';
const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

/** Єдиний політ refresh. Живе ДО завершення всієї doRefresh (разом із
 *  повторною спробою через 500 мс): інакше другий паралельний виклик з
 *  тим самим ротованим refresh-токеном отримав би 401 і розлогінив
 *  користувача. */
let refreshInflight: Promise<boolean> | null = null;

/** Оновити пару токенів. Паралельні 401 ділять ОДИН запит refresh, а між
 *  вкладками виклики серіалізуються через navigator.locks (де доступний). */
export function tryRefresh(): Promise<boolean> {
	if (!auth.refreshToken) return Promise.resolve(false);
	if (!refreshInflight) {
		refreshInflight = doRefresh().finally(() => {
			refreshInflight = null;
		});
	}
	return refreshInflight;
}

function doRefresh(): Promise<boolean> {
	const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined;
	if (locks?.request) {
		return locks.request(REFRESH_LOCK, () => refreshSerialized());
	}
	return refreshSerialized();
}

/** Один виклик /api/auth/refresh без побічних чисток сесії.
 *  status: HTTP-код, -1 — мережа/таймаут. */
async function callRefresh(): Promise<{ ok: boolean; status: number }> {
	const ctrl = new AbortController();
	const t = setTimeout(() => ctrl.abort(), 15_000);
	try {
		const res = await fetch(API_BASE + '/api/auth/refresh', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
			body: JSON.stringify({ refresh_token: auth.refreshToken }),
			signal: ctrl.signal
		});
		const body = (await res.json().catch(() => null)) as Envelope<AuthPair> | null;
		if (res.ok && body?.ok && body.data) {
			auth.setSession(body.data);
			return { ok: true, status: res.status };
		}
		return { ok: false, status: res.status };
	} catch {
		return { ok: false, status: -1 };
	} finally {
		clearTimeout(t);
	}
}

async function refreshSerialized(): Promise<boolean> {
	// Поки чекали на lock, інша вкладка могла вже ротувати токен —
	// тоді просто підхоплюємо її свіжу пару, не витрачаючи refresh-токен.
	if (auth.syncFromStorage()) return true;

	const first = await callRefresh();
	if (first.ok) return true;
	// мережа / 5xx — тимчасова помилка, сесію НЕ чіпаємо
	if (first.status !== 401 && first.status !== 403) return false;

	// Два страйки: ОДИН 401 від refresh не чистить сесію. Повторюємо
	// через 500 мс і чистимо лише якщо сервер відмовив ДВІЧІ поспіль.
	console.warn('[auth] refresh відмовив (401/403) — повторна перевірка…');
	await sleep(500);
	if (auth.syncFromStorage()) return true; // інша вкладка встигла оновити
	const second = await callRefresh();
	if (second.ok) return true;
	if (second.status !== 401 && second.status !== 403) return false;

	// Перед очищенням ще раз дивимось у localStorage: можливо, інша
	// вкладка щойно записала новішу сесію.
	if (auth.syncFromStorage()) return true;
	console.error(
		`[auth] refresh відмовив ДВІЧІ — сесію очищено. Статуси: ${first.status}, ${second.status}`
	);
	auth.clear();
	return false;
}

class ApiError extends Error {
	field = '';
	code = '';
	status = 0;
	constructor(message: string, field = '', code = '', status = 0) {
		super(message);
		this.field = field;
		this.code = code;
		this.status = status;
	}
}

/** Внутрішні прапори request(): мережевий ретрай і ретрай після refresh. */
interface RequestOpts {
	retried?: boolean;
	authRetry?: number;
}

async function request<T>(
	path: string,
	init: RequestInit = {},
	opts: RequestOpts = {}
): Promise<T> {
	const { retried = false, authRetry = 0 } = opts;
	const headers = new Headers(init.headers);
	headers.set('Accept', 'application/json');
	if (!headers.has('Authorization') && auth.accessToken) {
		headers.set('Authorization', `Bearer ${auth.accessToken}`);
	}
	let res: Response;
	// Таймаут кожного запиту. Таймаут НЕ ретраїться як мережева помилка:
	// ретрай лише справжньої network-помилки, лише для ідемпотентного
	// GET і лише один раз.
	const timeoutMs = init.body instanceof FormData ? 120_000 : 20_000;
	const ctrl = new AbortController();
	const abortTimer = setTimeout(() => ctrl.abort(), timeoutMs);
	try {
		res = await fetch(API_BASE + path, { ...init, headers, signal: ctrl.signal });
	} catch (ex) {
		clearTimeout(abortTimer);
		// AbortError від нашого таймаута — це НЕ network error:
		// ретрай перетворював повільний запит на до 40 с очікування.
		const aborted = ex instanceof DOMException && ex.name === 'AbortError';
		// Мережа здригнулась (наприклад, бекенд перезапускається) → одна
		// повторна спроба, лише ідемпотентний GET (retry POST міг би
		// задвоїти здачу ДЗ чи замовлення в магазині).
		const method = (init.method ?? 'GET').toUpperCase();
		if (!retried && !aborted && method === 'GET') {
			await sleep(500);
			return request<T>(path, init, { retried: true, authRetry });
		}
		throw new ApiError(
			aborted ? 'timeout' : 'network_error',
			'',
			aborted ? 'timeout' : 'network'
		);
	}
	clearTimeout(abortTimer);
	const body = (await res.json().catch(() => null)) as Envelope<T> | null;

	// 401 нашої сесії → refresh і повтор:
	//  • працює і БЕЗ JSON-тіла / без коду invalid_token (деякі 401
	//    повертають порожнє тіло) — сесія могла просто протухнути;
	//  • дозволяємо refresh і ПІСЛЯ network-retry;
	//  • authRetry < 1 — захист від циклу «refresh ок, але знову 401».
	if (res.status === 401 && authRetry < 1 && auth.refreshToken
		&& path !== '/api/auth/refresh' && path !== '/api/auth/login') {
		const code = body?.error?.[0]?.code ?? '';
		if (!body || code === '' || code === 'invalid_token' || code === 'not_authenticated') {
			if (await tryRefresh()) {
				return request<T>(path, init, { retried: true, authRetry: authRetry + 1 });
			}
		}
	}

	if (!body) throw new ApiError(`request_failed`, '', '', res.status);
	if (!body.ok) {
		const e = body.error?.[0];
		throw new ApiError(
			e?.message ?? 'request_failed',
			e?.field ?? '',
			e?.code ?? '',
			res.status
		);
	}
	return body.data;
}

/** Спільний «авторизований» fetch для не-JSON відповідей (файли):
 *  Bearer + таймаут + одна повторна спроба після refresh на 401.
 *  Таймаут діє до отримання заголовків відповіді. */
async function authedFetch(
	path: string,
	init: RequestInit = {},
	timeoutMs = 300_000
): Promise<Response> {
	const once = async (): Promise<Response> => {
		const headers = new Headers(init.headers);
		if (auth.accessToken) headers.set('Authorization', `Bearer ${auth.accessToken}`);
		const ctrl = new AbortController();
		const t = setTimeout(() => ctrl.abort(), timeoutMs);
		try {
			return await fetch(API_BASE + path, { ...init, headers, signal: ctrl.signal });
		} catch (ex) {
			const aborted = ex instanceof DOMException && ex.name === 'AbortError';
			throw new ApiError(
				aborted ? 'timeout' : 'network_error',
				'',
				aborted ? 'timeout' : 'network'
			);
		} finally {
			clearTimeout(t);
		}
	};
	let res = await once();
	if (res.status === 401 && auth.refreshToken && (await tryRefresh())) {
		res = await once();
	}
	return res;
}

/** Перетворює не-OK відповідь на ApiError (з тілом-конвертом, якщо є). */
async function throwFromResponse(res: Response, fallback: string, field = ''): Promise<never> {
	const body = (await res.json().catch(() => null)) as Envelope<unknown> | null;
	const e = body?.error?.[0];
	throw new ApiError(e?.message ?? fallback, e?.field ?? field, e?.code ?? '', res.status);
}

function getJson<T>(path: string): Promise<T> {
	return request<T>(path);
}

function postJson<T>(path: string, payload?: unknown): Promise<T> {
	return request<T>(path, {
		method: 'POST',
		headers: payload !== undefined ? { 'Content-Type': 'application/json' } : {},
		body: payload !== undefined ? JSON.stringify(payload) : undefined
	});
}

function delJson<T>(path: string): Promise<T> {
	return request<T>(path, { method: 'DELETE' });
}

// ---------- бінарні файли (переглядач ДЗ) ----------

export interface FetchedFile {
	blob: Blob;
	name: string;
	type: string;
}

/**
 * X-File-Name з HTTP-заголовка: не-latin1 символи бекенд процентно
 * кодує (кирилиця в заголовку ламає відповідь), тут розкодовуємо.
 */
function decodeFileName(raw: string | null): string {
	if (!raw) return 'file';
	try {
		return decodeURIComponent(raw);
	} catch {
		return raw;
	}
}

/** decodeURIComponent без винятку на битому %-кодуванні. */
function safeDecode(raw: string): string {
	try {
		return decodeURIComponent(raw);
	} catch {
		return raw;
	}
}

/** Читаємо тіло вручну через ReadableStream — так видно прогрес
 * (Content-Length бекенд тепер прокидає; total=0 → невизначений прогрес). */
async function readBlobWithProgress(
	res: Response,
	onProgress?: (loaded: number, total: number) => void
): Promise<Blob> {
	const type = res.headers.get('Content-Type') ?? 'application/octet-stream';
	const total = Number(res.headers.get('Content-Length') ?? '') || 0;
	if (!res.body) return await res.blob();
	const reader = res.body.getReader();
	const chunks: Uint8Array[] = [];
	let loaded = 0;
	for (;;) {
		const { done, value } = await reader.read();
		if (done) break;
		if (!value) continue;
		chunks.push(value);
		loaded += value.length;
		onProgress?.(loaded, total);
	}
	return new Blob(chunks as unknown as BlobPart[], { type });
}

/**
 * Бінарний GET (переглядач файлів ДЗ): той самий Bearer + авто-refresh на 401,
 * але відповідь — не конверт, а сирі байти. Таймаут більший (файли до 60 МБ).
 * onProgress — прогрес завантаження (loaded/total, байти).
 */
export async function fetchFile(
	path: string,
	onProgress?: (loaded: number, total: number) => void
): Promise<FetchedFile> {
	const res = await authedFetch(path, { headers: { Accept: '*/*' } });
	if (!res.ok) await throwFromResponse(res, 'file_fetch_failed', 'url');
	const blob = await readBlobWithProgress(res, onProgress);
	return {
		blob,
		name: decodeFileName(res.headers.get('X-File-Name')),
		type: res.headers.get('Content-Type') ?? 'application/octet-stream'
	};
}

function putJson<T>(path: string, payload: unknown): Promise<T> {
	return request<T>(path, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(payload)
	});
}

/** Аплоад файлів із прогресом (fetch не вміє upload-progress). Той самий
 *  конверт і той самий refresh сесії, що й у request(). */
function uploadFiles(
	path: string,
	fd: FormData,
	onProgress?: (loaded: number, total: number) => void,
	authRetry = 0
): Promise<FileItem> {
	return new Promise((resolve, reject) => {
		const xhr = new XMLHttpRequest();
		xhr.open('POST', API_BASE + path);
		xhr.setRequestHeader('Accept', 'application/json');
		if (auth.accessToken) xhr.setRequestHeader('Authorization', `Bearer ${auth.accessToken}`);
		xhr.timeout = 300_000;
		xhr.upload.onprogress = (e) => {
			if (e.lengthComputable) onProgress?.(e.loaded, e.total);
		};
		xhr.onerror = () => reject(new ApiError('network_error', '', 'network'));
		xhr.ontimeout = () => reject(new ApiError('timeout', '', 'timeout'));
		xhr.onload = async () => {
			let body: Envelope<FileItem> | null = null;
			try {
				body = JSON.parse(xhr.responseText) as Envelope<FileItem>;
			} catch {
				body = null;
			}
			if (xhr.status === 401 && authRetry < 1 && auth.refreshToken && (await tryRefresh())) {
				uploadFiles(path, fd, onProgress, authRetry + 1).then(resolve, reject);
				return;
			}
			if (!body) return reject(new ApiError('request_failed', '', '', xhr.status));
			if (!body.ok) {
				const e = body.error?.[0];
				return reject(
					new ApiError(e?.message ?? 'request_failed', e?.field ?? '', e?.code ?? '', xhr.status)
				);
			}
			resolve(body.data);
		};
		xhr.send(fd);
	});
}

// ------------------------------------------------------------ API

// ---------- Нотатки і паролі ----------

export interface NoteItem {
	id: number;
	title: string;
	preview: string;
	pinned: boolean;
	updated_at: string;
	created_at: string;
	/** Лише в повній відповіді (GET/POST/PUT одного запису). */
	body?: string;
}
export interface NoteIn {
	title: string;
	body: string;
	pinned: boolean;
}

export type VaultFieldKind = 'login' | 'password' | 'email' | 'phone' | 'url' | 'text' | 'secret';
export interface VaultField {
	id: string;
	kind: VaultFieldKind;
	label: string;
	/** У списку секретні поля (password/secret) приходять порожніми. */
	value: string;
	has_value?: boolean;
}
export interface VaultEntryItem {
	id: number;
	title: string;
	group: string;
	pinned: boolean;
	fields: VaultField[];
	/** true — ключ шифрування змінився, поля не розшифровуються. */
	broken: boolean;
	updated_at: string;
}
export interface VaultIn {
	title: string;
	group: string;
	pinned: boolean;
	fields: Pick<VaultField, 'id' | 'kind' | 'label' | 'value'>[];
}

// ---------- Файли (вкладка «Нотатки» → «Файли») ----------

export interface FileItem {
	/** 16 символів [A-Za-z0-9]; у нотатці — `file:<token>`. */
	token: string;
	name: string;
	description: string;
	orig_name: string;
	size: number;
	content_type: string;
	/** 'zip' — кілька файлів, запаковані в один архів. */
	kind: 'file' | 'zip';
	parts: string[];
	/** Пряме посилання на fs itstep (бачить лише власник). */
	url: string;
	created_at: string;
	updated_at: string;
	/** Нотатки власника, де використано `file:<token>`. */
	notes: { id: number; title: string }[];
}

export const api = {
	health: (): Promise<Health> => getJson('/api/health'),
	specStats: (): Promise<SpecStats> => getJson('/api/system/spec/stats'),

	register: (b: { username: string; password: string; email: string }) =>
		postJson<AuthPair>('/api/auth/register', b),
	login: (b: { login: string; password: string }) =>
		postJson<AuthPair>('/api/auth/login', b),
	logout: (refresh_token: string) =>
		postJson<{ logged_out: boolean }>('/api/auth/logout', { refresh_token }),
	me: () => getJson<M1User>('/api/auth/me'),


	// вхід за QR
	qrStart: () =>
		postJson<{ token: string; secret: string; url: string; qr: string; code: string; expires_in: number }>(
			'/api/auth/qr/start'
		),
	qrPoll: (token: string, secret: string) =>
		postJson<{ status: 'pending' | 'approved' | 'denied' | 'consumed' | 'expired'; pair: AuthPair | null }>(
			'/api/auth/qr/poll', { token, secret }
		),
	qrInfo: (token: string) =>
		getJson<{ device: string; ip: string; created_at: string; options: string[] }>(
			`/api/auth/qr/info?token=${encodeURIComponent(token)}`
		),
	qrApprove: (token: string, code: string) =>
		postJson<{ approved: boolean }>('/api/auth/qr/approve', { token, code }),
	qrDeny: (token: string) => postJson<{ denied: boolean }>('/api/auth/qr/deny', { token }),

	sessionsList: (current: string): Promise<SessionInfo[]> =>
		getJson(`/api/auth/sessions?current=${encodeURIComponent(current)}`),
	sessionRevoke: (session_id: string): Promise<{ revoked: boolean }> =>
		postJson('/api/auth/sessions/revoke', { session_id }),
	sessionsRevokeOthers: (keep: string): Promise<{ revoked: number }> =>
		postJson('/api/auth/sessions/revoke-others', { keep }),

	accountsList: (): Promise<AccountOut[]> => getJson('/api/accounts'),
	accountLink: (login_value: string, password: string) =>
		postJson<{ account: AccountOut; created: boolean }>(
			'/api/accounts/link', { login: login_value, password }),
	accountLinkToken: (access_token: string) =>
		postJson<{ account: AccountOut }>('/api/accounts/link-token', { access_token }),
	accountDelete: (id: number) =>
		delJson<{ deleted: boolean; id: number }>(`/api/accounts/${id}`),
	accountSync: (id: number) =>
		postJson<{ started: boolean }>(`/api/accounts/${id}/sync`, {}),
	syncStatus: (id: number): Promise<SyncState> =>
		getJson(`/api/accounts/${id}/sync/status`),
	snapshots: (id: number): Promise<SnapshotMeta[]> =>
		getJson(`/api/accounts/${id}/snapshots`),
	snapshot: (id: number, section: string): Promise<unknown> =>
		getJson(`/api/accounts/${id}/snapshots/${encodeURIComponent(section)}`),

	// --- профіль MyStat (через spec-driven проксі) ---
	personalData: (accountId: number, branch: string): Promise<Record<string, unknown>> =>
		getJson(`/api/mystat/v1/mystat/${branch}/profile/get-personal-data?__account=${accountId}`),

	checkModerating: (accountId: number, branch: string): Promise<unknown> =>
		getJson(`/api/mystat/v1/mystat/${branch}/profile/check-moderating-data?__account=${accountId}`),

	/** multipart: birthdate / phone / email / photo(File) — усе опціонально. */
	changePersonalData: (
		accountId: number,
		branch: string,
		fields: {
			birthdate?: string | null;
			phone?: string | null;
			email?: string | null;
			photo?: File | null;
		}
	): Promise<unknown> => {
		const fd = new FormData();
		if (fields.birthdate) fd.append('birthdate', fields.birthdate);
		if (fields.phone) fd.append('phone', fields.phone);
		if (fields.email) fd.append('email', fields.email);
		if (fields.photo) fd.append('photo', fields.photo);
		return request(`/api/mystat/v1/mystat/${branch}/profile/change-personal-data?__account=${accountId}`, {
			method: 'POST',
			body: fd
		});
	},

	// --- M1 Provider: короткі посилання ---
	links: (accountId: number, homeworkId?: number): Promise<{ items: M1LinkView[] }> =>
		getJson(`/api/links?__account=${accountId}${homeworkId ? `&homework_id=${homeworkId}` : ''}`),
	updateLink: (slug: string, targetUrl: string): Promise<M1LinkView> =>
		request(`/api/links/${slug}`, {
			method: 'PATCH',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ target_url: targetUrl })
		}),
	revokeLink: (slug: string): Promise<M1LinkView> =>
		request(`/api/links/${slug}`, { method: 'DELETE' }),
	uploadLinkFile: (slug: string, file: File, accountSeq?: number): Promise<M1LinkView> => {
		const fd = new FormData();
		fd.append('file', file);
		const q = accountSeq ? `?__account=${accountSeq}` : '';
		return request(`/api/links/${slug}/file${q}`, { method: 'POST', body: fd });
	},

	// --- наше агреговане API (M3) ---
	dashboard: (accountId: number, force = false): Promise<Dashboard> =>
		getJson(`/api/app/dashboard?__account=${accountId}${force ? '&force=true' : ''}`),
	homework: (accountId: number, force = false): Promise<HomeworkView> =>
		getJson(`/api/app/homework?__account=${accountId}${force ? '&force=true' : ''}`),
	hwCard: (accountId: number, homeworkId: number): Promise<HwCard> =>
		getJson(`/api/app/homework/${homeworkId}?__account=${accountId}`),
	deleteSubmission: (
		accountId: number,
		homeworkId: number
	): Promise<{ deleted: boolean; submission_id: number }> =>
		request<{ deleted: boolean; submission_id: number }>(
			`/api/app/homework/${homeworkId}/submission?__account=${accountId}`,
			{ method: 'DELETE' }
		),
	submitHomework: (
		accountId: number,
		homeworkId: number,
		comment: string,
		files: File[],
		opts?: {
			zip_mode?: 'auto' | 'always' | 'off';
			zip_name?: string;
			compress_level?: number;
			rename?: boolean;
			link?: string;
			provider?: 'itstep' | 'm1';
			open_in_browser?: boolean;
		}
	): Promise<{ submission_id: number | null; status: number; files: string[]; archived?: boolean; archived_name?: string | null; m1_link?: M1LinkView | null }> => {
		const fd = new FormData();
		fd.append('comment', comment);
		for (const f of files) fd.append('files', f);
		if (opts?.zip_mode) fd.append('zip_mode', opts.zip_mode);
		if (opts?.zip_name) fd.append('zip_name', opts.zip_name);
		if (opts?.compress_level !== undefined) fd.append('compress_level', String(opts.compress_level));
		if (opts?.rename === false) fd.append('rename', 'false');
		if (opts?.link) fd.append('link', opts.link);
		if (opts?.provider) fd.append('provider', opts.provider);
		if (opts?.open_in_browser) fd.append('open_in_browser', 'true');
		return request(
			`/api/app/homework/${homeworkId}/submit?__account=${accountId}`,
			{ method: 'POST', body: fd }
		);
	},
	schedule: (accountId: number, kind: 'week' | 'month' = 'week', date?: string, force = false): Promise<ScheduleView> =>
		getJson(`/api/app/schedule?kind=${kind}${date ? `&date=${encodeURIComponent(date)}` : ''}&__account=${accountId}${force ? '&force=true' : ''}`),
	marks: (accountId: number, period: 'month' | 'year' = 'year', force = false): Promise<MarksView> =>
		getJson(`/api/app/marks?period=${period}&__account=${accountId}${force ? '&force=true' : ''}`),

	activity: (accountId: number, page = 1, perPage = 20): Promise<ActivityPage> =>
		getJson(`/api/app/activity?page=${page}&per_page=${perPage}&__account=${accountId}`),

	// --- новини / магазин (M5) ---
	news: (accountId: number, force = false): Promise<NewsView> =>
		getJson(`/api/app/news?__account=${accountId}${force ? '&force=true' : ''}`),
	newsDetail: (accountId: number, newsId: number): Promise<NewsDetail> =>
		getJson(`/api/app/news/${newsId}?__account=${accountId}`),
	shop: (accountId: number, force = false): Promise<ShopView> =>
		getJson(`/api/app/shop?__account=${accountId}${force ? '&force=true' : ''}`),
	shopBuy: (
		accountId: number,
		productId: number,
		quantity = 1
	): Promise<ShopOpResult> =>
		request<ShopOpResult>(
			`/api/app/shop/order?product_id=${productId}&quantity=${quantity}&__account=${accountId}`,
			{ method: 'POST' }
		),
	shopDiscard: (accountId: number, uuid: string): Promise<ShopOpResult> =>
		request<ShopOpResult>(
			`/api/app/shop/order/${encodeURIComponent(uuid)}?__account=${accountId}`,
			{ method: 'DELETE' }
		),

	// --- платежі / клуби / контакти (M5) ---
	payments: (accountId: number, force = false): Promise<PaymentsView> =>
		getJson(
			`/api/app/payments?__account=${accountId}${force ? '&force=true' : ''}`
		),
	clubs: (accountId: number, force = false): Promise<ClubsView> =>
		getJson(
			`/api/app/clubs?__account=${accountId}${force ? '&force=true' : ''}`
		),
	contacts: (accountId: number, force = false): Promise<ContactsData> =>
		getJson(
			`/api/app/contacts?__account=${accountId}${force ? '&force=true' : ''}`
		),

	// --- нагороди / прогрес ---
	awards: (accountId: number, force = false): Promise<AwardsView> =>
		getJson(
			`/api/app/awards?__account=${accountId}${force ? '&force=true' : ''}`
		),
	awardsBuy: (accountId: number, items: number[]): Promise<ApiOpResult> =>
		postJson(`/api/app/awards/buy?__account=${accountId}`, { items }),
	awardsEquip: (accountId: number, item_id: number): Promise<ApiOpResult> =>
		postJson(`/api/app/awards/equip?__account=${accountId}`, { item_id }),
	progress: (accountId: number, force = false): Promise<ProgressView> =>
		getJson(
			`/api/app/progress?__account=${accountId}${force ? '&force=true' : ''}`
		),

	/** Довідка (файл з MyStat) — blob + ім'я з content-disposition. */
	downloadReference: async (
		accountId: number,
		type = 1
	): Promise<{ blob: Blob; filename: string }> => {
		const res = await authedFetch(
			`/api/app/reference-data?type=${type}&__account=${accountId}`,
			{ headers: { Accept: 'application/octet-stream' } },
			120_000
		);
		if (!res.ok) await throwFromResponse(res, 'reference_error');
		const blob = await res.blob();
		const cd = res.headers.get('content-disposition') ?? '';
		const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(cd);
		return {
			blob,
			filename: m ? safeDecode(m[1]) : 'dovidka.pdf'
		};
	},
	contactsSend: (
		accountId: number,
		subject: string,
		message: string,
		target: 'ceo' | 'teach' = 'ceo',
		teacher?: string
	): Promise<ApiOpResult> =>
		postJson(`/api/app/contacts/send?__account=${accountId}`, {
			target,
			subject,
			message,
			teacher
		}),
	clubBuy: (accountId: number, clubId: number, abonementId: number): Promise<ApiOpResult> =>
		postJson(`/api/app/clubs/buy?__account=${accountId}`, {
			club_id: clubId,
			abonement_id: abonementId
		}),

	qr: (accountId: number, force = false): Promise<QrData> =>
		getJson(`/api/app/qr?__account=${accountId}${force ? '&force=true' : ''}`),
	leaderboard: (accountId: number, force = false): Promise<LeaderboardView> =>
		getJson(`/api/app/leaderboard?__account=${accountId}${force ? '&force=true' : ''}`),

	// --- Харчування (FoodStep) ---
	nutritionMenu: async (supplier: string, force = false): Promise<FsMenu> => {
		// клієнтський кеш меню на 2 години (localStorage)
		const ck = `fs_menu_${supplier}`;
		if (!force) {
			try {
				const raw = localStorage.getItem(ck);
				if (raw) {
					const { data, ts } = JSON.parse(raw) as { data: FsMenu; ts: number };
					if (Date.now() - ts < 2 * 60 * 60 * 1000) return data;
				}
			} catch { /* битий кеш — тягнемо заново */ }
		}
		const data = await request<FsMenu>(
			`/api/nutrition/menu?supplier=${encodeURIComponent(supplier)}${force ? '&force=true' : ''}`,
			{ cache: 'no-store' }
		);
		try {
			localStorage.setItem(ck, JSON.stringify({ data, ts: Date.now() }));
		} catch { /* приватний режим — не критично */ }
		return data;
	},
	nutritionConfig: (): Promise<FsConfig> => getJson('/api/nutrition/config'),
	nutritionSaveConfig: (
		patch: Partial<FsConfig['auto']> & { supplier?: string }
	): Promise<FsConfig> =>
		putJson('/api/nutrition/config', {
			supplier: patch.supplier,
			auto_enabled: patch.enabled,
			auto_mode: patch.mode,
			fixed_variation_id: patch.fixed_variation_id,
			order_time: patch.order_time,
			notify_minutes: patch.notify_minutes,
			allow_weekends: patch.allow_weekends
		}),
	nutritionPassword: (password: string): Promise<{ password_set: boolean }> =>
		postJson('/api/nutrition/password', { password }),
	nutritionOrder: (b: {
		supplier?: string;
		dates: string[];
		items: FsOrderItem[];
	}): Promise<{ results: FsOrderResult[] }> =>
		postJson('/api/nutrition/order', b),
	nutritionOrders: (limit = 60): Promise<{ orders: FsOrder[] }> =>
		getJson(`/api/nutrition/orders?limit=${limit}`),
	nutritionCalendar: (month: string): Promise<{
		ordered: Record<string, { total: number; supplier: string }>;
		cancelled?: Record<string, { total: number; supplier: string }>;
	}> =>
		getJson(`/api/nutrition/calendar?month=${encodeURIComponent(month)}`),
	nutritionCancelOrder: (date: string): Promise<{ cancelled: boolean; remote: boolean; remote_status: string; note: string }> =>
		delJson(`/api/nutrition/order?date=${encodeURIComponent(date)}`),
	nutritionAddVariation: (b: {
		name: string;
		supplier?: string;
		items: FsOrderItem[];
	}): Promise<FsVariation> => postJson('/api/nutrition/variations', b),
	nutritionDelVariation: (id: number): Promise<{ deleted: boolean }> =>
		delJson(`/api/nutrition/variations/${id}`),

	// --- Telegram (сповіщення / прив'язка) ---
	tgStatus: (): Promise<TelegramStatus> => getJson('/api/telegram/status'),
	tgSaveSettings: (
		patch: { account_seq: number } & Partial<TelegramSettings>
	): Promise<TelegramSettings> => postJson('/api/telegram/settings', patch),
	tgUnlink: (): Promise<{ unlinked: boolean }> =>
		postJson('/api/telegram/unlink', {}),
	tgTest: (account_seq?: number): Promise<{ sent: boolean }> =>
		postJson('/api/telegram/test', { account_seq: account_seq ?? null }),

	// --- Додаткові (notify-сокет MyStat / Автооцінювання) ---
	extrasStatus: (): Promise<ExtrasStatus> => getJson('/api/extras/status'),
	extrasSaveSettings: (
		patch: { account_seq: number } & Partial<ExtrasSettings>
	): Promise<ExtrasSettings> => postJson('/api/extras/settings', patch),
	widgetLayoutsGet: (): Promise<{ layouts: Record<string, unknown>;
		updated_at: string | null }> =>
		getJson('/api/widgets/layouts'),
	widgetLayoutsPut: (layouts: unknown): Promise<{ layouts: unknown }> =>
		putJson('/api/widgets/layouts', { layout: layouts }),
	appearanceGet: (): Promise<{ pref: Record<string, unknown>;
		updated_at: string | null }> => getJson('/api/appearance'),
	appearancePut: (pref: unknown): Promise<{ pref: unknown }> =>
		putJson('/api/appearance', { pref }),

	// --- Файли (fs itstep, токени для нотаток) ---
	filesList: (): Promise<{ items: FileItem[] }> => getJson('/api/files'),
	/** `files` — один файл або кілька (тоді сервер пакує їх в один zip). */
	filesUpload: (
		files: File[],
		meta: { name: string; description: string },
		accountSeq: number,
		onProgress?: (loaded: number, total: number) => void
	): Promise<FileItem> => {
		const fd = new FormData();
		for (const f of files) fd.append('files', f, f.name);
		fd.append('name', meta.name);
		fd.append('description', meta.description);
		return uploadFiles(`/api/files${accountSeq ? `?__account=${accountSeq}` : ''}`, fd, onProgress);
	},
	fileUpdate: (token: string, meta: { name: string; description: string }): Promise<FileItem> =>
		putJson(`/api/files/${token}`, meta),
	fileDelete: (
		token: string,
		accountSeq?: number
	): Promise<{ deleted: boolean; remote_deleted: boolean }> =>
		delJson(`/api/files/${token}${accountSeq ? `?__account=${accountSeq}` : ''}`),

	// --- Нотатки і паролі ---
	notesList: (q = ''): Promise<{ items: NoteItem[] }> =>
		getJson(`/api/notes${q ? '?q=' + encodeURIComponent(q) : ''}`),
	noteGet: (id: number): Promise<NoteItem> => getJson(`/api/notes/${id}`),
	noteCreate: (n: NoteIn): Promise<NoteItem> => postJson('/api/notes', n),
	noteUpdate: (id: number, n: NoteIn): Promise<NoteItem> => putJson(`/api/notes/${id}`, n),
	noteDelete: (id: number): Promise<{ deleted: boolean }> => delJson(`/api/notes/${id}`),
	vaultList: (): Promise<{ items: VaultEntryItem[] }> => getJson('/api/vault'),
	vaultGet: (id: number): Promise<VaultEntryItem> => getJson(`/api/vault/${id}`),
	vaultCreate: (e: VaultIn): Promise<VaultEntryItem> => postJson('/api/vault', e),
	vaultUpdate: (id: number, e: VaultIn): Promise<VaultEntryItem> =>
		putJson(`/api/vault/${id}`, e),
	vaultDelete: (id: number): Promise<{ deleted: boolean }> => delJson(`/api/vault/${id}`),

	// --- Плагіни (маркетплейс / інсталяція / налаштування) ---
	pluginsList: (): Promise<PluginOut[]> => getJson('/api/plugins'),
	pluginInstall: (id: string, permissions: string[], account_seqs: number[] = []): Promise<unknown> =>
		postJson(`/api/plugins/${id}/install`, { accept_permissions: permissions, account_seqs }),
	pluginUninstall: (id: string): Promise<{ ok: boolean }> =>
		postJson(`/api/plugins/${id}/uninstall`, {}),
	pluginEnable: (id: string, enabled: boolean): Promise<{ ok: boolean }> =>
		postJson(`/api/plugins/${id}/enable`, { enabled }),
	pluginSettings: (id: string): Promise<PluginSettingsResp> =>
		getJson(`/api/plugins/${id}/settings`),
	pluginSaveSettings: (id: string, settings: Record<string, unknown>, account_seqs?: number[]):
		Promise<{ settings: Record<string, unknown>; account_seqs: number[] }> =>
		putJson(`/api/plugins/${id}/settings`, { settings, account_seqs }),
	pluginRuns: (id: string): Promise<PluginRunRow[]> =>
		getJson(`/api/plugins/${id}/runs`),
	pluginUi: (id: string, params: Record<string, unknown> = {}):
		Promise<{ ok: boolean; data?: unknown; error?: string }> =>
		postJson(`/api/plugins/${id}/ui`, { params }),
	pluginSource: (id: string): Promise<{ html: string }> =>
		getJson(`/api/plugins/${id}/source`),
	pluginUploadJson: (manifest: unknown, files: Record<string, string>):
		Promise<{ id: string; verified: boolean }> =>
		postJson('/api/plugins', { manifest, files }),
	pluginUploadZip: (file: File, visibility = 'public'):
		Promise<{ id: string; verified: boolean; visibility: string; share_token: string }> => {
		const fd = new FormData();
		fd.append('file', file);
		fd.append('visibility', visibility);
		return request('/api/plugins/upload-zip', { method: 'POST', body: fd });
	},
	pluginUploadFiles: (files: File[], visibility = 'public'):
		Promise<{ id: string; verified: boolean; visibility: string; share_token: string }> => {
		const fd = new FormData();
		for (const f of files) fd.append('files', f);
		fd.append('visibility', visibility);
		return request('/api/plugins/upload-files', { method: 'POST', body: fd });
	},
	pluginShare: (id: string, visibility?: string): Promise<{ visibility: string; share_token: string }> =>
		postJson(`/api/plugins/${id}/share`, { visibility }),
	pluginShared: (token: string): Promise<PluginOut> =>
		getJson(`/api/plugins/shared/${token}`),
	pluginDownload: async (id: string): Promise<void> => {
		const res = await authedFetch(`/api/plugins/${id}/download`, {}, 120_000);
		if (!res.ok) await throwFromResponse(res, 'download_failed');
		const blob = await res.blob();
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = `${id}.zip`;
		a.click();
		// не відкликаємо URL одразу: деякі браузери ще не почали завантаження
		setTimeout(() => URL.revokeObjectURL(url), 10_000);
	},
	pluginDelete: (id: string): Promise<unknown> =>
		request(`/api/plugins/${id}`, { method: 'DELETE' }),
	pluginVerify: (id: string, verified: boolean): Promise<{ ok: boolean }> =>
		postJson(`/api/plugins/${id}/verify`, { verified })
};

/** Проксований виклик справжнього MyStat API через наш шлюз.
 *  path починається з /v1/mystat/... — як в openapi.json. */
export function mystat<T = unknown>(path: string): Promise<T> {
	return request<T>(`/api/mystat${path.startsWith('/') ? path : '/' + path}`);
}

/** Блоб-кеш картинок страв: /api/nutrition/img вимагає Bearer, тож
 *  <img src> напряму не працює. Ключ — src; значення — promise blob-URL. */
const nutImgCache = new Map<string, Promise<string>>();
const NUT_IMG_MAX = 150;

export function nutritionImgUrl(src: string): Promise<string> {
	let hit = nutImgCache.get(src);
	if (!hit) {
		hit = (async () => {
			const res = await authedFetch(
				`/api/nutrition/img?src=${encodeURIComponent(src)}`,
				{ headers: { Accept: 'image/*' } },
				30_000
			);
			if (!res.ok) await throwFromResponse(res, 'image_failed');
			return URL.createObjectURL(await res.blob());
		})();
		hit.catch(() => nutImgCache.delete(src));
		nutImgCache.set(src, hit);
		// простий ліміт кешу: викидаємо найстаріший запис
		if (nutImgCache.size > NUT_IMG_MAX) {
			const oldest = nutImgCache.keys().next().value as string;
			const p = nutImgCache.get(oldest);
			nutImgCache.delete(oldest);
			p?.then((u) => URL.revokeObjectURL(u)).catch(() => {});
		}
	}
	return hit;
}

/** Звільнити всі blob-URL картинок страв (при знищенні компонента). */
export function releaseNutritionImgs(): void {
	for (const p of nutImgCache.values()) p.then((u) => URL.revokeObjectURL(u)).catch(() => {});
	nutImgCache.clear();
}

export { ApiError };

// ===================== Плагіни =====================

export interface PluginOut {
	id: string;
	name: string;
	version: string;
	author: string;
	description: string;
	verified: boolean;
	visibility: 'public' | 'link' | 'private';
	share_token: string;
	permissions: string[];
	tg_commands: { command: string; description: string }[];
	hooks: Record<string, boolean>;
	ui: { tab?: boolean; widget?: string; entry?: string };
	settings_schema?: { key: string; type: string; label?: string; default?: unknown; options?: string[] }[];
	installed: boolean;
	enabled: boolean;
	settings?: Record<string, unknown>;
	account_seqs: number[];
	code_hash: string;
	stats?: { installs: number; runs: number };
	can_admin?: boolean;
	is_admin?: boolean;
}

export interface PluginSettingsResp {
	account_seqs: number[];
	schema: { key: string; type: string; label?: string; default?: unknown; options?: string[] }[];
	values: Record<string, unknown>;
	storage_kb: number;
}

export interface PluginRunRow {
	ok: boolean;
	trigger: string;
	detail: string;
	ms: number;
	error: string;
	at: string;
}

// ===================== Новини (M5) =====================

export interface NewsItem {
	id: number;
	title: string;
	preview: string;
	image: string | null;
	is_viewed: boolean;
	published_at: string;
	author: string | null;
	mark: number | null;
}

export interface NewsView {
	items: NewsItem[];
	unread: number;
}

export interface NewsDetail extends NewsItem {
	text: string;
	avg_mark?: number | null;
}

// ===================== Магазин (M5) =====================

export type Currency = 'coins' | 'cristals' | 'beavers';

export interface ShopProduct {
	id: number;
	title: string;
	text: string;
	image: string | null;
	quantity: number | null;
	price: string | null;
	min_price: string | null;
	currency: Currency;
	/** Усі ціни товару: монети Й кристали одночасно (live: COI+DIA). */
	prices: ShopPrice[];
	properties: { name: string; value: string }[];
}

export interface ShopPrice {
	price: string | null;
	min_price: string | null;
	currency: Currency;
}
export interface ShopOrderItem {
	product_id: number;
	title: string;
	quantity: number;
	image: string | null;
	price: number;
	currency: Currency;
	/** Усі валюти позиції: [{price, currency}] — монети І кристали. */
	prices?: { price: number; currency: Currency }[];
}

export interface ShopOrder {
	id: number;
	uuid: string;
	status: number;
	status_label: string;
	cancelled: boolean;
	/** 2|4|5 (скасовано/закрито) — замовлення вже неактивне. */
	archived: boolean;
	created_at: string;
	can_discard: boolean;
	items: ShopOrderItem[];
	total: number;
	currency: Currency;
	/** Суми по КОЖНІЙ валюті (товар завжди коштує монети І кристали). */
	totals: { price: number; currency: Currency }[];
}

export interface ShopView {
	products: ShopProduct[];
	orders: ShopOrder[];
}

/** Результат покупки/скасування: статус mapi прокинуто як є. */
export interface ShopOpResult {
	status: number;
	data: unknown;
}

// ===================== Харчування (FoodStep) =====================

export interface FsDish {
	id: number;
	title: string;
	price: number;
	weight?: string;
	image?: string | null;
	corex_id: number | null;
	_no?: number;
}

export interface FsCategory {
	name: string;
	dishes: FsDish[];
}

export interface FsMenu {
	supplier: string;
	supplier_title: string;
	categories: FsCategory[];
	dishes: FsDish[];
}

export interface FsOrderItem {
	id: number;
	count: number;
}

export interface FsOrderResult {
	date: string;
	ok: boolean;
	status: string;
	message?: string;
	total?: number;
}

export interface FsOrder {
	date: string;
	supplier: string;
	supplier_title: string;
	items: (FsOrderItem & { title?: string })[];
	total: number;
	source: 'manual' | 'auto';
	status: string;
	created_at: string | null;
}

export interface FsVariation {
	id: number;
	name: string;
	supplier: string;
	items: FsOrderItem[];
}

export interface FsConfig {
	supplier: string;
	password_set: boolean;
	auto: {
		enabled: boolean;
		mode: 'random' | 'fixed';
		fixed_variation_id: number | null;
		order_time: string;
		notify_minutes: number;
		allow_weekends: boolean;
		skip_dates: string[];
	};
	variations: FsVariation[];
}

// ===================== QR / Лідерборд (M5) =====================

export interface QrData {
	qr: string;
}

export interface LbPoints {
	total: number | null;
	position: number | null;
	week_diff: number | null;
	month_diff: number | null;
}

export interface LbRow {
	id: string | number | null;
	fio: string;
	photo: string | null;
	amount: number | null;
	position: number | null;
	is_new: boolean;
}

/** mapi дає НЕ суцільний рейтинг: топ-3, рядки навколо твоєї позиції
 *  і новеньких (без позиції) — окремими блоками. */
export interface LbSection {
	top: LbRow[];
	nearby: LbRow[];
	new_students: LbRow[];
}

/** Періоди залежать від гілки mapi: школа - month/semester/year,
 *  академія - month/all_time. Невідомі ключі теж можливі - тому тип
 *  строковий, а доступні варіанти фронт бере з view.scopes. */
export type LbPeriod =
	| 'month' | 'semester' | 'year' | 'all_time' | (string & {});

/** Гілка mapi: академія / школа / невідома (невідома - англ. підписи). */
export type LbBranch = 'academy' | 'school' | 'unknown';

/** Готові підписи з бекенда (укр для відомих гілок, англ для невідомих):
 *  фронт просто рендерить label, нічого не хардкодячи. */
export interface LbPeriodMeta {
	key: LbPeriod;
	label: string;
}

export interface LbScopeMeta {
	key: string;
	label: string;
	periods: LbPeriodMeta[];
}

export interface LeaderboardView {
	points: Record<string, LbPoints>;
	/** «рейтинг, що ковзає»: 1-3 + вікно навколо твоєї позиції. */
	sliding_rating: boolean;
	branch: LbBranch;
	/** Доступні охоплення з періодами (динамічно, з live-відповіді). */
	scopes: LbScopeMeta[];
	/** sections[scope][period] → блоки top/nearby/new_students. */
	sections: Record<string, Record<string, LbSection>>;
}


// --- платежі / клуби / контакти (M5) ---

export type PaymentHistoryItem = {
	date: string | null;
	amount: number | null;
	currency: string;
	description: string;
};

export type PaymentsView = {
	full_name: string | null;
	one_c_code: string | null;
	online_link: string | null;
	instruction_link: string | null;
	student_cost: number | null;
	debtor_status: number;
	debt_amount: number;
	next_date: string | null;
	next_critical: string | null;
	history: PaymentHistoryItem[];
	schedule: unknown;
};

export type ClubSchedule = { day: string | null; from: string; to: string };

export type ClubItem = {
	id: number;
	name: string;
	category: string | null;
	sub_type: string | null;
	cost: number | null;
	debt: number;
	address: string | null;
	image: string | null;
	description: string | null;
	status: string | null;
	schedules: ClubSchedule[];
	teachers: string[];
	abonements: { id: number;[k: string]: unknown }[];
};

export type ClubsView = {
	clubs: ClubItem[];
	abonements: unknown[];
	balance: number;
	transactions: unknown[];
};

export type ContactsData = Record<string, unknown>;

export type ApiOpResult = { status: number; data: unknown };

// ===================== Нагороди / Прогрес =====================

export type AwardsItem = {
	id: number;
	img: string;
	price: number;
	currency: string;
	purchased: boolean;
	equipped: boolean;
	/** Безкоштовний (дефолт) предмет — без prices. */
	free: boolean;
};

export type AwardsCategory = { key: string; items: AwardsItem[] };

export type AwardsView = {
	/** Баланс бобрів (BEV). */
	beavers: number;
	categories: AwardsCategory[];
};

export type ProgressPoint = {
	month: string;
	points: number | null;
	prev: number | null;
};

export type ProgressChart = {
	chart_type: number | string | null;
	average: number | null;
	prev_average: number | null;
	points: ProgressPoint[];
};

export type ProgressView = {
	charts: ProgressChart[];
	total_average: number | null;
	prev_total_average: number | null;
};

// ===================== Telegram (сповіщення) =====================

export interface TelegramSettings {
	/** Нова домашка від викладача. */
	homework_new: boolean;
	/** Нагадування про дедлайн домашки (за 24 год і за 3 год). */
	deadlines: boolean;
	/** Зміна рейтингу (бали ачівок). */
	rating_change: boolean;
	/** Зміна розкладу поточного тижня. */
	schedule_week_change: boolean;
	/** Зміна розкладу на сьогодні (заміни). */
	schedule_day_change: boolean;
	/** Розклад на день щоранку о 06:00. */
	schedule_daily: boolean;
	/** Нова оцінка. */
	marks_new: boolean;
	/** Зміна порядку в лідерборді. */
	leaderboard_change: boolean;
	/** true - лише коли змінилась МОЯ позиція; false - будь-яка зміна. */
	leaderboard_mine_only: boolean;
	/** Який саме зріз лідерборда моніторити: 'group', 'stream'… ('' = усі). */
	leaderboard_scope: string;
	/** Період обраного зрізу: 'month', 'all_time'… ('' = усі). */
	leaderboard_period: string;
	/** Зміни товарів магазину. */
	shop_change: boolean;
	/** Тихі години 23:00-05:00 (рекомендовано): не смікати mapi вночі. */
	quiet_hours: boolean;
	/** Повідомити в TG, коли урок оцінено автоматично («Додаткові»). */
	auto_eval_notify: boolean;
	link_open_notify: boolean;
}

/** Конфіз сповіщень одного акаунта (конфіги розділені по акаунтах!). */
export interface TelegramAccountInfo {
	account_seq: number;
	login: string;
	fio: string;
	label: string;
	status: string;
	settings: TelegramSettings | null;
}

export interface TelegramStatus {
	linked: boolean;
	/** Токен бота задано в .env сервера. */
	bot_configured: boolean;
	/** Поллінг активний саме зараз. */
	bot_running: boolean;
	bot_username: string | null;
	/** https://t.me/<bot>?start=<uid>-<sig> - унікальне для вашого акаунта. */
	deep_link: string | null;
	/** PNG data-URI з QR-кодом deep_link (лише поки не прив'язано). */
	qr_data_uri: string | null;
	site_url: string;
	linked_at: string | null;
	/** Кожен акаунт зі СВОЇМ конфігом сповіщень. */
	accounts: TelegramAccountInfo[];
}

// ===================== Додаткові (сокет / Автооцінювання) =====================

export interface ExtrasSettings {
	/** Живе з'єднання з notify-сокетом MyStat: миттєві події. */
	socket_enabled: boolean;
	/** Автоматично оцінювати 5/5 без коментаря кожен урок, що надійшов. */
	auto_eval: boolean;
}

export interface ExtrasAccountInfo {
	account_seq: number;
	login: string;
	socket_enabled: boolean;
	auto_eval: boolean;
	/** Тихі години (спільна галочка з Telegram-вкладкою). */
	quiet_hours: boolean;
	/** З'єднання активне саме зараз. */
	connected: boolean;
	last_event_at: string | null;
	events: number;
	/** Успішних автооцінок у цьому запуску. */
	evals_ok: number;
	/** Уроки, відкладені на тихі години (оцінимо зранку). */
	pending_evals: number;
	last_error: string;
	last_eval: {
		theme: string;
		teach_name: string;
		rated_at: string | null;
	} | null;
}

export interface ExtrasStatus {
	/** false = python-socketio не встановлено на сервері. */
	available: boolean;
	accounts: ExtrasAccountInfo[];
}

