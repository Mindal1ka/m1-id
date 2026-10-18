/**
 * Мінімальний безпечний Markdown ⇄ HTML для нотаток.
 *
 * renderMarkdown: спершу ВЕСЬ текст екранується, і лише потім розставляються
 * власні теги, тож «сирий» HTML користувача не потрапляє у вивід. Посилання
 * проходять через safeUrl (javascript:/data: → '#').
 * Підтримка: заголовки #–###, **жирний**, *курсив*, ~~закреслений~~, `код`,
 * блоки ```код```, списки (-, *, 1.), чекбокси (- [ ] / - [x]), цитати (>),
 * лінії (---), посилання [текст](url), голі https://…, екранування \*,
 * та прикріплені файли `file:<token>` (→ чип; див. `chipHtml`).
 *
 * htmlToMarkdown: зворотній шлях для «звичайного» (Word-подібного) редактора.
 * Редактор тримає в DOM лише те, що вміє renderMarkdown, тож
 * md → html → md не втрачає змісту.
 */
import { safeUrl } from '$lib/sanitize';
import type { FileItem } from '$lib/api/client';
import { badgeOf, catOf, fmtSize } from './fileUtils';

function esc(s: string): string {
	return s
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;')
		.replace(/'/g, '&#39;');
}

/** Стан файла для чипа: об'єкт — відомий; 'loading' — список ще вантажиться;
 *  null — немає серед файлів користувача (видалений або чужий токен). */
export type ChipState = FileItem | 'loading' | null;

export function chipHtml(token: string, st: ChipState): string {
	const base = `data-ftoken="${esc(token)}" contenteditable="false"`;
	if (st === 'loading') {
		return `<span class="fchip loading" ${base}><span class="fn">файл…</span></span>`;
	}
	if (!st) {
		return `<span class="fchip missing" ${base}><span class="fx">?</span><span class="fn">файл недоступний</span></span>`;
	}
	return (
		`<span class="fchip ${catOf(st)}" ${base} title="${esc(st.name)}">` +
		`<span class="fx">${esc(badgeOf(st))}</span>` +
		`<span class="fn">${esc(st.name)}</span>` +
		`<span class="fs">${esc(fmtSize(st.size))}</span></span>`
	);
}

const FILE_REF = /(^|[^A-Za-z0-9])file:([A-Za-z0-9]{16})(?![A-Za-z0-9])/g;

export interface RenderOpts {
	/** Як показати `file:<token>`; без нього всі токени «недоступні». */
	resolve?: (token: string) => ChipState;
}

/** Інлайн-розмітка поверх сирого рядка (екранування робимо тут). */
function inline(src: string, opts: RenderOpts): string {
	const stash: string[] = [];
	const put = (html: string): string => {
		stash.push(html);
		return `\u0001${stash.length - 1}\u0001`;
	};
	// \* \# … → літерал (захована до кінця, щоб не потрапити під розмітку)
	let t = src.replace(/\\([\\`*_~[\]#>+\-.!])/g, (_m, ch: string) => put(esc(ch)));
	t = esc(t).replace(/`([^`]+)`/g, (_m, c: string) => put(`<code>${c}</code>`));
	t = t.replace(FILE_REF, (_m, pre: string, tok: string) =>
		pre + put(chipHtml(tok, opts.resolve ? opts.resolve(tok) : null))
	);
	t = t
		.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, text: string, url: string) => {
			const href = safeUrl(url.replace(/&amp;/g, '&'));
			return href === '#'
				? text
				: `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${text}</a>`;
		})
		.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, (_m, pre: string, url: string) => {
			const href = safeUrl(url.replace(/&amp;/g, '&'));
			return href === '#'
				? pre + url
				: `${pre}<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${url}</a>`;
		})
		.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
		.replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')
		.replace(/~~([^~]+)~~/g, '<del>$1</del>');
	return t.replace(/\u0001(\d+)\u0001/g, (_m, i: string) => stash[Number(i)] ?? '');
}

export function renderMarkdown(md: string, opts: RenderOpts = {}): string {
	const lines = md.replace(/\r\n?/g, '\n').split('\n');
	const out: string[] = [];
	let i = 0;
	let para: string[] = [];
	let quote: string[] = [];
	let list: { tag: 'ul' | 'ol'; items: string[] } | null = null;

	const flushPara = () => {
		if (para.length) out.push(`<p>${para.map((l) => inline(l, opts)).join('<br>')}</p>`);
		para = [];
	};
	const flushQuote = () => {
		if (quote.length) {
			out.push(`<blockquote>${quote.map((l) => inline(l, opts)).join('<br>')}</blockquote>`);
		}
		quote = [];
	};
	const flushList = () => {
		if (list) out.push(`<${list.tag}>${list.items.join('')}</${list.tag}>`);
		list = null;
	};
	const flushAll = () => {
		flushPara();
		flushQuote();
		flushList();
	};

	while (i < lines.length) {
		const line = lines[i];

		if (/^```/.test(line)) {
			flushAll();
			const buf: string[] = [];
			i++;
			while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
			i++; // закриваюча ```
			out.push(`<pre><code>${esc(buf.join('\n'))}</code></pre>`);
			continue;
		}

		if (!line.trim()) {
			flushAll();
			i++;
			continue;
		}

		const h = line.match(/^(#{1,3})\s+(.*)$/);
		if (h) {
			flushAll();
			out.push(`<h${h[1].length}>${inline(h[2], opts)}</h${h[1].length}>`);
			i++;
			continue;
		}

		if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
			flushAll();
			out.push('<hr>');
			i++;
			continue;
		}

		const q = line.match(/^>\s?(.*)$/);
		if (q) {
			flushPara();
			flushList();
			quote.push(q[1]);
			i++;
			continue;
		}

		const li = line.match(/^\s*([-*+]|\d+\.)\s+(.*)$/);
		if (li) {
			flushPara();
			flushQuote();
			const tag = /\d/.test(li[1]) ? 'ol' : 'ul';
			if (list && list.tag !== tag) flushList();
			list ??= { tag, items: [] };
			const task = li[2].match(/^\[( |x|X)\]\s+(.*)$/);
			list.items.push(
				task
					? `<li class="task${task[1] === ' ' ? '' : ' done'}"><span class="tcheck" contenteditable="false"></span>${inline(task[2], opts)}</li>`
					: `<li>${inline(li[2], opts)}</li>`
			);
			i++;
			continue;
		}

		flushQuote();
		flushList();
		para.push(line);
		i++;
	}
	flushAll();
	return out.join('');
}

// ---------------------------------------------------------------- HTML → Markdown

/** Екранує службові символи в звичайному тексті. */
function escText(s: string): string {
	return s
		.replace(/ /g, ' ')
		.replace(/\\/g, '\\\\')
		.replace(/([*`~[\]])/g, '\\$1');
}

/** Службовий початок рядка (`# `, `> `, `- `, `1. `, `---`, ```` ``` ````) → літерал. */
function escLineStart(line: string): string {
	if (/^#{1,3}\s/.test(line)) return '\\' + line;
	if (/^>/.test(line)) return '\\' + line;
	if (/^[-+]\s/.test(line)) return '\\' + line;
	if (/^\s*([-_])\1{2,}\s*$/.test(line)) return '\\' + line;
	if (/^```/.test(line)) return '\\' + line;
	if (/^\d+\.\s/.test(line)) return line.replace('.', '\\.');
	return line;
}

const isEl = (n: Node): n is HTMLElement => n.nodeType === 1;
const BLOCK_TAGS = new Set([
	'P', 'DIV', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'UL', 'OL', 'LI',
	'BLOCKQUOTE', 'PRE', 'HR', 'TABLE'
]);

function inlineMd(nodes: Node[]): string {
	let out = '';
	nodes.forEach((n, idx) => {
		if (n.nodeType === 3) {
			out += escText(n.nodeValue ?? '');
			return;
		}
		if (!isEl(n)) return;
		const tag = n.tagName;
		const kids = Array.from(n.childNodes);
		const wrap = (m: string): string => {
			const inner = inlineMd(kids);
			if (!inner.trim()) return inner;
			const lead = inner.match(/^\s*/)![0];
			const trail = inner.match(/\s*$/)![0];
			return lead + m + inner.trim() + m + trail;
		};
		if (n.dataset.ftoken) {
			const next = nodes[idx + 1];
			const needAfter =
				!!next && !(next.nodeType === 3 && /^\s/.test(next.nodeValue ?? '')) &&
				!(isEl(next) && next.tagName === 'BR');
			const needBefore = /[A-Za-z0-9]$/.test(out);
			out += `${needBefore ? ' ' : ''}file:${n.dataset.ftoken}${needAfter ? ' ' : ''}`;
			return;
		}
		if (n.classList.contains('tcheck')) return;
		switch (tag) {
			case 'BR':
				out += '\n';
				break;
			case 'B':
			case 'STRONG':
				out += wrap('**');
				break;
			case 'I':
			case 'EM':
				out += wrap('*');
				break;
			case 'S':
			case 'STRIKE':
			case 'DEL':
				out += wrap('~~');
				break;
			case 'CODE': {
				const t = n.textContent ?? '';
				out += t ? '`' + t.replace(/`/g, "'") + '`' : '';
				break;
			}
			case 'A': {
				const href = n.getAttribute('href') ?? '';
				const text = inlineMd(kids);
				out += !href || href === '#' ? text : text.trim() === escText(href) ? href : `[${text}](${href})`;
				break;
			}
			default:
				out += inlineMd(kids);
		}
	});
	return out;
}

/** Рядки абзацу: службовий початок кожного рядка екранується. */
function paragraphMd(nodes: Node[]): string {
	const text = inlineMd(nodes).replace(/[ \t]+\n/g, '\n').trim();
	return text
		.split('\n')
		.map((l) => escLineStart(l))
		.join('\n');
}

function blocksMd(parent: Node, out: string[]): void {
	let run: Node[] = [];
	const flush = () => {
		if (run.length) {
			const p = paragraphMd(run);
			if (p) out.push(p);
		}
		run = [];
	};
	for (const n of Array.from(parent.childNodes)) {
		if (!isEl(n) || !BLOCK_TAGS.has(n.tagName)) {
			run.push(n);
			continue;
		}
		flush();
		const tag = n.tagName;
		const kids = Array.from(n.childNodes);
		if (/^H[1-6]$/.test(tag)) {
			const lvl = Math.min(3, Number(tag[1]));
			const t = inlineMd(kids).replace(/\s*\n\s*/g, ' ').trim();
			if (t) out.push('#'.repeat(lvl) + ' ' + t);
		} else if (tag === 'UL' || tag === 'OL') {
			const items: string[] = [];
			let num = 1;
			for (const li of Array.from(n.children)) {
				if (li.tagName !== 'LI') continue;
				const t = inlineMd(Array.from(li.childNodes)).replace(/\s*\n\s*/g, ' ').trim();
				if (li.classList.contains('task')) {
					items.push(`- [${li.classList.contains('done') ? 'x' : ' '}] ${t}`);
				} else if (tag === 'OL') {
					items.push(`${num++}. ${t}`);
				} else {
					items.push(`- ${t}`);
				}
			}
			if (items.length) out.push(items.join('\n'));
		} else if (tag === 'BLOCKQUOTE') {
			const inner: string[] = [];
			blocksMd(n, inner);
			const t = inner.join('\n').split('\n').map((l) => '> ' + l).join('\n');
			if (inner.length) out.push(t);
		} else if (tag === 'PRE') {
			out.push('```\n' + (n.textContent ?? '').replace(/\n$/, '') + '\n```');
		} else if (tag === 'HR') {
			out.push('---');
		} else if (tag === 'LI') {
			const t = inlineMd(kids).trim();
			if (t) out.push('- ' + t);
		} else if (kids.some((k) => isEl(k) && BLOCK_TAGS.has(k.tagName))) {
			blocksMd(n, out); // <div> з вкладеними блоками
		} else {
			const p = paragraphMd(kids);
			if (p) out.push(p);
		}
	}
	flush();
}

export function htmlToMarkdown(root: HTMLElement): string {
	const out: string[] = [];
	blocksMd(root, out);
	return out.join('\n\n').replace(/\n{3,}/g, '\n\n').trim();
}
