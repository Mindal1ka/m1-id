import { HoverCardController } from '$lib/ui/hoverCardState.svelte';
import type { MarkItem } from '$lib/api/client';
import type { SchedLesson } from '$lib/app/helpers';

/** Що можна показати у спільному спливному вікні. */
export type HoverPayload =
	| { kind: 'lesson'; l: SchedLesson }
	| { kind: 'mark'; m: MarkItem; cls: string; label: string };

/** Ключ уроку з датою: той самий урок у різні дні не ділить стан вікна. */
export function lessonKey(l: SchedLesson): string {
	return `lesson|${l.date ?? ''}|${l.lesson_no}|${l.start}|${l.end}|${l.subject}|${l.room}|${l.theme ?? ''}`;
}

/** Контролер, що гарантує дату в ключі уроку, навіть якщо виклик передав ключ без неї. */
class AppHoverCardController extends HoverCardController<HoverPayload> {
	#key(key: string, data: HoverPayload): string {
		if (data.kind !== 'lesson') return key;
		const d = data.l.date;
		return d && !key.includes(d) ? `${key}|${d}` : key;
	}
	override hover(anchor: HTMLElement, key: string, data: HoverPayload, px: number | null = null): void {
		super.hover(anchor, this.#key(key, data), data, px);
	}
	override toggle(anchor: HTMLElement, key: string, data: HoverPayload, px: number | null = null): void {
		super.toggle(anchor, this.#key(key, data), data, px);
	}
	override show(anchor: HTMLElement, key: string, data: HoverPayload, px: number | null = null): void {
		super.show(anchor, this.#key(key, data), data, px);
	}
}

/** Єдиний екземпляр на сторінку (рендериться у HoverCards.svelte). */
export const hoverCard = new AppHoverCardController();
