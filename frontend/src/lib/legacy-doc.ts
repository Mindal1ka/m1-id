/**
 * Витяг тексту і зображень зі старих бінарних документів Word 97–2003 (.doc).
 *
 * docx-preview працює лише з OOXML (.docx), тому .doc парсимо самі:
 * CFB (OLE2) → FIB → CLX (piece table) → текст із WordDocument-стріму.
 * Форматування не зберігається; зображення з Data-стріму витягуємо
 * «карувінгом» (за сигнатурами JPEG/PNG) і показуємо окремою галереєю
 * під текстом — порядок у тексті не відтворюємо, але картинки видно.
 *
 * Спека: [MS-CFB] + [MS-DOC] (FibBase, fibRgLw97, Pcdt/PlcPcd/Pcd),
 * зображення — [MS-ODRAW] (Data-стрім).
 */
import * as CFBns from 'cfb';

// cfb — CJS-пакет: залежно від інтеропа read лежить або на просторі
// імен, або на default
const CFB = ((CFBns as unknown as { read?: unknown }).read
	? CFBns
	: (CFBns as unknown as { default: typeof CFBns }).default) as typeof CFBns;

export interface DocExtract {
	/** очищений текст документа (без форматування) */
	text: string;
	/** у Data-стрімі є вбудовані об'єкти (зображення/OLE) */
	hasMedia: boolean;
	/** вбудовані зображення (JPEG/PNG), витягнуті з Data-стріму */
	images: DocImage[];
}

export interface DocImage {
	/** mime-тип для Blob */
	mime: 'image/jpeg' | 'image/png';
	bytes: Uint8Array;
}

/** lid → кодова сторінка для 8-бітних шматків тексту (CP125x) */
const LID_CP: Record<number, string> = {
	0x0419: 'windows-1251', // російська
	0x0422: 'windows-1251', // українська
	0x0423: 'windows-1251', // білоруська
	0x0402: 'windows-1251', // болгарська
	0x0819: 'windows-1251',
	0x0405: 'windows-1250', // чеська
	0x040e: 'windows-1250', // угорська
	0x0415: 'windows-1250', // польська
	0x0418: 'windows-1250', // румунська
	0x041b: 'windows-1250', // словацька
	0x0424: 'windows-1250' // словенська
};

function cpFor(lid: number): string {
	return LID_CP[lid] ?? 'windows-1252';
}

function decode(bytes: Uint8Array, cp: string): string {
	try {
		return new TextDecoder(cp).decode(bytes);
	} catch {
		return new TextDecoder('windows-1252').decode(bytes);
	}
}

/**
 * Витяг тексту і зображень з бінарного .doc. Кидає Error з повідомленням
 * українською, якщо документ зашифрований або не схожий на Word.
 */
export function extractDoc(data: Uint8Array): DocExtract {
	const cfb = CFB.read(data, { type: 'array' });
	const wdEntry = CFB.find(cfb, 'WordDocument') as { content?: Uint8Array } | null;
	if (!wdEntry || !wdEntry.content) {
		throw new Error('Це не документ Word (.doc): немає WordDocument-стріму');
	}

	// Data-стрім: тіла вбудованих об'єктів/зображень
	const dataEntry = CFB.find(cfb, 'Data') as { content?: Uint8Array } | null;
	const hasMedia = !!(dataEntry?.content && dataEntry.content.length > 8);
	const images = dataEntry?.content ? carveImages(dataEntry.content) : [];

	const word = new Uint8Array(wdEntry.content);
	const dv = new DataView(word.buffer, word.byteOffset, word.byteLength);

	const wIdent = dv.getUint16(0, true);
	if (wIdent !== 0xa5ec) {
		throw new Error('Невідомий бінарний формат .doc');
	}
	const nFib = dv.getUint16(2, true);
	const lid = dv.getUint16(6, true);
	const flags = dv.getUint16(0x0a, true);
	if (flags & 0x0100) {
		throw new Error('Документ захищено паролем — перегляд неможливий');
	}

	let raw = '';
	if (nFib >= 0x00c1 && !(flags & 0x0004 && false)) {
		// Word97+: текст у piece table (CLX у табличному стрімі)
		const tblEntry = CFB.find(cfb, flags & 0x0200 ? '1Table' : '0Table') as
			| { content?: Uint8Array }
			| null;
		const fcClx = dv.getUint32(0x1a2, true);
		const lcbClx = dv.getUint32(0x1a6, true);
		// fibRgLw97[3] = ccpText — кількість символів основного тексту
		const ccpText = dv.getUint32(0x4c, true);
		if (tblEntry?.content && lcbClx > 0) {
			raw = readPieces(
				new Uint8Array(tblEntry.content),
				word,
				fcClx,
				lcbClx,
				ccpText,
				lid
			);
		}
	}
	if (!raw) {
		// до-Word97: суцільний текст fcMin..fcMac із FibBase
		const fcMin = dv.getUint32(0x18, true);
		const fcMac = dv.getUint32(0x1c, true);
		if (fcMac > fcMin && fcMac <= word.length) {
			raw = decode(word.subarray(fcMin, fcMac), cpFor(lid));
		}
	}
	if (!raw) {
		throw new Error('Не вдалося витягти текст зі старого .doc');
	}
	return { text: cleanup(raw), hasMedia, images };
}

/**
 * Карвінг зображень із Data-стріму: шукаємо сигнатури JPEG/PNG і вирізаємо
 * від початку до кінця. В Data-стрімі зображення лежать усередині Office
 * Art blip-записів ([MS-ODRAW]) — самі байти картинки зазвичай збережені
 * verbatim, тому сигнатурний пошук працює надійно.
 *
 * GIF/BMP/WMF/EMF не карвуємо: GIF надто легко хибно впізнати всередині
 * інших даних, BMP («BM») — повністю неспецифічний, WMF/EMF браузер
 * сам не показує.
 */
function carveImages(data: Uint8Array): DocImage[] {
	const out: DocImage[] = [];
	const MAX_IMG = 24; // розумна стеля, щоб не з'їсти пам'ять на смітті
	const MIN_IMG_BYTES = 256; // менше — майже напевно збіг, не картинка

	let pos = 0;
	while (pos < data.length - 8 && out.length < MAX_IMG) {
		// JPEG: FF D8 FF (третій байт — маркер SOI/E0/E1 тощо)
		if (data[pos] === 0xff && data[pos + 1] === 0xd8 && data[pos + 2] === 0xff) {
			const end = findJpegEnd(data, pos);
			if (end > pos + MIN_IMG_BYTES) {
				out.push({ mime: 'image/jpeg', bytes: data.slice(pos, end) });
				pos = end;
				continue;
			}
		}
		// PNG: 89 50 4E 47 0D 0A 1A 0A … IEND + CRC
		if (
			data[pos] === 0x89 &&
			data[pos + 1] === 0x50 &&
			data[pos + 2] === 0x4e &&
			data[pos + 3] === 0x47 &&
			data[pos + 4] === 0x0d &&
			data[pos + 5] === 0x0a &&
			data[pos + 6] === 0x1a &&
			data[pos + 7] === 0x0a
		) {
			const end = findPngEnd(data, pos);
			if (end > pos + MIN_IMG_BYTES) {
				out.push({ mime: 'image/png', bytes: data.slice(pos, end) });
				pos = end;
				continue;
			}
		}
		pos++;
	}
	return out;
}

/** Кінець JPEG = маркер EOI (FF D9). Пошук по структурі маркерів. */
function findJpegEnd(data: Uint8Array, start: number): number {
	let i = start + 2;
	while (i < data.length - 1) {
		if (data[i] !== 0xff) {
			i++;
			continue;
		}
		const marker = data[i + 1];
		if (marker === 0xff) {
			i++;
			continue;
		}
		// EOI — кінець
		if (marker === 0xd9) return i + 2;
		// маркери без довжини
		if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) {
			i += 2;
			continue;
		}
		// сегмент із довжиною
		const len = (data[i + 2] << 8) | data[i + 3];
		if (len < 2) return -1;
		i += 2 + len;
	}
	// пошкоджений потік — беремо до кінця стріму
	return data.length;
}

/** Кінець PNG = чанк IEND (довжина 0 + "IEND" + CRC = 12 байтів). */
function findPngEnd(data: Uint8Array, start: number): number {
	const dv = new DataView(data.buffer, data.byteOffset, data.byteLength);
	let i = start + 8; // одразу після сигнатури
	while (i + 12 <= data.length) {
		const len = dv.getUint32(i, false); // PNG: big-endian
		if (len > 0x7fffff00) return -1; // нереалістична довжина — не PNG
		const isIend =
			data[i + 4] === 0x49 && // I
			data[i + 5] === 0x45 && // E
			data[i + 6] === 0x4e && // N
			data[i + 7] === 0x44; // D
		const chunkEnd = i + 12 + len;
		if (isIend) return Math.min(chunkEnd, data.length);
		i = chunkEnd;
	}
	return data.length;
}

/** Обхід CLX: пропускаємо Prc, читаємо Pcdt (piece table). */
function readPieces(
	table: Uint8Array,
	word: Uint8Array,
	fcClx: number,
	lcbClx: number,
	ccpText: number,
	lid: number
): string {
	if (fcClx >= table.length) return '';
	const tdv = new DataView(table.buffer, table.byteOffset, table.byteLength);
	const tEnd = Math.min(fcClx + lcbClx, table.length);
	let pos = fcClx;
	while (pos < tEnd) {
		const clxt = table[pos];
		if (clxt === 0x01) {
			// Prc — ревізія властивостей, пропускаємо (cbGrpprl + байти)
			pos += 3 + tdv.getUint16(pos + 1, true);
		} else if (clxt === 0x02) {
			// Pcdt — сама piece table
			const lcb = tdv.getUint32(pos + 1, true);
			const pStart = pos + 5;
			const n = Math.floor((lcb - 4) / 12);
			if (n <= 0) return '';
			const pcdOff = pStart + (n + 1) * 4;
			const cpAt = (i: number): number => tdv.getUint32(pStart + i * 4, true);
			let out = '';
			for (let i = 0; i < n; i++) {
				const c0 = cpAt(i);
				// CP-простір вкриває і основний текст, і виноски/колонтитули —
				// беремо лише основний документ [0, ccpText)
				if (c0 >= ccpText) break;
				const cnt = Math.min(cpAt(i + 1), ccpText) - c0;
				if (cnt <= 0) continue;
				const fcRaw = tdv.getUint32(pcdOff + i * 8 + 2, true);
				const compressed = (fcRaw & 0x40000000) !== 0;
				const fc = fcRaw & 0x3fffffff;
				if (compressed) {
					// 8-бітні символи в CP125x, зсув = fc/2
					const off = Math.floor(fc / 2);
					if (off + cnt > word.length) continue;
					out += decode(word.subarray(off, off + cnt), cpFor(lid));
				} else {
					// UTF-16LE
					const off = fc;
					if (off + cnt * 2 > word.length) continue;
					out += decode(word.subarray(off, off + cnt * 2), 'utf-16le');
				}
			}
			return out;
		} else {
			break; // невідомий блок — далі не парсимо
		}
	}
	return '';
}

/** Керуючі символи MS-DOC → звичайний текст. */
function cleanup(raw: string): string {
	return raw
		.replace(/\r\n?/g, '\n')
		.replace(/\x07/g, '\n') // кінець комірки/рядка таблиці
		.replace(/[\x0b\x0c\x0e]/g, '\n') // перенос рядка/сторінки/колонки
		.replace(/\x1e/g, '-') // нерозривний дефіс
		// поля Word (гіперлінки тощо): лишаємо лише РЕЗУЛЬТАТ після \x14,
		// а службовий текст інструкції (\x13…\x14) викидаємо
		.replace(/\x13[^\x14\x15]*\x14/g, '')
		.replace(/\x13[^\x15]*\x15/g, '')
		.replace(/\x1f/g, '') // м'який (опціональний) дефіс
		.replace(/[\x13\x14\x15]/g, '') // службові символи полів
		.replace(/[\x01\x02\x05\x08]/g, '') // плейсхолдери об'єктів/виносок
		.replace(/[\x00-\x06\x10-\x1a\x1c-\x1f\x7f]/g, '')
		.replace(/[ \t]{2,}/g, ' ')
		.replace(/\n{3,}/g, '\n\n')
		.trim();
}