/**
 * Переносить вузол у <body>. Потрібно для поповерів з `position: fixed`
 * усередині `.glass` (backdrop-filter створює containing block і z-index
 * лишається всередині карточки).
 */
export function portal(node: HTMLElement): { destroy(): void } {
	document.body.appendChild(node);
	return { destroy: () => node.remove() };
}
