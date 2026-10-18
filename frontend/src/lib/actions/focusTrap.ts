/** Доступність модалок: пастка фокуса, повернення фокуса та inert-фон. */

const FOCUSABLE =
	'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),' +
	'textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

function focusables(node: HTMLElement): HTMLElement[] {
	return Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
		(el) => !el.hasAttribute('inert') && el.getClientRects().length > 0
	);
}

/** Svelte-action для вікна діалогу: при відкритті переводить фокус у
 *  діалог (перший елемент або сам вузол), Tab/Shift+Tab не виходять за
 *  межі вікна, при закритті фокус повертається на елемент-ініціатор. */
export function focusTrap(node: HTMLElement): { destroy(): void } {
	const prev = document.activeElement instanceof HTMLElement ? document.activeElement : null;
	if (!node.hasAttribute('tabindex')) node.setAttribute('tabindex', '-1');

	// rAF: вузол ще може переїжджати в body (portal) / анімуватись
	const raf = requestAnimationFrame(() => {
		if (node.contains(document.activeElement)) return;
		(focusables(node)[0] ?? node).focus({ preventScroll: true });
	});

	const onKey = (e: KeyboardEvent): void => {
		if (e.key !== 'Tab') return;
		const items = focusables(node);
		if (items.length === 0) {
			e.preventDefault();
			node.focus();
			return;
		}
		const first = items[0];
		const last = items[items.length - 1];
		const active = document.activeElement;
		if (e.shiftKey && (active === first || active === node)) {
			e.preventDefault();
			last.focus();
		} else if (!e.shiftKey && active === last) {
			e.preventDefault();
			first.focus();
		}
	};
	node.addEventListener('keydown', onKey);

	return {
		destroy(): void {
			cancelAnimationFrame(raf);
			node.removeEventListener('keydown', onKey);
			if (prev && prev.isConnected) prev.focus({ preventScroll: true });
		}
	};
}

/** Робить решту сторінки `inert` (недоступною для фокуса й скрінрідерів),
 *  поки живе вузол; при знищенні знімає лише те, що поставила сама. */
export function inertBackground(node: HTMLElement): { destroy(): void } {
	const marked: HTMLElement[] = [];
	let cur: HTMLElement | null = node;
	while (cur && cur !== document.body) {
		const parent: HTMLElement | null = cur.parentElement;
		if (!parent) break;
		for (const sib of Array.from(parent.children)) {
			if (
				sib !== cur &&
				sib instanceof HTMLElement &&
				!sib.hasAttribute('inert') &&
				// тости лишаються клікабельними поверх діалогів
				!sib.hasAttribute('data-keep-interactive')
			) {
				sib.setAttribute('inert', '');
				marked.push(sib);
			}
		}
		cur = parent;
	}
	return {
		destroy(): void {
			for (const el of marked) el.removeAttribute('inert');
		}
	};
}
