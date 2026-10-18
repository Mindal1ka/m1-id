/** Програмний confirm(): чергу запитів показує єдиний <ConfirmHost />. */

export interface ConfirmOptions {
	title: string;
	message?: string;
	confirmText?: string;
	cancelText?: string;
	danger?: boolean;
}

export interface ConfirmRequest {
	title: string;
	message: string;
	confirmText: string;
	cancelText: string;
	danger: boolean;
	resolve: (value: boolean) => void;
}

export const confirmState = $state<{ current: ConfirmRequest | null }>({ current: null });

const queue: ConfirmRequest[] = [];

/** Пауза перед наступним запитом, щоб устиг програтись вихід попереднього діалогу. */
const NEXT_DELAY_MS = 240;

export function confirm(opts: ConfirmOptions): Promise<boolean> {
	return new Promise<boolean>((resolve) => {
		const req: ConfirmRequest = {
			title: opts.title,
			message: opts.message ?? '',
			confirmText: opts.confirmText ?? 'Підтвердити',
			cancelText: opts.cancelText ?? 'Скасувати',
			danger: opts.danger ?? false,
			resolve
		};
		if (confirmState.current) queue.push(req);
		else confirmState.current = req;
	});
}

/** Викликає ConfirmHost: закриває поточний запит і піднімає наступний із черги. */
export function resolveConfirm(value: boolean): void {
	const cur = confirmState.current;
	if (!cur) return;
	confirmState.current = null;
	cur.resolve(value);
	const next = queue.shift();
	if (next) {
		setTimeout(() => {
			confirmState.current = next;
		}, NEXT_DELAY_MS);
	}
}
