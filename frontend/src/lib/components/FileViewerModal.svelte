<script lang="ts">
	import {
		Download,
		ExternalLink,
		Eye,
		File,
		FileArchive,
		FileText,
		Image,
		Loader2,
		X
	} from '@lucide/svelte';
	import { fetchFile, ApiError } from '$lib/api/client';
	import { friendlyError } from '$lib/errors';
	import { untrack, tick } from 'svelte';
	import { stagger, pressable, blurFade, springIn, motionOK, ease, AnimatedNumber } from '$lib/motion';
	import { focusTrap, inertBackground } from '$lib/actions/focusTrap';
	import { portal } from '$lib/actions/portal';

	/**
	 * Переглядач файлів ДЗ БЕЗ завантаження: PDF (iframe), зображення, txt,
	 * DOCX (docx-preview → HTML), ZIP (JSZip → список → вміст на клік).
	 * Кнопка «Спробувати відкрити в браузері?» → тягнемо файл через
	 * бекенд-проксі /api/app/files/view і рендеримо локально.
	 */
	let {
		open = false,
		url = '',
		name = '',
		onclose = () => {}
	}: {
		open?: boolean;
		url?: string;
		name?: string;
		onclose?: () => void;
	} = $props();

	type Kind = 'pdf' | 'image' | 'text' | 'docx' | 'doc' | 'zip' | 'gallery' | 'other';

	let stage = $state<'ask' | 'loading' | 'view' | 'error'>('ask');
	let errMsg = $state('');
	// технічна деталі помилки (статус/код/тип) — допомагає зрозуміти причину
	let errDetail = $state('');
	let fileName = $state('');
	// прогрес завантаження файлу (байти; total=0 — довжина невідома)
	let prog = $state({ loaded: 0, total: 0 });
	let kind = $state<Kind>('other');
	let blob = $state<Blob | null>(null);
	let objectUrl = $state('');
	let textContent = $state('');
	let docText = $state('');
	let docHasMedia = $state(false);
	let docImageUrls = $state<string[]>([]);
	let officeOpen = $state(false);

	// Office Online рендерить публічний URL на боці Microsoft — єдиний
	// спосіб показати повний .doc (з зображеннями) без конвертера на сервері
	const OFFICE_VIEW = 'https://view.officeapps.live.com/op/embed.aspx?src=';
	let zipEntries = $state<Array<{ path: string; size: number }>>([]);
	// M1 Provider: власне посилання /api/v1/files/<slug> з кількома фото
	// віддає HTML-галерею — розбираємо її на список медіа
	let galleryEntries = $state<Array<{ name: string; index: number }>>([]);
	// активний вкладений файл архіву (віяло «архів → вміст»)
	let entryUrl = $state('');
	let entryName = $state('');
	let entryKind = $state<Kind>('other');
	let entryObjectUrl = $state('');
	let entryText = $state('');
	let docxContainer = $state<HTMLElement | null>(null);
	let rendering = $state(false);
	// Зум вмісту в модалці (не масштаб UI): CSS zoom на контейнері вмісту.
	// 'fit' — авто-вписування (дефолт), 'manual' — ручні −/+ (25–300%)
	let zoomArea = $state<HTMLElement | null>(null);
	let zoomMode = $state<'fit' | 'manual'>('fit');
	let zoom = $state(1);
	let fitZoom = $state(1);
	let effZoom = $derived(zoomMode === 'fit' ? fitZoom : zoom);
	// поточний переглядуваний kind: головний файл або вкладений з архіву
	const dkind = $derived(entryUrl ? entryKind : kind);
	const zoomable = $derived(
		dkind === 'image' || dkind === 'text' || dkind === 'docx' || dkind === 'doc'
	);
	// guard від повторного рендера: effect читає rendering → без ключа
	// завершення рендера тригерив би новий рендер (нескінченний цикл)
	let docxRenderedKey = $state('');

	function kindOf(fname: string, type: string): Kind {
		const f = fname.toLowerCase();
		const t = type.toLowerCase();
		if (t.includes('pdf') || f.endsWith('.pdf')) return 'pdf';
		if (t.startsWith('image/') || /\.(png|jpe?g|webp|gif|bmp|svg)$/.test(f)) return 'image';
		if (t.startsWith('text/') || /\.(txt|log|csv|md|json|py|js|ts|html|css|xml|yaml|yml)$/.test(f)) return 'text';
		if (t.includes('wordprocessingml') || /\.(docx|odt)$/.test(f)) return 'docx';
		// старий бінарний Word 97–2003: текст парсимо самі ($lib/legacy-doc)
		if (t.includes('msword') || /\.doc$/.test(f)) return 'doc';
		if (t.includes('spreadsheetml') || t.includes('presentationml')) return 'zip';
		if (/\.(zip|xlsx|pptx)$/.test(f) || t.includes('zip')) return 'zip';
		return 'other';
	}

	// іконки вкладених файлів архіву
	function entryIcon(p: string) {
		const k = kindOf(p, '');
		return k === 'image' ? Image : k === 'pdf' || k === 'text' ? FileText : k === 'docx' || k === 'doc' ? FileText : k === 'zip' ? FileArchive : File;
	}

	// лічильник поколінь: відповіді застарілих запитів ігноруються
	let gen = 0;

	function reset(): void {
		gen++;
		stage = 'ask';
		errMsg = '';
		errDetail = '';
		prog = { loaded: 0, total: 0 };
		kind = 'other';
		blob = null;
		docText = '';
		docHasMedia = false;
		if (docImageUrls.length) {
			for (const u of docImageUrls) URL.revokeObjectURL(u);
			docImageUrls = [];
		}
		officeOpen = false;
		textContent = '';
		zipEntries = [];
		galleryEntries = [];
		entryUrl = '';
		entryName = '';
		entryKind = 'other';
		entryText = '';
		if (objectUrl) { URL.revokeObjectURL(objectUrl); objectUrl = ''; }
		if (entryObjectUrl) { URL.revokeObjectURL(entryObjectUrl); entryObjectUrl = ''; }
		docxContainer = null;
		docxRenderedKey = '';
		zoomArea = null;
		zoomMode = 'fit';
		zoom = 1;
		fitZoom = 1;
	}

	// «Умістити цілком»: зображення — вписати в область (ширина/висота),
	// docx — вписати сторінку по ширині, текст/інше — 100%
	function measureFit(): void {
		const area = zoomArea;
		if (!area) { fitZoom = 1; return; }
		if (dkind === 'image') {
			const img = area.querySelector('img');
			if (img && img.naturalWidth > 0) {
				const s = Math.min(
					(area.clientWidth - 28) / img.naturalWidth,
					(area.clientHeight - 28) / img.naturalHeight,
					1
				);
				fitZoom = Math.max(0.15, Math.round(s * 100) / 100);
			}
		} else if (dkind === 'docx') {
			const page = docxContainer?.querySelector('section.docx') as HTMLElement | null;
			if (page && page.offsetWidth > 0) {
				fitZoom = Math.max(0.15, Math.min(1, (area.clientWidth - 40) / page.offsetWidth));
			}
		} else {
			fitZoom = 1;
		}
	}

	/** Плавна зміна масштабу: нове значення zoom ставимо одразу (правильна
	 *  розкладка/прокрутка), а візуально доганяємо transform-ом (FLIP). */
	async function animateZoom(prev: number): Promise<void> {
		await tick();
		if (!motionOK() || !zoomArea || !prev || !effZoom) return;
		const ratio = prev / effZoom;
		if (Math.abs(ratio - 1) < 0.01) return;
		const els = zoomArea.querySelectorAll<HTMLElement>('.img-view, .txt-view, .docx-inner, .docimgs');
		els.forEach((el) => {
			el.style.transformOrigin = '50% 0';
			el.animate([{ transform: `scale(${ratio})` }, { transform: 'scale(1)' }], {
				duration: 380,
				easing: ease('out')
			});
		});
	}

	function zoomBy(d: number): void {
		const prev = effZoom;
		zoom = Math.min(3, Math.max(0.25, Math.round((effZoom + d) * 10) / 10));
		zoomMode = 'manual';
		void animateZoom(prev);
	}

	function zoomFit(): void {
		const prev = effZoom;
		zoomMode = 'fit';
		void animateZoom(prev);
	}

	// після зміни файлу/вкладеного — перерахувати дефолтний fit
	// (docx рахує renderDocx після рендера)
	$effect(() => {
		if (stage !== 'view') return;
		void dkind;
		const key = entryUrl ? 'e:' + entryName : 'main';
		void key;
		if (dkind !== 'docx') setTimeout(measureFit, 0);
	});

	$effect(() => {
		// ГАРД від циклу: reset() сам читає objectUrl/entryObjectUrl/
		// docImageUrls — без untrack ефект залежав би від них, і створення
		// blob у confirmView() перезапускало ефект → reset() посеред
		// завантаження: stage знову 'ask', blob відкликаний → переглядач
		// «повертався до питання» і давав blob: ERR_FILE_NOT_FOUND.
		if (open) {
			untrack(() => reset());
			fileName = name;
		}
	});

	/** Лишає в згенерованому DOCX-DOM лише безпечні URL (http/https/mailto/tel/#якір);
	 *  решта (javascript:, data: тощо) видаляється. Зовнішні посилання — у новій вкладці. */
	function sanitizeDocxDom(root: HTMLElement): void {
		const safe = (raw: string): boolean => {
			const v = raw.replace(/[\t\r\n]/g, '').trim();
			if (v.startsWith('#')) return true;
			return /^(https?:|mailto:|tel:)/i.test(v);
		};
		for (const el of Array.from(root.querySelectorAll('*'))) {
			for (const attr of Array.from(el.attributes)) {
				const n = attr.name.toLowerCase();
				if (n.startsWith('on')) { el.removeAttribute(attr.name); continue; }
				if (n === 'href' || n === 'src' || n === 'xlink:href' || n === 'action' || n === 'formaction') {
					const v = attr.value;
					const isImg = el.tagName.toLowerCase() === 'img' && n === 'src';
					// вбудовані зображення docx-preview — blob:/data:image (растр)
					const okImg = isImg && /^(blob:|data:image\/(png|jpe?g|gif|webp|bmp)[;,])/i.test(v.trim());
					if (!okImg && !safe(v)) el.removeAttribute(attr.name);
				}
			}
			if (el.tagName.toLowerCase() === 'a' && el.hasAttribute('href')
				&& !(el.getAttribute('href') ?? '').startsWith('#')) {
				el.setAttribute('target', '_blank');
				el.setAttribute('rel', 'noopener noreferrer');
			}
		}
	}

	async function renderDocx(target: Blob): Promise<void> {
		const myGen = gen;
		// docx-preview рендерить у готовий DOM-вузол: чекаємо, поки
		// Svelte змонтує контейнер, тоді рендеримо
		await new Promise((r) => setTimeout(r, 0));
		if (!docxContainer) return;
		rendering = true;
		try {
			const { renderAsync } = await import('docx-preview');
			await renderAsync(target, docxContainer, docxContainer, {
				inWrapper: true,
				breakPages: true,
				ignoreFonts: false,
				useBase64URL: true
			});
			if (myGen !== gen || !docxContainer) return; // файл змінився під час рендера
			sanitizeDocxDom(docxContainer);
			requestAnimationFrame(measureFit);
		} catch (ex) {
			// без catch застрягли б назавжди на «Рендеримо документ…»
			if (myGen !== gen) return;
			errMsg = friendlyError(ex);
			stage = 'error';
		} finally {
			rendering = false;
		}
	}

	$effect(() => {
		// docx головного файлу: контейнер з'являється після stage='view'
		if (stage === 'view' && kind === 'docx' && blob && docxContainer
			&& docxRenderedKey !== 'main') {
			docxRenderedKey = 'main';
			void renderDocx(blob);
		}
		// docx вкладеного файлу архіву
		const ekey = 'entry:' + entryName;
		if (entryUrl && entryKind === 'docx' && docxContainer
			&& docxRenderedKey !== ekey) {
			docxRenderedKey = ekey;
			const eg = gen;
			void (async () => {
				try {
					const src = await fetch(entryUrl).then((r) => r.blob());
					if (eg !== gen) return;
					await renderDocx(src);
				} catch (ex) {
					if (eg !== gen) return;
					errMsg = friendlyError(ex);
					stage = 'error';
				}
			})();
		}
	});

	async function openEntry(path: string, data: Uint8Array): Promise<void> {
		await openEntryBlob(path, new Blob([data as BlobPart]));
	}

	async function openEntryBlob(name: string, blobEntry: Blob): Promise<void> {
		if (entryObjectUrl) { URL.revokeObjectURL(entryObjectUrl); entryObjectUrl = ''; }
		entryName = name;
		entryKind = kindOf(name, '');
		entryText = '';
		if (entryKind === 'text') {
			entryText = await blobEntry.text();
		} else if (entryKind === 'doc') {
			const { extractDoc } = await import('$lib/legacy-doc');
			entryText = extractDoc(new Uint8Array(await blobEntry.arrayBuffer())).text;
		} else if (entryKind !== 'docx') {
			entryObjectUrl = URL.createObjectURL(blobEntry);
		}
		// для docx рендеримо через $effect вище (потрібен контейнер)
	}

	/** HTML-галерея M1 Provider: витягуємо список медіа зі сторінки. */
	function parseGallery(
		html: string
	): Array<{ name: string; index: number }> | null {
		const m = html.match(/M1_MEDIA\s*=\s*(\[[\s\S]*?\])\s*;/);
		if (!m) return null;
		try {
			const arr = JSON.parse(m[1]) as Array<{ name?: string }>;
			if (!Array.isArray(arr) || arr.length === 0) return null;
			return arr.map((x, i) => ({
				name: String(x?.name ?? `Файл ${i + 1}`),
				index: i
			}));
		} catch {
			return null;
		}
	}

	async function onGalleryClick(e: { name: string; index: number }): Promise<void> {
		if (!blob) return;
		docxRenderedKey = '';
		try {
			// медіа тягнемо тим самим проксі: <slug>/media/<index>
			const res = await fetchFile(
				`/api/app/files/view?url=${encodeURIComponent(url + '/media/' + e.index)}`
			);
			await openEntryBlob(e.name, res.blob);
		} catch (ex) {
			errMsg = friendlyError(ex as ApiError);
		}
	}

	async function openZip(target: Blob): Promise<void> {
		const JSZip = (await import('jszip')).default;
		const zip = await JSZip.loadAsync(target);
		const files = Object.keys(zip.files)
			.filter((p) => !zip.files[p].dir)
			.sort();
		if (files.length === 0) {
			errMsg = 'Архів порожній';
			stage = 'error';
			return;
		}
		zipEntries = await Promise.all(files.map(async (p) => ({
			path: p,
			size: (await zip.files[p].async('uint8array')).length
		})));
	}

	async function onEntryClick(path: string): Promise<void> {
		if (!blob) return;
		docxRenderedKey = '';
		try {
			const JSZip = (await import('jszip')).default;
			const zip = await JSZip.loadAsync(blob);
			const data = await zip.file(path)?.async('uint8array');
			if (!data) return;
			await openEntry(path, data);
		} catch (ex) {
			errMsg = friendlyError(ex as ApiError);
		}
	}

	function setErr(ex: unknown): void {
		errMsg = friendlyError(ex as ApiError);
		errDetail = ex instanceof ApiError
			? `HTTP ${ex.status}${ex.code ? ` · ${ex.code}` : ''}${ex.message ? ` · ${ex.message}` : ''}`
			: `${(ex as Error)?.name ?? 'Error'}: ${(ex as Error)?.message ?? String(ex)}`;
	}

	async function confirmView(): Promise<void> {
		const my = ++gen;
		stage = 'loading';
		errMsg = '';
		prog = { loaded: 0, total: 0 };
		try {
			const res = await fetchFile(
				`/api/app/files/view?url=${encodeURIComponent(url)}`,
				(loaded, total) => { if (my === gen) prog = { loaded, total }; }
			);
			if (my !== gen) return; // відкрито інший файл — ігноруємо
			blob = res.blob;
			// ім'я з посилання — часто лише токен без розширення:
			// перезаписуємо справжнім іменем з X-File-Name
			if (!fileName || fileName === 'file' || !/\.[a-z0-9]{1,6}$/i.test(fileName)) {
				fileName = res.name;
			}
			kind = kindOf(fileName, res.type);
			if (kind === 'text') {
				const txt = await res.blob.text();
				if (my !== gen) return;
				const g = parseGallery(txt);
				if (g) {
					// M1 Provider-галерея (кілька фото) — показуємо списком
					galleryEntries = g;
					kind = 'gallery';
				} else {
					textContent = txt;
				}
			} else if (kind === 'image' || kind === 'pdf') {
				objectUrl = URL.createObjectURL(res.blob);
			} else if (kind === 'doc') {
				// старий бінарний .doc: текст самі, зображення — через Office Online
				const { extractDoc } = await import('$lib/legacy-doc');
				const info = extractDoc(new Uint8Array(await res.blob.arrayBuffer()));
				if (my !== gen) return;
				docText = info.text;
				docHasMedia = info.hasMedia;
				// зображення з Data-стріму: Blob → object URL для галереї
				docImageUrls = info.images.map(
					(im) => URL.createObjectURL(new Blob([im.bytes as BlobPart], { type: im.mime }))
				);
			} else if (kind === 'zip') {
				await openZip(res.blob);
			}
			if (my !== gen) return;
			stage = 'view';
		} catch (ex) {
			if (my !== gen) return;
			setErr(ex);
			stage = 'error';
		}
	}

	async function download(): Promise<void> {
		if (!blob) {
			// стадія ask: тягнемо файл (з прогресом), зберігаємо і АВТОМАТИЧНО
			// закриваємо модалку — користувач повертається до домашки
			stage = 'loading';
			errMsg = '';
			prog = { loaded: 0, total: 0 };
			try {
				const res = await fetchFile(
					`/api/app/files/view?url=${encodeURIComponent(url)}`,
					(loaded, total) => { prog = { loaded, total }; }
				);
				const a = document.createElement('a');
				a.href = URL.createObjectURL(res.blob);
				a.download = res.name || 'file';
				a.click();
				// відкликаємо пізніше: браузер має встигнути почати download
				setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
				close();
			} catch (ex) {
				setErr(ex);
				stage = 'error';
			}
			return;
		}
		const a = document.createElement('a');
		a.href = objectUrl || URL.createObjectURL(blob);
		a.download = fileName || 'file';
		a.click();
		if (!objectUrl) URL.revokeObjectURL(a.href);
	}

	function downloadEntry(): void {
		if (!entryObjectUrl) return;
		const a = document.createElement('a');
		a.href = entryObjectUrl;
		a.download = entryName || 'file';
		a.click();
	}

	function openTab(): void {
		if (objectUrl) window.open(objectUrl, '_blank', 'noopener');
	}

	function openOffice(): void {
		officeOpen = true;
	}

	// capture + preventDefault: Esc закриває лише переглядач, а діалог під ним
	// (Dialog/деталі ДЗ) бачить defaultPrevented і лишається відкритим
	function onKeydown(e: KeyboardEvent): void {
		if (!open || e.key !== 'Escape' || e.defaultPrevented) return;
		e.preventDefault();
		close();
	}

	function close(): void {
		reset();
		onclose();
	}
</script>

<svelte:window onkeydowncapture={onKeydown} />

{#if open}
	<!-- Портал у <body> + z-index вище за Dialog: вкладений перегляд завжди
	     поверх, а діалоги під ним стають inert (фокус лише у переглядачі) -->
	<div class="fv-root" use:portal use:inertBackground>
	<div class="ovl" onclick={close} role="presentation"></div>
	<div class="panel glass" role="dialog" aria-modal="true" aria-label="Перегляд файлу"
		use:focusTrap>
		<header>
			<h3><FileText size={18} /> {fileName || 'Файл'}</h3>
			<div class="hbtns">
				{#if stage === 'view' && blob}
					<button class="mini" onclick={download} title="Завантажити">
						<Download size={14} /> Завантажити
					</button>
					{#if kind === 'pdf' || kind === 'image'}
						<button class="mini" onclick={openTab} title="У новій вкладці">
							<ExternalLink size={14} />
						</button>
					{/if}
					{#if zoomable}
						<span class="zoomctl">
							<button class="mini" onclick={() => zoomBy(-0.1)} aria-label="Зменшити" title="Зменшити">−</button>
							<span class="zval"><AnimatedNumber value={Math.round(effZoom * 100)} duration={320} format={(n) => `${n}%`} /></span>
							<button class="mini" onclick={() => zoomBy(0.1)} aria-label="Збільшити" title="Збільшити">+</button>
							<button class="mini" onclick={zoomFit} title="Умістити цілком">⤢</button>
						</span>
					{/if}
				{/if}
				<button class="x" onclick={close} aria-label="Закрити"><X size={20} /></button>
			</div>
		</header>

		{#if stage === 'ask'}
			<div class="ask" in:blurFade|global={{ duration: 300, amount: 6, y: 8 }}>
				<span class="ask-ico" in:springIn|global={{ delay: 80, start: 0.6, duration: 480 }}><FileText size={34} /></span>
				<p><b>{fileName || 'Файл завдання'}</b></p>
				<p class="dim">Спробувати відкрити в браузері?</p>
				<div class="askbtns">
					<button class="btn primary" use:pressable onclick={() => void confirmView()}>
						<Eye />
						Так, переглянути
					</button>
					<button class="btn ghost" use:pressable onclick={download}>
						<Download size={16} /> Завантажити файл
					</button>
				</div>
			</div>
		{:else if stage === 'loading'}
			<div class="center" in:blurFade|global={{ duration: 280, amount: 6 }}>
				<Loader2 size={26} class="spin" />
				<p class="dim">Завантажуємо файл…</p>
				{#if prog.loaded > 0}
					<p class="prog-num">
						{#if prog.total}
							{Math.min(100, Math.round((prog.loaded / prog.total) * 100))}%
							· {(prog.loaded / 1048576).toFixed(1)} / {(prog.total / 1048576).toFixed(1)} МБ
						{:else}
							{(prog.loaded / 1048576).toFixed(1)} МБ
						{/if}
					</p>
					<div class="progbar" role="progressbar" aria-valuemin={0} aria-valuemax={100}>
						<div
							class="progfill"
							class:indet={!prog.total}
							style:transform={prog.total
								? `scaleX(${Math.min(1, prog.loaded / prog.total)})`
								: undefined}
						></div>
					</div>
				{/if}
			</div>
		{:else if stage === 'error'}
			<div class="center" in:blurFade|global={{ duration: 280, amount: 6 }}>
				<p class="err">⚠ {errMsg}</p>
				{#if errDetail}
					<p class="dim" style="max-width:560px;word-break:break-word">{errDetail}</p>
				{/if}
				<button class="btn ghost" use:pressable onclick={() => void confirmView()}>
					Спробувати ще раз
				</button>
			</div>
		{:else if stage === 'view'}
			{#if entryUrl}
				<div class="crumb" in:blurFade|global={{ duration: 260, amount: 4, y: 4 }}>
					<button class="mini" onclick={() => { entryUrl = ''; entryName = ''; docxRenderedKey = ''; }}>
						← Архів: {zipEntries.length} файл(ів)
					</button>
					<span class="crumb-name">{entryName}</span>
				</div>
				<div class="zoomarea" bind:this={zoomArea} in:blurFade|global={{ duration: 420, amount: 10, y: 8 }}>
					{#if entryKind === 'image' && entryObjectUrl}
						<img class="img-view" style:zoom={effZoom} src={entryObjectUrl} alt={entryName} onload={() => setTimeout(measureFit, 0)} />
					{:else if entryKind === 'pdf' && entryObjectUrl}
						<iframe class="frame" src={entryObjectUrl} title={entryName}></iframe>
					{:else if entryKind === 'text' || entryKind === 'doc'}
						<pre class="txt-view" style:zoom={effZoom}>{entryText}</pre>
					{:else if entryKind === 'docx'}
						<div class="docx-wrap">
							<div class="docx-inner" style:zoom={effZoom} bind:this={docxContainer}></div>
						</div>
					{:else}
						<div class="center">
							<p class="dim">Формат файлу не підтримується для перегляду</p>
							<button class="btn ghost" onclick={downloadEntry}><Download size={16} /> Завантажити</button>
						</div>
					{/if}
				</div>
			{:else if kind === 'zip'}
				<ul class="zlist" use:stagger={{ step: 35, y: 10, max: 12 }} in:blurFade|global={{ duration: 300, amount: 5 }}>
					{#each zipEntries as e (e.path)}
						{@const Icon = entryIcon(e.path)}
						<li>
							<button class="flink" use:pressable={{ scale: 0.985 }} onclick={() => void onEntryClick(e.path)}>
								<Icon size={15} />
								{e.path}
								<small class="dim">{(e.size / 1024).toFixed(0)} КБ</small>
							</button>
						</li>
					{/each}
				</ul>
			{:else if kind === 'gallery'}
				<ul class="zlist" use:stagger={{ step: 35, y: 10, max: 12 }} in:blurFade|global={{ duration: 300, amount: 5 }}>
					{#each galleryEntries as e, i (e.index)}
						{@const Icon = entryIcon(e.name)}
						<li>
							<button class="flink" use:pressable={{ scale: 0.985 }} onclick={() => void onGalleryClick(e)}>
								<Icon size={15} />
								{e.name}
								<small class="dim">{i + 1} / {galleryEntries.length}</small>
							</button>
						</li>
					{/each}
				</ul>
			{:else}
				<div class="viewbox" in:blurFade|global={{ duration: 480, amount: 12, y: 10 }}>
					{#if kind === 'pdf' && objectUrl}
						<iframe class="frame" src={objectUrl} title={fileName}></iframe>
					{:else}
						<div class="zoomarea" bind:this={zoomArea}>
							{#if kind === 'image' && objectUrl}
								<img class="img-view" style:zoom={effZoom} src={objectUrl} alt={fileName} onload={() => setTimeout(measureFit, 0)} />
							{:else if kind === 'text'}
								<pre class="txt-view" style:zoom={effZoom}>{textContent}</pre>
							{:else if kind === 'doc' && officeOpen}
								<iframe class="frame" src={OFFICE_VIEW + encodeURIComponent(url)} title={fileName}></iframe>
							{:else if kind === 'doc'}
								<div class="docnote">
									<span>Старий формат .doc — текст без форматування.</span>
									<button class="mini" onclick={openOffice}>Office Online (з зображеннями)</button>
								</div>
								{#if docImageUrls.length}
									<div class="docimgs" style:zoom={effZoom}>
										{#each docImageUrls as du, i (du)}
											<a href={du} target="_blank" rel="noreferrer">
												<img src={du} alt="Зображення {i + 1} з .doc" loading="lazy" />
											</a>
										{/each}
									</div>
								{/if}
								{#if docText.trim()}
									<pre class="txt-view" style:zoom={effZoom}>{docText}</pre>
								{:else if docImageUrls.length === 0 && docHasMedia}
									<div class="center">
										<FileText size={26} />
										<p class="dim" style="text-align:center">
											У документі лише зображення — браузер сам їх не показує.<br />
											Відкрийте через Office Online або завантажте файл.
										</p>
										<button class="btn primary" onclick={openOffice}>
											<ExternalLink size={16} /> Office Online
										</button>
									</div>
								{:else if !docImageUrls.length}
									<pre class="txt-view" style:zoom={effZoom}>{docText}</pre>
								{/if}
							{:else if kind === 'docx'}
								{#if rendering || !docxContainer}
									<div class="center"><Loader2 size={26} class="spin" /><p class="dim">Рендеримо документ…</p></div>
								{/if}
								<div class="docx-wrap">
									<div class="docx-inner" style:zoom={effZoom} bind:this={docxContainer}></div>
								</div>
							{:else}
								<div class="center">
									<p class="dim">Формат не підтримується для перегляду</p>
									<button class="btn ghost" onclick={download}><Download size={16} /> Завантажити</button>
								</div>
							{/if}
						</div>
					{/if}
				</div>
			{/if}
		{/if}
	</div>
	</div>
{/if}

<style>
	.ovl {
		position: fixed;
		inset: 0;
		background: rgba(5, 7, 12, 0.72);
		-webkit-backdrop-filter: blur(calc(6px + 0px));
		backdrop-filter: blur(calc(6px + 0px));
		z-index: calc(var(--z-modal, 810) + 20);
		animation: fv-fade 0.18s ease;
	}
	/* lite: без backdrop-filter, темніший суцільний фон */
	:global(html[data-perf='lite']) .ovl {
		-webkit-backdrop-filter: none;
		backdrop-filter: none;
		background: rgba(5, 7, 12, 0.85);
	}

	.panel {
		position: fixed;
		left: 50%;
		top: 50%;
		transform: translate(-50%, -50%);
		width: min(860px, 94vw);
		height: min(640px, 88dvh);
		display: flex;
		flex-direction: column;
		border-radius: 16px;
		z-index: calc(var(--z-modal, 810) + 21); /* ВИЩЕ за .ovl: оверлей блурить ФОН, а не панель */
		animation: fv-pop 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
		border-left: 3px solid var(--accent);
		overflow: hidden;
	}

	header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
		padding: 12px 16px;
		border-bottom: 1px solid var(--surface-2);
		flex-shrink: 0;
	}

	header h3 {
		margin: 0;
		font-size: 14.5px;
		display: inline-flex;
		align-items: center;
		gap: 8px;
		color: var(--text);
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.hbtns { display: flex; gap: 6px; align-items: center; }

	.x {
		background: none;
		border: none;
		color: var(--text-dim);
		cursor: pointer;
		padding: 6px;
		border-radius: 10px;
		display: grid;
		place-items: center;
	}
	.x:hover { background: var(--surface-2); color: var(--text); }

	.mini {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		border: 1px solid var(--glass-border, rgba(255,255,255,0.1));
		border-radius: 8px;
		background: transparent;
		color: var(--text-dim);
		font: inherit;
		font-size: 12px;
		padding: 5px 9px;
		cursor: pointer;
	}
	.mini:hover { color: var(--accent); border-color: var(--accent); }

	.ask {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 10px;
		color: var(--accent);
		padding: 24px;
		text-align: center;
	}
	.ask-ico { display: grid; }
	.ask p { margin: 0; color: var(--text); word-break: break-word; }
	.ask .dim { color: var(--text-dim); font-size: 13.5px; }

	.askbtns { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; justify-content: center; }

	.center {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 10px;
		padding: 24px;
	}

	.err { margin: 8px 0; color: var(--danger); font-size: 14px; }
	.dim { color: var(--text-dim); font-size: 12.5px; }

	/* прогрес завантаження файлу у переглядачі */
	.prog-num {
		margin: 0;
		color: var(--text);
		font-size: 13px;
		font-variant-numeric: tabular-nums;
	}
	.progbar {
		width: min(320px, 70%);
		height: 6px;
		border-radius: 99px;
		background: var(--surface-2);
		overflow: hidden;
	}
	.progfill {
		width: 100%;
		height: 100%;
		border-radius: 99px;
		background: var(--accent);
		transform-origin: left center;
		transform: scaleX(0);
		transition: transform 360ms var(--ease-out);
	}
	/* невизначений прогрес (Content-Length невідомий) — бігунець */
	.progfill.indet { width: 40%; transform: none; transition: none; animation: fv-indet 1.1s ease-in-out infinite; }
	@keyframes fv-indet {
		0% { transform: translateX(-100%); }
		100% { transform: translateX(250%); }
	}

	.viewbox { flex: 1; min-height: 0; display: flex; flex-direction: column; }

	/* область з прокруткою для зумованого вмісту (все, крім pdf) */
	.zoomarea {
		flex: 1;
		min-height: 0;
		overflow: auto;
		display: flex;
		flex-direction: column;
	}

	/* керування зумом в хедері */
	.zoomctl {
		display: inline-flex;
		align-items: center;
		gap: 4px;
	}
	.zval {
		font-size: 11.5px;
		color: var(--text-dim);
		min-width: 38px;
		text-align: center;
		user-select: none;
	}

	.frame {
		flex: 1;
		width: 100%;
		border: none;
		background: #fff;
	}

	.img-view {
		margin: auto;
		max-width: 100%;
		max-height: 100%;
		object-fit: contain;
		padding: 14px;
	}

	.txt-view {
		flex: 1;
		margin: 0;
		padding: 14px 16px;
		overflow: auto;
		white-space: pre-wrap;
		word-break: break-word;
		font-size: 13px;
		line-height: 1.55;
		color: var(--text);
		background: var(--surface-2);
	}

	.docnote {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 7px 12px;
		border: 1px solid var(--surface-2);
		font-size: 12px;
		color: var(--text-dim);
		flex-wrap: wrap;
		margin: 0 12px 4px;
		border-radius: 8px;
	}

	/* галерея зображень, витягнутих зі старого .doc (Data-стрім) */
	.docimgs {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		padding: 10px 16px;
	}
	.docimgs img {
		max-width: 240px;
		max-height: 240px;
		border-radius: 8px;
		border: 1px solid var(--surface-2);
		background: #fff;
		object-fit: contain;
		cursor: zoom-in;
	}

	.docx-wrap {
		flex: 1;
		background: #525659;
		padding: 12px 0;
	}
	.docx-inner { min-height: 100%; }
	/* аркуші docx-preview — білий «папір» по центру */
	.docx-wrap :global(.docx-wrapper) {
		background: transparent;
		padding: 0;
	}
	.docx-wrap :global(.docx-wrapper > section.docx) {
		margin: 0 auto 14px;
		box-shadow: 0 2px 14px rgba(0, 0, 0, 0.4);
	}

	.crumb {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 16px 0;
		flex-wrap: wrap;
	}
	.crumb-name { font-size: 12.5px; color: var(--text-dim); word-break: break-all; }

	.zlist { list-style: none; margin: 0; padding: 10px 16px; overflow: auto; display: flex; flex-direction: column; gap: 6px; }

	.flink {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 11px;
		border-radius: 10px;
		border: none;
		background: var(--surface-2);
		color: var(--cyan, #67d4e8);
		cursor: pointer;
		font-size: 13px;
		width: 100%;
		text-align: left;
		word-break: break-all;
	}
	.flink:hover { filter: brightness(1.15); }
	.flink small { margin-left: auto; flex-shrink: 0; }

	.center .spin, .spin { animation: fv-spin 1s linear infinite; }

	@keyframes fv-spin { to { transform: rotate(360deg); } }
	@keyframes fv-fade { from { opacity: 0; } }
	@keyframes fv-pop { from { opacity: 0; transform: translate(-50%, -46%) scale(0.96); } }
</style>
