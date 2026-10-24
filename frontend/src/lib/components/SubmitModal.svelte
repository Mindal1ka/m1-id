<script lang="ts">
	import { fade, fly, slide } from 'svelte/transition';
	import { flip } from 'svelte/animate';
	import { cubicOut } from 'svelte/easing';
	import { springIn, blurFade, shake, pop, pressable, motionOK } from '$lib/motion';
	import { Coins, FileText, FileUp, Paperclip, Send, X, Check, Settings2, FileArchive, Link2, Code2, Play, Palette, Cloud, Globe } from '@lucide/svelte';
	import { api, type HwItem } from '$lib/api/client';
	import { friendlyError } from '$lib/errors';
	import { fx } from '$lib/fx.svelte';
	import { safeUrl } from '$lib/sanitize';
	import { hwKindTag } from '$lib/app/helpers';

	let {
		open = false,
		hw = null,
		account,
		mode = 'submit',
		onclose,
		onsubmitted
	}: {
		open?: boolean;
		hw: HwItem | null;
		account: number;
		mode?: 'submit' | 'resubmit';
		onclose?: () => void;
		onsubmitted?: () => void;
	} = $props();

	const MAX_FILE = 25 * 1024 * 1024;

	// ціна здачі, як у офіційному клієнті: −2 за перездачу виконаного ДЗ,
	// −20 за здачу з дедлайном, що минув пів року тому (hw.late_penalty)
	const cost = $derived(
		!hw ? 0 : mode === 'resubmit' ? (hw.retake_cost ?? 2) : (hw.late_penalty ?? 0)
	);

	let comment = $state('');
	let picked: File[] = $state([]);
	let sending = $state(false);
	let err = $state('');
	let done = $state(false);
	let dragging = $state(false);
	let fileInput: HTMLInputElement | null = $state(null);
	let errEl = $state<HTMLElement>();
	let sendBtn = $state<HTMLElement>();
	let okEl = $state<HTMLElement>();
	// індекс першого файлу з останньої пачки (для каскаду появи)
	let batchStart = $state(0);

	// помилка → потрушування повідомлення і кнопки
	$effect(() => {
		if (err && errEl) {
			shake(errEl);
			if (sendBtn) shake(sendBtn);
		}
	});
	// успіх → пульс великої галочки
	$effect(() => {
		if (done && okEl) pop(okEl, 1.12);
	});

	/** Вихід рядка файлу: стискання + зсув. */
	function rowOut(node: Element) {
		if (!motionOK()) return { duration: 0 };
		return {
			duration: 260,
			easing: cubicOut,
			css: (t: number, u: number) =>
				`opacity:${t};transform:scale(${0.9 + 0.1 * t}) translateX(${u * 26}px)`
		};
	}

	// параметри здачі
	let showParams = $state(false);
	let zipMode = $state<'auto' | 'always'>('auto');
	let zipName = $state('');
	let compressLevel = $state(6);
	let rename = $state(true);

	// провайдер: M1 Provider (дефолт) або звичайний файл на fs itstep
	let provider = $state<'itstep' | 'm1'>('m1');
	// джерело всередині M1 Provider: своє посилання або файл на fs itstep
	let m1Source = $state<'url' | 'file'>('file');
	let openInBrowser = $state(false);
	let linkUrl = $state('');

	// усі обрані файли підтримує браузерний перегляд?
	const allSupported = $derived(
		picked.length > 0 &&
		picked.every((f) => /\.(png|jpe?g|webp|mp4|webm|zip)$/i.test(f.name)));

	const linkInfo = $derived.by(() => {
		const raw = linkUrl.trim();
		if (!raw) return null;
		try {
			const u = new URL(/^https?:\/\//i.test(raw) ? raw : `https://${raw}`);
			const host = u.hostname.replace(/^www\./, '');
			const map: [RegExp, string, string][] = [
				[/^drive\.google\.com$/, 'Google Drive', 'cloud'],
				[/^docs\.google\.com$/, 'Google Docs', 'file'],
				[/^canva\.com$|(^|\.)canva\.com$/, 'Canva', 'palette'],
				[/^github\.com$/, 'GitHub', 'github'],
				[/^youtube\.com$|^youtu\.be$/, 'YouTube', 'youtube'],
				[/^figma\.com$/, 'Figma', 'figma'],
				[/^notion\.(so|site)$/, 'Notion', 'file'],
				[/^gitlab\.com$/, 'GitLab', 'github']
			];
			for (const [re, name, ico] of map) {
				if (re.test(host)) return { name, ico, host, url: u.toString() };
			}
			return { name: host, ico: 'link', host, url: u.toString() };
		} catch {
			return null;
		}
	});

	// скидання при кожному відкритті
	$effect(() => {
		if (open) {
			comment = '';
			picked = [];
			err = '';
			done = false;
			sending = false;
			dragging = false;
			showParams = false;
			zipMode = 'auto';
			zipName = '';
			compressLevel = 6;
			// дефолт — M1 Provider (типовий кейс: фото/архів розв'язку)
			provider = 'm1';
			m1Source = 'file';
			openInBrowser = false;
			linkUrl = '';
		}
	});

	function onKeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape' && open) onclose?.();
	}

	function fmtDate(s: string | null): string {
		if (!s) return '';
		const d = new Date(s);
		return Number.isNaN(d.getTime())
			? s
			: d.toLocaleDateString('uk-UA', { day: '2-digit', month: '2-digit',
				year: 'numeric' });
	}

	function addFiles(fl: FileList | null): void {
		if (!fl?.length) return;
		for (const f of [...fl]) {
			if (f.size > MAX_FILE) {
				err = `«${f.name}» більший за 25 МБ`;
				return;
			}
		}
		err = '';
		batchStart = picked.length;
		picked = [...picked, ...[...fl]];
	}

	function removePicked(i: number): void {
		picked = picked.filter((_, idx) => idx !== i);
	}

	async function submit(): Promise<void> {
		if (!hw || sending || done) return;
		const isLink = provider === 'm1' && m1Source === 'url';
		if (isLink) {
			if (!linkInfo) {
				err = linkUrl.trim()
					? 'Не схоже на посилання — перевірте адресу'
					: 'Вставте посилання на рішення';
				return;
			}
			sending = true;
			err = '';
			try {
				await api.submitHomework(account, hw.id, comment, [], {
					link: linkInfo.url,
					provider: 'm1'
				});
				done = true;
				fx.celebrate('hw');
				setTimeout(() => {
					onsubmitted?.();
					onclose?.();
				}, 1200);
			} catch (ex) {
				err = friendlyError(ex);
			} finally {
				sending = false;
			}
			return;
		}
		if (!picked.length && !comment.trim()) {
			err = 'Прикріпіть файл або опишіть рішення текстом';
			return;
		}
		sending = true;
		err = '';
		try {
			await api.submitHomework(account, hw.id, comment, picked, {
				zip_mode: zipMode,
				zip_name: zipName.trim(),
				compress_level: compressLevel,
				rename,
				provider,
				open_in_browser: provider === 'm1' && openInBrowser
			});
			done = true;
			fx.celebrate('hw');
			setTimeout(() => {
				onsubmitted?.();
				onclose?.();
			}, 1200);
		} catch (ex) {
			err = friendlyError(ex);
		} finally {
			sending = false;
		}
	}
</script>

<svelte:window onkeydown={onKeydown} />

{#if open && hw}
	<div class="ov" transition:fade={{ duration: 140 }}
		onclick={() => onclose?.()} aria-hidden="true"></div>

	<div class="dlg glass hw-solid" role="dialog" aria-modal="true"
		transition:fly={{ y: 26, duration: 220 }}>
		<header>
			<h3><FileText size={18} /> {mode === 'resubmit' ? 'Перездати роботу' : 'Здати роботу'}</h3>
			<button class="x" onclick={() => onclose?.()} aria-label="Закрити">
				<X size={18} />
			</button>
		</header>

		<div class="brief">
			<b>{hw.title}</b>
			<span class="text-dim small">{hw.subject}{#if hwKindTag(hw.kind)} · {hwKindTag(hw.kind).toLowerCase()}{/if}</span>
			<div class="brief-chips">
				{#if hw.overdue_days}
					<span class="due-chip late">Прострочено: {hw.overdue_days} дн.</span>
				{:else if hw.due}
					<span class="due-chip">Дедлайн: {fmtDate(hw.due)}</span>
				{/if}
				<span class="text-faint small">{hw.status_label}</span>
				{#if cost > 0}
					<span class="due-chip cost" title={mode === 'resubmit'
						? 'Запит на перездачу коштує монети'
						: 'Дедлайн давно минув — здача коштує монети'}><Coins size={12} /> −{cost}</span>
				{/if}
			</div>
		</div>

		{#if done}
			<div class="ok" in:fade={{ duration: 150 }}>
				<span class="ok-ico" bind:this={okEl}>
					<svg viewBox="0 0 52 52" width="72" height="72" aria-hidden="true">
						<circle class="ok-c" cx="26" cy="26" r="23" pathLength="1" />
						<path class="ok-p" d="M15 27 l8 8 l15 -17" pathLength="1" />
					</svg>
				</span>
				<b class="ok-t">Роботу здано!</b>
				<span class="text-dim small ok-s">Статус: на перевірці</span>
			</div>
		{:else}
			<div class="mode-tabs" role="tablist">
				<button class:active={provider === 'itstep'} role="tab"
					aria-selected={provider === 'itstep'}
					onclick={() => (provider = 'itstep')}>
					<FileArchive size={14} /> Файл (Itstep)
				</button>
				<button class:active={provider === 'm1'} role="tab"
					aria-selected={provider === 'm1'}
					onclick={() => (provider = 'm1')}>
					<Link2 size={14} /> M1 Provider
				</button>
			</div>

			{#if provider === 'm1'}
				<div class="mode-tabs src-tabs" role="tablist">
					<button class:active={m1Source === 'file'} role="tab"
						aria-selected={m1Source === 'file'}
						onclick={() => (m1Source = 'file')}>
						<FileUp size={13} /> Файл
					</button>
					<button class:active={m1Source === 'url'} role="tab"
						aria-selected={m1Source === 'url'}
						onclick={() => (m1Source = 'url')}>
						<Link2 size={13} /> Своє посилання
					</button>
				</div>
			{/if}

			{#if provider === 'm1' && m1Source === 'url'}
				<div class="link-box" in:blurFade={{ duration: 280, amount: 5, y: 8 }}>
					<div class="link-input">
						<Link2 size={15} />
						<input bind:value={linkUrl} spellcheck="false"
							placeholder="https://drive.google.com/… або canva.com/…"
							onkeydown={(e) => e.key === 'Enter' && submit()} />
					</div>
					{#if linkInfo}
						{#key linkInfo.name}
						<a class="link-card" href={safeUrl(linkInfo.url)} target="_blank"
							rel="noopener noreferrer" in:springIn={{ start: 0.94, duration: 420, y: 8 }}>
							<span class="lc-ico">
								{#if linkInfo.ico === 'palette'}<Palette size={18} />
								{:else if linkInfo.ico === 'github'}<Code2 size={18} />
								{:else if linkInfo.ico === 'youtube'}<Play size={18} />
								{:else if linkInfo.ico === 'cloud'}<Cloud size={18} />
								{:else if linkInfo.ico === 'figma'}<Globe size={18} />
								{:else if linkInfo.ico === 'file'}<FileText size={18} />
								{:else}<Link2 size={18} />{/if}
							</span>
							<span class="lc-body">
								<b>{linkInfo.name}</b>
								<small>{linkInfo.host} — буде відкрито викладачем у новій вкладці</small>
							</span>
						</a>
						{/key}
					{:else if linkUrl.trim()}
						<p class="p-hint" in:blurFade={{ duration: 220, y: 4 }}>⚠ Не схоже на посилання</p>
					{:else}
						<p class="p-hint">Google Drive, Canva, GitHub, Figma, Notion, YouTube —
							будь-яке посилання на рішення, без завантаження файлу.</p>
					{/if}
				</div>
			{:else}			<div class="drop" class:dragging class:has-files={picked.length}
					in:blurFade={{ duration: 280, amount: 5, y: 8 }}
				role="button" tabindex="0"
				onclick={() => fileInput?.click()}
				onkeydown={(e) => e.key === 'Enter' && fileInput?.click()}
				ondragover={(e) => { e.preventDefault(); dragging = true; }}
				ondragleave={() => (dragging = false)}
				ondrop={(e) => { e.preventDefault(); dragging = false;
					addFiles(e.dataTransfer?.files ?? null); }}>
				<input type="file" multiple hidden
					bind:this={fileInput}
					onchange={(e) => {
						addFiles((e.currentTarget as HTMLInputElement).files);
						(e.currentTarget as HTMLInputElement).value = '';
					}} />
				<span class="d-ico"><FileUp size={22} /></span>
				<span>{picked.length
					? `Файлів обрано: ${picked.length} — додати ще`
					: 'Прикріпіть файл або додайте текст нижче'}</span>
				<small>клікніть або перетягніть · до 25 МБ кожен</small>
			</div>

			{#each picked as f, i (f)}
				<div class="f-row"
					animate:flip={{ duration: 320, easing: cubicOut }}
					in:fly={{ x: -22, duration: 380, delay: Math.min(8, Math.max(0, i - batchStart)) * 55, easing: cubicOut }}
					out:rowOut>
					<Paperclip size={14} />
					<span class="f-name">{f.name}</span>
					<span class="text-faint small">{(f.size / 1024).toFixed(0)} КБ</span>
					<button class="x" onclick={() => removePicked(i)} aria-label="Прибрати">
						<X size={14} />
					</button>
				</div>
			{/each}

			<button class="params-toggle" use:pressable={{ scale: 0.98 }} onclick={() => (showParams = !showParams)} type="button">
				<span class="gear" class:on={showParams}><Settings2 size={14} /></span>
				<span>Параметри здачі</span>
				{#if picked.length > 1 || zipMode === 'always'}
					<span class="zip-chip"><FileArchive size={11} />
						{zipMode === 'always'
							? (zipName.trim() || 'Фамілія_Ім\'я') + '.zip'
							: `${picked.length} файли → один .zip`}</span>
				{/if}
			</button>

			{#if showParams}
				<div class="params" transition:slide={{ duration: 340, easing: cubicOut }}>
					<label class="p-field">
						<span>Упаковка в архів</span>
						<select bind:value={zipMode}>
							<option value="auto">Авто: png/jpg напряму, решта — .zip</option>
							<option value="always">Завжди пакувати в .zip</option>
						</select>
					</label>
					<label class="p-field">
						<span>Ім'я файлів та архіва</span>
						<input bind:value={zipName}
							placeholder="за замовчуванням: Фамілія_Ім'я"
							maxlength="80" />
					</label>
					{#if zipMode === 'always' || picked.length > 1 || picked.some((f) => !/\.(png|jpe?g)$/i.test(f.name))}
						<label class="p-field">
							<span>Ступінь стиснення</span>
							<select bind:value={compressLevel}>
								<option value={0}>Без стиснення (найшвидше)</option>
								<option value={1}>Швидке</option>
								<option value={6}>Збалансоване</option>
								<option value={9}>Максимальне (найдовше)</option>
							</select>
						</label>
					{/if}
					<label class="p-check">
						<input type="checkbox" bind:checked={rename} />
						<span>Переіменовувати файли у «Фамілія_Ім'я»</span>
					</label>
				</div>
			{/if}
			{/if}

			{#if provider === 'm1' && m1Source === 'file'}
				<label class="p-check">
					<input type="checkbox" bind:checked={openInBrowser}
						disabled={!allSupported} />
					<span>Відкривати в браузері{#if !allSupported} — файл(и) не підтримуються{/if}</span>
				</label>
			{/if}

			<textarea bind:value={comment} rows="3" maxlength="2000"
				placeholder="Коментар до рішення (необов'язково)"></textarea>

			{#if err}
				<p class="f-err" bind:this={errEl} transition:fade={{ duration: 160 }}>⚠ {err}</p>
			{/if}

			<button class="btn send" class:sending bind:this={sendBtn} use:pressable={{ scale: 0.97 }}
				disabled={sending} onclick={submit}>
				{#key sending}
					<span class="send-in" in:blurFade={{ duration: 240, amount: 4, y: 6 }}>
						{#if sending}
							<span class="mini-spin"></span> Надсилаємо…
						{:else}
							<Send size={16} /> {mode === 'resubmit' ? 'Перездати' : provider === 'm1' && m1Source === 'url' ? 'Надіслати посилання' : 'Здати'}{#if cost > 0}<span class="send-cost">−{cost} <Coins size={13} /></span>{/if}
						{/if}
					</span>
				{/key}
			</button>
		{/if}
	</div>
{/if}

<style>
	.ov {
		position: fixed;
		inset: 0;
		background: rgba(5, 7, 12, 0.6);
		-webkit-backdrop-filter: blur(calc(6px + 0px));
		backdrop-filter: blur(calc(6px + 0px));
		z-index: 90;
	}
	/* lite: без backdrop-filter, темніший суцільний фон */
	:global(html[data-perf='lite']) .ov {
		-webkit-backdrop-filter: none;
		backdrop-filter: none;
		background: rgba(5, 7, 12, 0.78);
	}

	.dlg {
		position: fixed;
		z-index: 91;
		left: 50%;
		top: 50%;
		transform: translate(-50%, -50%);
		width: min(520px, calc(100vw - 32px));
		max-height: calc(100dvh - 48px);
		overflow-y: auto;
		border-radius: var(--radius-lg);
		padding: 20px;
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	h3 {
		display: flex;
		align-items: center;
		gap: 8px;
		margin: 0;
		font-family: var(--font-display);
		font-size: 17px;
	}

	.x {
		display: grid;
		place-items: center;
		width: 30px;
		height: 30px;
		border: none;
		border-radius: var(--radius-sm);
		background: transparent;
		color: var(--text-dim);
		cursor: pointer;
	}

	.x:hover {
		background: var(--glass-bg);
		color: var(--text);
	}

	.brief {
		display: flex;
		flex-direction: column;
		gap: 3px;
		padding: 12px 14px;
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-md);
		background: var(--surface-2);
	}

	.brief b {
		font-size: 14.5px;
	}

	.due-chip.cost {
		display: inline-flex;
		align-items: center;
		gap: 3px;
		color: var(--amber, #ffb454);
	}
	.send-cost {
		display: inline-flex;
		align-items: center;
		gap: 3px;
		margin-left: 8px;
		padding: 1px 7px;
		border-radius: 999px;
		font-size: 12px;
		font-weight: 600;
		background: rgb(0 0 0 / 0.18);
	}
	.brief-chips {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-top: 4px;
		flex-wrap: wrap;
	}

	.drop {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 4px;
		padding: 22px 14px;
		border: 1.5px dashed var(--glass-border);
		border-radius: var(--radius-md);
		color: var(--text-dim);
		cursor: pointer;
		text-align: center;
		transition: border-color 0.15s ease, background 0.15s ease, color 0.15s ease,
			transform 420ms var(--ease-spring), box-shadow 320ms var(--ease-out);
	}

	.drop:hover,
	.drop.dragging {
		border-color: var(--accent);
		color: var(--accent);
		background: rgba(108, 124, 255, 0.06);
	}

	/* перетягування: легке збільшення, світіння, іконка підстрибує */
	.drop.dragging {
		transform: scale(1.01);
		box-shadow:
			0 0 0 4px color-mix(in srgb, var(--accent) 18%, transparent),
			0 10px 34px color-mix(in srgb, var(--accent) 28%, transparent);
	}
	.d-ico { display: grid; }
	.drop.dragging .d-ico {
		animation: sm-bounce 760ms var(--ease-spring) infinite;
	}
	@keyframes sm-bounce {
		0%, 100% { transform: translateY(0); }
		45% { transform: translateY(-7px) scale(1.12); }
	}
	.gear { display: grid; transition: transform 480ms var(--ease-spring); }
	.gear.on { transform: rotate(90deg); }
	.lc-ico { animation: sm-ico 520ms var(--ease-spring) 120ms both; }
	@keyframes sm-ico { from { opacity: 0; transform: scale(0.3) rotate(-20deg); } }

	.drop.has-files {
		padding: 14px;
	}

	.drop small {
		color: var(--text-faint);
	}

	.f-row {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 7px 10px;
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-sm);
		background: var(--surface-2);
	}

	.f-name {
		flex: 1;
		min-width: 0;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		font-size: 13px;
	}

	textarea {
		width: 100%;
		box-sizing: border-box;
		resize: vertical;
		min-height: 64px;
		padding: 10px 12px;
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-md);
		background: var(--surface-2);
		color: var(--text);
		font: inherit;
		font-size: 13.5px;
	}

	textarea:focus {
		outline: none;
		border-color: var(--accent);
	}

	.f-err {
		margin: 0;
		color: var(--danger);
		font-size: 13px;
	}

	.params-toggle {
		display: flex;
		align-items: center;
		gap: 7px;
		padding: 8px 10px;
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-sm);
		background: transparent;
		color: var(--text-dim);
		font: inherit;
		font-size: 13px;
		cursor: pointer;
		transition: color 0.15s ease, border-color 0.15s ease;
	}

	.params-toggle:hover {
		color: var(--accent);
		border-color: var(--accent);
	}

	.zip-chip {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		margin-left: auto;
		padding: 2px 8px;
		border-radius: 999px;
		background: rgba(108, 124, 255, 0.12);
		color: var(--accent);
		font-size: 11px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 60%;
	}

	.params {
		display: flex;
		flex-direction: column;
		gap: 10px;
		padding: 12px 14px;
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-md);
		background: var(--surface-2);
	}

	.p-field {
		display: flex;
		flex-direction: column;
		gap: 4px;
		font-size: 12.5px;
		color: var(--text-dim);
	}

	.p-field select,
	.p-field input {
		padding: 8px 10px;
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-sm);
		background: var(--surface-2);
		color: var(--text);
		font: inherit;
		font-size: 13px;
	}

	.p-field select:focus,
	.p-field input:focus {
		outline: none;
		border-color: var(--accent);
	}

	.p-hint {
		margin: 0;
		font-size: 11.5px;
		color: var(--text-faint);
	}

	.p-check {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 12.5px;
		color: var(--text-dim);
		cursor: pointer;
	}

	.p-check input {
		accent-color: var(--accent);
	}

	.mode-tabs {
		display: flex;
		gap: 6px;
	}

	.mode-tabs button {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 6px;
		padding: 9px 10px;
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-sm);
		background: transparent;
		color: var(--text-dim);
		font: inherit;
		font-size: 12.5px;
		cursor: pointer;
		transition: color 0.15s ease, border-color 0.15s ease, background 0.15s ease;
	}

	.mode-tabs button.active {
		color: var(--accent);
		border-color: var(--accent);
		background: rgba(108, 124, 255, 0.08);
	}

	.src-tabs button {
		padding: 7px 10px;
		font-size: 12px;
	}

	.link-box {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.link-input {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 10px 12px;
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-md);
		background: var(--surface-2);
		color: var(--text-dim);
	}

	.link-input:focus-within {
		border-color: var(--accent);
		color: var(--accent);
	}

	.link-input input {
		flex: 1;
		min-width: 0;
		border: none;
		background: transparent;
		color: var(--text);
		font: inherit;
		font-size: 13px;
	}

	.link-input input:focus {
		outline: none;
	}

	.link-card {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 10px 12px;
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-md);
		background: var(--surface-2);
		text-decoration: none;
		color: inherit;
		transition: border-color 0.15s ease, background 0.15s ease;
	}

	.link-card:hover {
		border-color: var(--accent);
		background: rgba(108, 124, 255, 0.06);
	}

	.lc-ico {
		display: grid;
		place-items: center;
		width: 36px;
		height: 36px;
		border-radius: var(--radius-sm);
		background: rgba(108, 124, 255, 0.12);
		color: var(--accent);
		flex-shrink: 0;
	}

	.lc-body {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}

	.lc-body b {
		font-size: 13px;
	}

	.lc-body small {
		color: var(--text-faint);
		font-size: 11px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.send {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
		padding: 12px;
		border: none;
		border-radius: var(--radius-md);
		background: var(--accent);
		color: #fff;
		font: inherit;
		font-weight: 600;
		cursor: pointer;
		transition: filter 0.15s ease, transform 0.1s ease;
	}

	.send:hover:not(:disabled) {
		filter: brightness(1.1);
	}

	.send:active:not(:disabled) {
		transform: scale(0.98);
	}

	.send:disabled {
		opacity: 0.6;
		cursor: default;
	}

	.send { position: relative; overflow: hidden; }
	.send-in { display: inline-flex; align-items: center; gap: 8px; position: relative; z-index: 1; }
	/* надсилання: по кнопці біжить світла смуга-прогрес */
	.send.sending::after {
		content: '';
		position: absolute;
		inset: 0;
		transform: translateX(-100%);
		background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.28), transparent);
		animation: m1-shimmer 1.2s ease-in-out infinite;
	}
	.send.sending:disabled { opacity: 0.85; }

	.mini-spin {
		width: 15px;
		height: 15px;
		border-radius: 50%;
		border: 2px solid rgba(255, 255, 255, 0.35);
		border-top-color: #fff;
		animation: rot 0.8s linear infinite;
	}

	@keyframes rot {
		to {
			transform: rotate(360deg);
		}
	}

	.ok {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 6px;
		padding: 26px 14px;
	}

	.ok-ico {
		display: grid;
		place-items: center;
		width: 72px;
		height: 72px;
		border-radius: 50%;
		background: rgba(74, 222, 128, 0.12);
		color: var(--success);
		animation: sm-okbg 520ms var(--ease-spring) both;
	}
	.ok-ico svg {
		fill: none;
		stroke: var(--success);
		stroke-width: 3;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.ok-c, .ok-p { stroke-dasharray: 1; stroke-dashoffset: 1; }
	.ok-c { animation: sm-draw 520ms var(--ease-out) 80ms forwards; }
	.ok-p { animation: sm-draw 360ms var(--ease-out) 460ms forwards; }
	.ok-t { animation: sm-up 420ms var(--ease-out) 560ms both; }
	.ok-s { animation: sm-up 420ms var(--ease-out) 660ms both; }
	@keyframes sm-draw { to { stroke-dashoffset: 0; } }
	@keyframes sm-okbg { from { opacity: 0; transform: scale(0.5); } }
	@keyframes sm-up { from { opacity: 0; transform: translateY(8px); } }
	:global(html[data-anim='off']) :is(.ok-ico, .ok-c, .ok-p, .ok-t, .ok-s, .lc-ico, .drop.dragging .d-ico, .send.sending::after) {
		animation: none;
	}
	:global(html[data-anim='off']) :is(.ok-c, .ok-p) { stroke-dashoffset: 0; }
	:global(html[data-anim='off']) .drop.dragging { transform: none; }

	/* Де є нижня панель (≤900px): вікно живе у вільній зоні НАД нею — центр і
	 * висота рахуються без --nav-total, тож кнопка «Здати» не опиняється під
	 * панеллю, а внутрішній скрол доходить до самого низу. */
	@media (max-width: 900px) {
		.dlg {
			top: calc((100dvh - var(--nav-total, 0px)) / 2);
			max-height: calc(100dvh - var(--nav-total, 0px) - 24px);
			overscroll-behavior: contain;
			-webkit-overflow-scrolling: touch;
		}
	}

	@media (max-width: 560px) {
		.dlg {
			/* на телефоні — по центру вільної зони */
			width: min(520px, calc(100vw - 24px));
			max-height: calc(100dvh - var(--nav-total, 0px) - 20px);
			padding: 16px;
		}

		.send {
			padding: 13px;
		}
	}
</style>
