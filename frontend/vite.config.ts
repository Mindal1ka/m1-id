import adapter from '@sveltejs/adapter-static';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig, loadEnv, type Plugin } from 'vite';
// @ts-ignore - node types
import { readFileSync, readdirSync, writeFileSync, existsSync, statSync } from 'node:fs';
// @ts-ignore - node types
import { join } from 'node:path';
/**
 * Унікальний штамп КОЖНОГО білда: рандомні числа (мс + rand).
 * Використовується одночасно в трьох місцях — тому клієнт, сервер і
 * воркер ЗАВЖДИ про одну версію:
 *  • define __BUILD_STAMP__  → зібраний бандл сам знає свою версію
 *    (детермінований детект «прод уже новіший, а вкладка стара»);
 *  • build/version.json      → сервер віддає актуальну версію;
 *  • build/sw.js VERSION     → нові байти воркера на кожен білд.
 *
 * Vite оцінює цей конфіг ДВАЧИ (окремо client- і SSR-збірки), тому
 * «свіжий рандом» на завантаженні модуля давав РІЗНІ штампи в бандлі
 * та у version.json → модалка оновлення показувалась би вічно.
 * Рішення: штамп живе у файлі-маркері .svelte-kit/m1id-stamp.txt і
 * повторно використовується протягом 120с (одна команда vite build
 * встигає повністю), після чого генерується новий.
 */
const STAMP_FILE = join('.svelte-kit', 'm1id-stamp.txt');
const STAMP_WINDOW_MS = 120_000;

function currentStamp(): string {
	try {
		if (existsSync(STAMP_FILE)) {
			const age = Date.now() - statSync(STAMP_FILE).mtimeMs;
			if (age >= 0 && age < STAMP_WINDOW_MS) {
				return readFileSync(STAMP_FILE, 'utf8').trim();
			}
		}
	} catch {
		/* нема файла/читання не вдалось - генеруємо новий */
	}
	const s = `${Date.now()}-${Math.floor(Math.random() * 9000) + 1000}`;
	try {
		writeFileSync(STAMP_FILE, s);
	} catch {
		/* .svelte-kit недоступний - рідкісний випадок, рандом у пам'яті */
	}
	return s;
}

const STAMP = currentStamp();

/**
 * Кожен білд піднімає VERSION у build/sw.js (суфікс-час).
 * Байти воркера змінюються -> браузер гарантовано ставить новий SW,
 * новий кеш, і вкладки оновлюються самі (SHELL_UPDATED -> тост).
 * Жодних «на проді досі стара версія» вручну.
 */
function swAutoVersion(): Plugin {
	return {
		name: 'm1id-sw-auto-version',
		apply: 'build',
		enforce: 'post',
		closeBundle() {
			try {
				const p = 'build/sw.js';
				const c = readFileSync(p, 'utf8');
				const out = c.replace(
					/const VERSION = '(m1id-v\d+)[^']*';/,
					(_m: string, base: string) =>
						`const VERSION = '${base}-auto${STAMP}';`
				);
				writeFileSync(p, out);
				// прапор версії для клієнта: layout опитує /version.json
				writeFileSync('build/version.json', JSON.stringify({ v: STAMP }));
				console.log('[m1id] build stamp -> ' + STAMP);
			} catch (e) {
				console.warn('[m1id] sw version bump failed:', e);
			}
		}
	};
}

function cssPrefixGuard(): Plugin {
	// СТРАЖ: сканує зібраний CSS і ПАДАЄ, якщо мініфікатор знову з'їв
	// -webkit-backdrop-filter або стандартний (обидва рази був біль —
	// спершу lightningcss, потім esbuild з chrome87-ціллю).
	return {
		name: 'm1id-css-prefix-guard',
		apply: 'build',
		enforce: 'post',
		closeBundle() {
			try {
				// свіжий клієнтський вивід Vite (build/ на цей момент ще старий — адаптер пише його пізніше)
				const dir = '.svelte-kit/output/client';
				let std = 0;
				let wbk = 0;
				const walk = (d: string): void => {
					for (const e of readdirSync(d, { withFileTypes: true })) {
						const p = join(d, e.name);
						if (e.isDirectory()) walk(p);
						else if (e.name.endsWith('.css')) {
							const t = readFileSync(p, 'utf8');
							std += (t.match(/(?<!-)backdrop-filter\s*:\s*blur/g) || []).length;
							wbk += (t.match(/-webkit-backdrop-filter\s*:\s*blur/g) || []).length;
						}
					}
				};
				walk(dir);
				console.log(
					`[m1id] css prefix guard: backdrop-filter=${std} / -webkit-backdrop-filter=${wbk}`
				);
				if (std === 0 || wbk === 0 || std !== wbk) {
					throw new Error(
						`CSS prefix guard: -webkit-backdrop-filter (${wbk}) != backdrop-filter (${std}) — мініфікатор з'їв префікси, скло зникне у Safari/Chrome. Див. cssTarget у vite.config.`
					);
				}
			} catch (e) {
				if (e instanceof Error && e.message.includes('prefix guard')) throw e;
				console.warn('[m1id] css prefix guard skipped:', (e as Error).message);
			}
		}
	};
}

export default defineConfig(({ mode }) => {
	// Домен проєкту — з frontend/.env (M1ID_DOMAIN), fallback m1id.xyz.
	const ENV = loadEnv(mode, process.cwd(), '');
	const DOMAIN = String(ENV.M1ID_DOMAIN || 'm1id.xyz').replace(/^https?:\/\//, '').replace(/\/+$/, '');

	return {
	// Клієнт знає версію СВОГО бандла: __BUILD_STAMP__ вшивається в JS.
	// Порівняння з /version.json (щохвилини) → модалка оновлення.
	define: {
		__BUILD_STAMP__: JSON.stringify(STAMP)
	},

	// lightningcss-мініфікатор збірки ВИКИДАВ стандартний backdrop-filter,
	// залишаючи лише -webkit- (Safari) -> у Chrome скло ставало прозорим.
	// chrome87 підтримує backdrop-filter без префікса - і все лишиться.
	build: {
		target: 'esnext',
		// Історія: lightningcss ВИКИДАВ стандартний backdrop-filter (лишав
		// лише -webkit- -> у Chrome скло ставало прозорим), тому тут був
		// cssMinify: false (CSS взагалі не стискався). esbuild префікси
		// не чіпає — перевірено грепом dist після білда: всі пари
		// backdrop-filter / -webkit-backdrop-filter на місці.
		cssMinify: 'esbuild',
		// safari15 у цілях — критично: esbuild із лише chrome87 вирізав
		// -webkit-backdrop-filter як «непотрібний префікс» (16 -> 0 у dist).
		// З safari15 у цілях префікс «потрібний» і виживає.
		cssTarget: ['chrome87', 'safari15']
	},

	plugins: [
		// swAutoVersion() перенесено в scripts/bump-sw.mjs (npm run build):
		// у closeBundle build/sw.js ще не існує — бамп міг тільки фейлитись
		cssPrefixGuard(),
		sveltekit({
			compilerOptions: {
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},

			// SPA-режим PWA: уся статика в build/, невідомі шляхи → app.html.
			// ВАЖЛИВО: index.html — це ПРЕРЕНДЕРЕНИЙ лендінг '/' (ssr=true),
			// тому фолбеком служить окремий SPA-шелл app.html: гідратація
			// лендінгу на шляху /app чи /login дала б місмач і крах.
			adapter: adapter({
				fallback: 'app.html',
				pages: 'build',
				assets: 'build'
			}),

			// Мобільні кадри лендінгу (static/landing-shots/m-*.jpg) знімає
			// tools/shots.mjs --mobile — ПІСЛЯ збірки. Поки їх немає, пререндер
			// не має падати на 404 (на сторінці для них є запасний ПК-кадр).
			prerender: {
				handleHttpError: ({ path, message }) => {
					if (path.startsWith('/landing-shots/m-')) return;
					throw new Error(message);
				}
			}
		})
	],

	server: {
		port: 5173,
		proxy: {
			// дев-проксі: фронт ходить на свій же origin, vite транслює на бекенд.
			// На проді те саме робить reverse-proxy (m1id.xyz → /api).
			// Порт 8080, щоб не перетинатися зі старим мок-сервером MyStat на 8000.
			'/api': 'http://127.0.0.1:8080'
		}
	},

	// хостинг: фронт завжди слухає РІВНО цей порт,
	// щоб зовнішній проксі не «поїхав»
	preview: {
		host: '0.0.0.0',
		port: 4173,
		strictPort: true,
		// vite 8 ріже запити з чужим Host (DNS-rebinding guard):
		// проксі приходить сюди з цим Host. Домен — з .env (M1ID_DOMAIN).
		allowedHosts: [DOMAIN, `m.${DOMAIN}`, `www.${DOMAIN}`, `mapi.${DOMAIN}`, 'localhost']
	}
};
});
