/** Перекладач помилок на людську мову.
 *  Користувач бачить короткі фрази — жодних шляхів, URL і «запустіть start.bat». */
import { ApiError } from '$lib/api/client';

const MAP: Record<string, string> = {
	// мережа / сервер
	network: 'Немає з’єднання. Перевірте інтернет і спробуйте ще раз.',
	network_error: 'Немає з’єднання. Перевірте інтернет і спробуйте ще раз.',
	timeout: 'Сервер відповідає надто довго. Спробуйте ще раз.',

	// сесія M1 ID
	not_authenticated: 'Сесія завершилась. Увійдіть знову.',
	invalid_token: 'Сесія завершилась. Увійдіть знову.',
	refresh_invalid: 'Сесія завершилась. Увійдіть знову.',
	user_not_found: 'Сесія завершилась. Увійдіть знову.',

	// акаунти MyStat
	account_needs_relogin: 'Потрібно повторно увійти в MyStat.',
	mystat_invalid_credentials: 'Невірний логін або пароль MyStat.',
	mystat_unavailable: 'MyStat тимчасово недоступний. Спробуйте пізніше.',
	relative_not_supported: 'Батьківські акаунти MyStat поки не підтримуються. Увійдіть акаунтом студента.',
	sync_already_running: 'Синхронізація вже виконується.',
	snapshot_not_found: 'Даних за цей період ще немає.',
	account_not_found: 'Акаунт не знайдено.',

	// реєстрація / вхід M1 ID
	username_taken: 'Таке ім’я користувача вже зайняте.',
	email_taken: 'Цей email вже зареєстрований.',
	invalid_credentials: 'Невірний логін або пароль.',
	invalid_email_format: 'Некоректний email.',
	disposable_email: 'Одноразові email-адреси не підтримуються.',
	email_domain_not_found: 'Такий email не існує.',
	email_domain_unreachable: 'Цей email не приймає листи.',
	rate_limited: 'Занадто часто. Зачекайте хвилину.',

	qr_expired: 'QR застарів. Оновіть його на сторінці входу.',
	qr_wrong_code: 'Хибний код — запит відхилено задля безпеки.',

	// інше
	unknown_endpoint: 'Функція поки недоступна.',

	// здача домашки (M4e)
	hw_file_required: 'Додайте хоча б один файл або опишіть рішення текстом.',
	hw_file_too_large: 'Файл завеликий — ліміт 25 МБ.',
	hw_submit_rejected: 'MyStat не прийняв роботу. Можливо, минув дедлайн.',
	hw_nothing_to_delete: 'Немає що видаляти — робота ще не здана.'
};

export function friendlyError(ex: unknown): string {
	if (ex instanceof ApiError) {
		if (ex.code && MAP[ex.code]) return MAP[ex.code];
		if (ex.status === 401) return 'Сесія завершилась. Увійдіть знову.';
		if (ex.status === 403) return 'Недостатньо прав для цієї дії.';
		if (ex.status === 404) return 'Нічого не знайдено.';
		if (ex.status === 429) return 'Занадто часто. Зачекайте хвилину.';
		if (ex.status === 422) return 'Перевірте правильність заповнення полів.';
		if (ex.status >= 500) return 'Помилка сервера. Спробуйте пізніше.';
	}
	return 'Щось пішло не так. Спробуйте ще раз.';
}

/** Мережева помилка (офлайн / таймаут / бекенд недоступний): про це вже
 *  повідомляє StaleBanner, тож великі ErrorState на вкладках не потрібні. */
export function isNetworkError(ex: unknown): boolean {
	if (ex instanceof ApiError) {
		return ex.code === 'network' || ex.code === 'network_error' || ex.code === 'timeout' || (ex.status === 0 && !ex.code);
	}
	// Сирий збій fetch(): браузери кидають TypeError з типовим повідомленням
	// («Failed to fetch» / «NetworkError…» / «Load failed» / «Network request failed»).
	// Решта TypeError — це баги коду, а не відсутність мережі.
	if (ex instanceof TypeError) {
		return /failed to fetch|networkerror|network request failed|load failed|fetch failed/i.test(ex.message);
	}
	return false;
}

/** Спокійний підпис порожнього стану, коли даних немає, а ми офлайн. */
export const OFFLINE_EMPTY = 'Немає даних офлайн';
