/** Конфігурація бренду та оточення. Назва змінюється в ОДНОМУ місці (рішення №4). */
export const PROJECT_NAME = 'M1 ID';
export const TAGLINE = 'Твій MyStat — таким, яким він має бути.';
export const APP_VERSION = '0.6.0';
export const MILESTONE = 'M6 · write ops / plugins / telegram';

/**
 * Базовий URL API.
 *  1. VITE_API_URL з оточення збірки — найвищий пріоритет.
 *  2. Усі запити до бека — через https://mapi.<зона> (m1id.xyz → mapi.m1id.xyz).
 *     Виняток: сам хост mapi.<зона> (відкритий API, /docs) → ''.
 */
export const API_BASE: string = (() => {
	const env = String(import.meta.env.VITE_API_URL ?? '')
		.trim()
		.replace(/\/+$/, '');
	if (env) return env;
	if (typeof window !== 'undefined') {
		const h = window.location.hostname.toLowerCase();
		// сам API-хост (mapi.<зона>): база порожня — шляхи /api/... рідні
		if (h.startsWith('mapi.')) return '';
		// все інше (m1id.xyz, www., будь-який піддомен) → бек на mapi.<зона>
		const parts = h.split('.');
		// дев/локалхост: vite-проксі /api → 127.0.0.1:8080
		if (h === 'localhost' || h.endsWith('.localhost') || parts.length < 2) return '';
		return `https://mapi.${parts.slice(-2).join('.')}`;
	}
	return '';
})();
