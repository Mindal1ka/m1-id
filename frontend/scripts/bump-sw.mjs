// Postbuild: бамп VERSION у build/sw.js + stamp у build/version.json.
// Викликається з package.json ПІСЛЯ `vite build` — у closeBundle плагіна
// build/sw.js ще не існує (статика копіюється адаптером пізніше),
// через що бамп ніколи не спрацьовував і на проді жив старий SW
// зі старим кешем (подивись git history: '[m1id] sw version bump failed').
import { readFileSync, writeFileSync, existsSync } from 'node:fs';

const sw = 'build/sw.js';
const ver = 'build/version.json';
// ВАЖЛИВО: той самий штамп, що вшитий у бандл (__BUILD_STAMP__):
// клієнт порівнює version.json з вшитим значенням — різниця = вічна
// модалка оновлення. Штамп тримає .svelte-kit/m1id-stamp.txt (120с вікно).
const stamp = (() => {
	try {
		return readFileSync('.svelte-kit/m1id-stamp.txt', 'utf8').trim();
	} catch {
		return String(Math.floor(Date.now() / 1000));
	}
})();

if (!existsSync(sw)) {
	console.warn('[m1id] bump-sw: build/sw.js відсутній — пропускаю');
	process.exit(0);
}

const src = readFileSync(sw, 'utf8');
const out = src.replace(
	/const VERSION = '(m1id-v\d+)[^']*';/,
	(_m, base) => `const VERSION = '${base}-${stamp}';`
);
if (out === src) console.warn('[m1id] bump-sw: VERSION не знайдено — патерн змінився?');
writeFileSync(sw, out);
writeFileSync(ver, JSON.stringify({ v: stamp }));
console.log('[m1id] sw version bump -> ' + stamp);
