/** Allow-list санітайзер HTML на DOMParser.
 *  mapi віддає довільний HTML з адмінки MyStat, який рендериться через
 *  {@html} — тому чистимо його ЖОРСТКО: парсимо в справжній DOM і
 *  заново збираємо розмітку лише з дозволених вузлів та атрибутів.
 *  Regex-підхід тут ненадійний (обходи через вкладені теги, імена
 *  атрибутів, entities), DOMParser сам декодує HTML-entities, тому
 *  перевірка значень атрибутів після парсу безпечна. */

/** Теги, що видаляються РАЗОМ ЗІ ВМІСТОМ. */
const DROP_TAGS = new Set([
	'script',
	'noscript',
	'template',
	'style',
	'frame',
	'frameset',
	'applet',
	'math',
	'textarea',
	'select',
	'iframe',
	'object',
	'embed',
	'link',
	'meta',
	'base',
	'form',
	'input',
	'button',
	'svg'
]);

/** Allow-list атрибутів ПО ТЕГАХ. Усі інші елементи залишаються
 *  БЕЗ атрибутів взагалі (ні class, ні data-* — нічого). */
const ATTR_ALLOW: Record<string, ReadonlySet<string>> = {
	a: new Set(['href', 'target', 'rel', 'title']),
	img: new Set(['src', 'alt', 'title', 'width', 'height'])
};

/** Нормалізація значення атрибута перед перевіркою схеми: браузер при
 *  навігації вирізує tab/newline/CR з URL, тому `jav\tascript:` (або
 *  `jav&#10;ascript:` після парсу) виглядає як «відносний», а кліком
 *  нормалізується до javascript:. Прибираємо ці символи ДО перевірки. */
function _normalizeUrlValue(raw: string): string {
	return raw.replace(/[\t\r\n]/g, '');
}

/** URL для href/src: дозволені http:, https:, mailto: (mailto — лише для
 *  посилань) та відносні (шлях, #якір). Для img — ЛИШЕ http(s) і відносні:
 *  data: (зокрема data:image/svg+xml) та mailto: заборонені.
 *  Protocol-relative `//host` — заборонений: він веде на зовнішній origin.
 *  javascript:, data:, vbscript: та будь-які інші схеми → заборона. */
export function urlAllowed(tag: string, raw: string): boolean {
	const value = _normalizeUrlValue(raw.trim());
	const v = value.toLowerCase();
	// protocol-relative //host → зовнішній origin, заборона
	if (v.startsWith('//')) return false;
	// немає схеми → відносний URL (шлях, #якір, ./../)
	if (!/^[a-z][a-z0-9+.-]*:/i.test(value)) return true;
	if (v.startsWith('http:') || v.startsWith('https:')) return true;
	if (tag !== 'img' && v.startsWith('mailto:')) return true;
	return false;
}

/** Безпечний URL для href з даних API: javascript:/data:/vbscript:
 *  та інші небезпечні схеми → '#'. Використовувати для ВСІХ href,
 *  що походять з API (ContactsTab, M1LinkModal, SubmitModal,
 *  TelegramPanel, PaymentsTab). tel:/mailto: навмисно НЕ в
 *  allow-list — для них є telHref()/mailtoHref() нижче. */
export function safeUrl(raw: string): string {
	const v = _normalizeUrlValue((raw ?? '').trim());
	return urlAllowed('a', v) ? v : '#';
}

/** tel:-посилання з телефону з API: залишаємо лише цифри. */
export function telHref(raw: unknown): string {
	const digits = String(raw ?? '').replace(/\D/g, '');
	return digits ? `tel:+${digits}` : '#';
}

/** mailto:-посилання з адреси з API: проста перевірка формату + кодування. */
export function mailtoHref(raw: unknown): string {
	const v = String(raw ?? '').trim();
	if (!/^[^\s@<>"',;:?&#]+@[^\s@<>"',;:?&#/]+\.[^\s@<>"',;:?&#/]+$/.test(v)) return '#';
	return 'mailto:' + encodeURI(v);
}

/** https-посилання з «голого» хоста з API (`site.com` або `https://site.com`).
 *  Схема завжди http(s); решта перевіряється через URL(). */
export function siteHref(raw: unknown): string {
	const v = String(raw ?? '').trim();
	if (!v) return '#';
	const full = /^https?:\/\//i.test(v) ? v : 'https://' + v.replace(/^\/+/, '');
	try {
		const u = new URL(full);
		if (u.protocol !== 'https:' && u.protocol !== 'http:') return '#';
		return u.href;
	} catch {
		return '#';
	}
}

function sanitizeChildren(src: Node, out: Node, doc: Document): void {
	for (const child of Array.from(src.childNodes)) {
		if (child.nodeType === 3 /* TEXT_NODE */) {
			out.appendChild(doc.createTextNode(child.nodeValue ?? ''));
			continue;
		}
		if (child.nodeType !== 1 /* ELEMENT_NODE */) continue; // коментарі тощо
		const el = child as Element;
		const tag = el.tagName.toLowerCase();
		if (DROP_TAGS.has(tag)) continue; // разом зі вмістом

		let clean: Element;
		try {
			clean = doc.createElement(tag);
		} catch {
			continue; // нестандартне ім'я тега — викидуємо вузол цілком
		}
		const allowed = ATTR_ALLOW[tag];
		for (const attr of Array.from(el.attributes)) {
			const name = attr.name.toLowerCase();
			// обробники та data-атрибути не проходять НІКОЛИ
			if (name.startsWith('on') || name.startsWith('data-')) continue;
			if (!allowed || !allowed.has(name)) continue;
			if (
				(name === 'href' || name === 'src') &&
				!urlAllowed(tag, attr.value)
			) {
				continue; // небезпечна схема → атрибут видаляється
			}
			clean.setAttribute(name, attr.value);
		}
		if (tag === 'a' && clean.getAttribute('target') === '_blank') {
			clean.setAttribute('rel', 'noopener noreferrer');
		}
		sanitizeChildren(el, clean, doc);
		out.appendChild(clean);
	}
}

/** Повертає безпечний HTML для {@html}: лише дозволені теги/атрибути,
 *  текст і структуру збережено. На сервері (немає DOM) → порожній рядок
 *  (деталі новин і так завантажуються лише на клієнті). */
export function sanitizeHtml(dirty: string): string {
	if (typeof window === 'undefined' || typeof DOMParser === 'undefined') {
		return '';
	}
	try {
		const doc = new DOMParser().parseFromString(dirty, 'text/html');
		const clean = doc.createElement('div');
		sanitizeChildren(doc.body, clean, doc);
		return clean.innerHTML;
	} catch {
		return '';
	}
}
