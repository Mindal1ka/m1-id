export type GradeTone = 'high' | 'mid' | 'low' | 'none';

/** Тон оцінки за якістю. Шкала 12: ≥10 high, ≥7 mid; шкала 5: ≥4.5 / ≥3.5; інші шкали — за часткою. */
export function gradeTone(value: number | string | null | undefined, scale = 12): GradeTone {
	if (value === null || value === undefined || value === '') return 'none';
	const n = typeof value === 'number' ? value : Number(String(value).replace(',', '.'));
	if (!Number.isFinite(n)) return 'none';
	if (scale === 12) return n >= 10 ? 'high' : n >= 7 ? 'mid' : 'low';
	if (scale === 5) return n >= 4.5 ? 'high' : n >= 3.5 ? 'mid' : 'low';
	const r = n / scale;
	return r >= 10 / 12 ? 'high' : r >= 7 / 12 ? 'mid' : 'low';
}
