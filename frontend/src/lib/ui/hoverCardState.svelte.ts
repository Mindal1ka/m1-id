/**
 * Контролер спільного спливного вікна (HoverCard).
 *
 * Один екземпляр на сторінку: споживачі (уроки, оцінки) лише повідомляють,
 * над яким якорем наведено курсор / зроблено тап і що показати, а сам вікно
 * рендерить `HoverCard.svelte` — із появою, зникненням і плавним переїздом
 * між якорями.
 */

export interface HoverCardOptions {
	/** Затримка показу при наведенні (коли вікно ще закрите), мс. */
	showDelay?: number;
	/** Затримка приховування («місток», щоб встигнути перевести курсор на вікно), мс. */
	hideDelay?: number;
}

export class HoverCardController<T> {
	/** Вікно має бути відкрите (елемент може ще грати анімацію виходу). */
	isOpen = $state(false);
	/** Ключ поточного якоря: зміна ключа при відкритому вікні = переїзд. */
	key = $state('');
	data = $state.raw<T | null>(null);
	anchor = $state.raw<HTMLElement | null>(null);
	/** X курсора на момент наведення — вікно центрується біля нього в межах якоря. */
	px = $state.raw<number | null>(null);

	readonly showDelay: number;
	readonly hideDelay: number;
	#showTimer: ReturnType<typeof setTimeout> | undefined;
	#hideTimer: ReturnType<typeof setTimeout> | undefined;

	constructor({ showDelay = 90, hideDelay = 150 }: HoverCardOptions = {}) {
		this.showDelay = showDelay;
		this.hideDelay = hideDelay;
	}

	#clearShow(): void {
		clearTimeout(this.#showTimer);
		this.#showTimer = undefined;
	}

	#clearHide(): void {
		clearTimeout(this.#hideTimer);
		this.#hideTimer = undefined;
	}

	#apply(anchor: HTMLElement, key: string, data: T, px: number | null): void {
		this.#clearShow();
		this.#clearHide();
		this.anchor = anchor;
		this.key = key;
		this.data = data;
		this.px = px;
		this.isOpen = true;
	}

	/** Курсор над якорем. Якщо вікно вже відкрите — переїзд без затримки. */
	hover(anchor: HTMLElement, key: string, data: T, px: number | null = null): void {
		this.#clearHide();
		if (this.isOpen) {
			this.#apply(anchor, key, data, px);
			return;
		}
		this.#clearShow();
		this.#showTimer = setTimeout(() => this.#apply(anchor, key, data, px), this.showDelay);
	}

	/** Курсор залишив якір (або саме вікно). */
	unhover(): void {
		this.#clearShow();
		if (!this.isOpen) return;
		this.#clearHide();
		this.#hideTimer = setTimeout(() => this.close(), this.hideDelay);
	}

	/** Курсор на самому вікні — не ховати. */
	keep(): void {
		this.#clearHide();
	}

	/** Тап / клік / Enter: відкрити, а повторний тап по тому ж якорю — закрити. */
	toggle(anchor: HTMLElement, key: string, data: T, px: number | null = null): void {
		if (this.isOpen && this.key === key) {
			this.close();
			return;
		}
		this.#apply(anchor, key, data, px);
	}

	/** Показати негайно (клік мишею на пристрої з hover). */
	show(anchor: HTMLElement, key: string, data: T, px: number | null = null): void {
		this.#apply(anchor, key, data, px);
	}

	close(): void {
		this.#clearShow();
		this.#clearHide();
		this.isOpen = false;
	}
}
