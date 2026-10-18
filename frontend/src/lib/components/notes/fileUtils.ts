import type { FileItem } from '$lib/api/client';

/** Розмір у людському вигляді: 12 КБ, 3,4 МБ. */
export function fmtSize(n: number): string {
	if (n < 1024) return `${n} Б`;
	if (n < 1024 * 1024) return `${Math.round(n / 1024)} КБ`;
	return `${(n / 1024 / 1024).toFixed(1).replace('.', ',')} МБ`;
}

export function fmtDate(iso: string): string {
	const d = new Date(iso + (iso.endsWith('Z') ? '' : 'Z'));
	if (isNaN(d.getTime())) return '';
	return d.toLocaleDateString('uk-UA', { day: 'numeric', month: 'short', year: 'numeric' });
}

export type FileCat = 'img' | 'doc' | 'arc' | 'media' | 'code' | 'other';

const CATS: Record<FileCat, string[]> = {
	img: ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'heic', 'avif'],
	doc: ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'md', 'rtf', 'odt', 'csv'],
	arc: ['zip', 'rar', '7z', 'tar', 'gz'],
	media: ['mp3', 'wav', 'ogg', 'm4a', 'mp4', 'webm', 'mov', 'mkv', 'avi'],
	code: ['js', 'ts', 'py', 'html', 'css', 'json', 'c', 'cpp', 'cs', 'java', 'sh', 'sql', 'xml', 'yml']
	,
	other: []
};

/** Розширення (нижній регістр, без крапки) за іменем файлу. */
export function extOf(name: string): string {
	const i = name.lastIndexOf('.');
	return i > 0 ? name.slice(i + 1).toLowerCase().slice(0, 5) : '';
}

export function catOf(f: Pick<FileItem, 'orig_name' | 'name' | 'kind'>): FileCat {
	if (f.kind === 'zip') return 'arc';
	const e = extOf(f.orig_name || f.name);
	for (const c of Object.keys(CATS) as FileCat[]) if (CATS[c].includes(e)) return c;
	return 'other';
}

export function isImage(f: Pick<FileItem, 'orig_name' | 'name' | 'kind'>): boolean {
	return catOf(f) === 'img';
}

/** Мітка-бейдж типу (PDF, ZIP…). */
export function badgeOf(f: Pick<FileItem, 'orig_name' | 'name' | 'kind'>): string {
	return f.kind === 'zip' ? 'ZIP' : (extOf(f.orig_name || f.name) || 'FILE').toUpperCase();
}

export const TOKEN_RE = /file:([A-Za-z0-9]{16})(?![A-Za-z0-9])/g;

/** Токени файлів, згаданих у Markdown, у порядку появи (без дублів). */
export function tokensIn(md: string): string[] {
	const out: string[] = [];
	for (const m of md.matchAll(TOKEN_RE)) if (!out.includes(m[1])) out.push(m[1]);
	return out;
}
