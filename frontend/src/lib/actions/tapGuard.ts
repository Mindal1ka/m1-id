/** Гасить «мімо-кліки»: клік, під час якого вказівник змістився
 *  більше за slop (px) від точки pointerdown, вважаємо скролом
 *  і не пропускаємо далі. Діє на всіх нащадків вузла (capture-фаза),
 *  тож достатньо повісити action на контейнер сітки.
 *
 *  Кліки з клавіатури (Enter на сфокусованій плитці) не чіпає —
 *  вони приходять без pointerdown.
 *
 *  Дефолт 8px ≈ системний touch-slop Android. */
export function tapGuard(node: HTMLElement, slop = 8): { destroy(): void } {
	let sx = 0;
	let sy = 0;
	let seen = false;

	const onDown = (e: PointerEvent): void => {
		if (e.pointerType === 'mouse' && e.button !== 0) return;
		sx = e.clientX;
		sy = e.clientY;
		seen = true;
	};

	const onClick = (e: MouseEvent): void => {
		if (!seen) return; // клік не з нашого вказівника — не втручаємось
		seen = false;
		if (Math.hypot(e.clientX - sx, e.clientY - sy) > slop) {
			e.preventDefault();
			e.stopPropagation();
		}
	};

	const onCancel = (): void => {
		seen = false;
	};

	node.addEventListener('pointerdown', onDown, true);
	node.addEventListener('click', onClick, true);
	node.addEventListener('pointercancel', onCancel, true);

	return {
		destroy() {
			node.removeEventListener('pointerdown', onDown, true);
			node.removeEventListener('click', onClick, true);
			node.removeEventListener('pointercancel', onCancel, true);
		}
	};
}
