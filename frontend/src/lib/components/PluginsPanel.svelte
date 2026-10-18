<script lang="ts">
	import {
		Puzzle, ShieldCheck, Upload, Trash2, RefreshCw, Terminal, Info, Link2, Download, Users,
		Lock, X, MessageSquare, Puzzle as PuzzleIcon
	} from '@lucide/svelte';
	import { fade } from 'svelte/transition';
	import { tick } from 'svelte';
	import { flip } from 'svelte/animate';
	import { blurFade, pop, pressable, springIn, stagger } from '$lib/motion';
	import { api, ApiError, type PluginOut } from '$lib/api/client';
	import { friendlyError } from '$lib/errors';
	import { confirm } from '$lib/ui';
	import PluginInfoModal from './PluginInfoModal.svelte';
	import PluginUploadModal from './PluginUploadModal.svelte';
	import PluginSettings from './PluginSettings.svelte';
	import PluginRuns from './PluginRuns.svelte';

	let { active = false }: { active?: boolean } = $props();

	// --- стан ---
	let plugins = $state<PluginOut[]>([]);
	let err = $state('');
	let busy = $state(false);
	let settingsFor = $state<PluginOut | null>(null);
	let runsFor = $state<PluginOut | null>(null);
	let confirmPerm = $state<PluginOut | null>(null);
	let infoOpen = $state(false);
	let uploadOpen = $state(false);
	let linkTokens = $state<Record<string, string>>({});

	function onKeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape' && confirmPerm) confirmPerm = null;
	}

	/** Рендер у body: .glass-картка вкладки запирає fixed-елементи. */
	function portal(node: HTMLElement): { destroy(): void } {
		document.body.appendChild(node);
		return { destroy: () => node.remove() };
	}

	function visBadge(p: PluginOut): { icon: typeof Link2; label: string } | null {
		if (p.visibility === 'link') return { icon: Link2, label: 'по посиланню' };
		if (p.visibility === 'private') return { icon: Lock, label: 'приватний' };
		return null;
	}

	function shareUrl(token: string): string {
		return `${location.origin}${location.pathname}?plg=${token}`;
	}

	async function copyShare(token: string): Promise<void> {
		await navigator.clipboard?.writeText(shareUrl(token));
	}

	// перечитуємо щоразу, коли вкладка стає активною
	$effect(() => {
		if (active) void load();
	});

	async function load(): Promise<void> {
		busy = true;
		err = '';
		try {
			const resp = await api.pluginsList();
			plugins = resp ?? [];
			// share-посилання: ?plg=<token> → підтягнути плагін у список
			const token = new URLSearchParams(location.search).get('plg');
			if (token) {
				try {
					const shared = await api.pluginShared(token);
					if (shared && !plugins.some((x) => x.id === shared.id)) {
						plugins = [...plugins, shared];
					}
				} catch { /* недійсний токен — ігноруємо */ }
			}
		} catch (e) {
			err = friendlyError(e);
		} finally {
			busy = false;
		}
	}

	// кастомна вкладка плагіна (on_ui): дані або index.html (iframe)
	let uiData: unknown = $state(null);
	let uiErr = $state('');
	let uiHtml = $state('');
	let uiOpenId = $state('');
	// iframe плагіна: дані шлемо на його onload (а не за таймером)
	let uiFrame = $state<HTMLIFrameElement | null>(null);
	let uiFrameLoaded = false;
	let uiPayload: { ready: boolean; data: unknown } = { ready: false, data: null };

	/** Надсилає дані плагіна в iframe, коли готові і сам iframe, і дані. */
	function pushUiData(): void {
		if (!uiFrameLoaded || !uiPayload.ready) return;
		uiFrame?.contentWindow?.postMessage({ type: 'plugin:data', payload: uiPayload.data }, '*');
	}

	function onFrameLoad(): void {
		uiFrameLoaded = true;
		pushUiData();
	}

	async function openUi(p: PluginOut): Promise<void> {
		uiOpenId = p.id;
		uiFrameLoaded = false;
		uiPayload = { ready: false, data: null };
		uiHtml = '';
		uiData = null;
		uiErr = '';
		try {
			if (p.ui?.entry) {
				const src = await api.pluginSource(p.id);
				const html = src.html;
				// NB: CSP для iframe не задано свідомо (sandbox без allow-same-origin дає
				// opaque origin); повна ізоляція мережі потребує окремого origin/заголовка CSP.
				// спілкування iframe з ядром: тільки postMessage-протокол
				const bridge = `
<script>
  window.addEventListener('message', (ev) => {
    if (ev.data && ev.data.type === 'plugin:data') {
      document.getElementById('__data__').textContent = JSON.stringify(ev.data.payload);
      document.dispatchEvent(new CustomEvent('plugin-data', { detail: ev.data }));
    }
  });
<\/script><span id="__data__" hidden></span>`;
				// міст вставляємо перед </body> (без урахування регістру);
				// якщо тега немає — дописуємо в кінець документа
				const bodyClose = /<\/body\s*>/i;
				uiHtml = bodyClose.test(html)
					? html.replace(bodyClose, () => bridge + '</body>')
					: html + bridge;
				const r = await api.pluginUi(p.id);
				if (r.ok) {
					// дані віддаємо всередину iframe (opaque origin) після його load
					uiPayload = { ready: true, data: r.data ?? null };
					pushUiData();
				} else {
					uiErr = r.error || 'Плагін повернув помилку.';
				}
			} else {
				const r = await api.pluginUi(p.id);
				if (r.ok) {
					uiData = r.data ?? {};
				} else {
					uiErr = r.error || 'Плагін повернув помилку.';
				}
			}
		} catch (e) {
			uiErr = friendlyError(e);
		}
	}

	/** Картка, що щойно оновилась (вмик/вимк) — коротке підсвічування. */
	let flashId = $state<string | null>(null);
	let flashTimer: ReturnType<typeof setTimeout> | undefined;

	function flashCard(id: string): void {
		flashId = null;
		void tick().then(() => {
			flashId = id;
			clearTimeout(flashTimer);
			flashTimer = setTimeout(() => (flashId = null), 950);
		});
	}

	async function popCard(id: string): Promise<void> {
		await tick();
		const el = document.querySelector<HTMLElement>(`.plg [data-pid="${CSS.escape(id)}"]`);
		if (el) pop(el, 1.025);
	}

	async function install(p: PluginOut): Promise<void> {
		try {
			await api.pluginInstall(p.id, p.permissions);
			confirmPerm = null;
			await load();
			void popCard(p.id);
			flashCard(p.id);
		} catch (e) {
			err = friendlyError(e);
		}
	}

	async function uninstall(p: PluginOut): Promise<void> {
		const ok = await confirm({
			title: `Видалити плагін «${p.name}»?`,
			message: 'Плагін буде вимкнено, а всі його дані та налаштування — стерто. Це незворотно.',
			confirmText: 'Видалити',
			danger: true
		});
		if (!ok) return;
		try {
			await api.pluginUninstall(p.id);
			await load();
		} catch (e) {
			err = friendlyError(e);
		}
	}

	async function toggle(p: PluginOut): Promise<void> {
		try {
			await api.pluginEnable(p.id, !p.enabled);
			await load();
			flashCard(p.id);
		} catch (e) {
			err = friendlyError(e);
		}
	}

	async function onUploaded(): Promise<void> {
		await load();
	}

	async function removePlugin(p: PluginOut): Promise<void> {
		const ok = await confirm({
			title: `Видалити «${p.name}» з маркетплейсу?`,
			message: 'Плагін зникне для всіх, а дані всіх користувачів будуть втрачені. Це незворотно.',
			confirmText: 'Видалити',
			danger: true
		});
		if (!ok) return;
		try {
			await api.pluginDelete(p.id);
			await load();
		} catch (e) {
			err = friendlyError(e);
		}
	}

	async function makeLink(p: PluginOut): Promise<void> {
		try {
			const r = await api.pluginShare(p.id, 'link');
			linkTokens = { ...linkTokens, [p.id]: r.share_token };
		} catch (e) {
			err = e instanceof ApiError && e.status === 403
				? 'Лише адмін або автор аплоаду.'
				: friendlyError(e);
		}
	}

	async function verify(p: PluginOut): Promise<void> {
		try {
			await api.pluginVerify(p.id, !p.verified);
			await load();
		} catch (e) {
			err = e instanceof ApiError && e.status === 403
				? 'Верифікація доступна лише адміну.'
				: friendlyError(e);
		}
	}
</script>

<div class="plg">
	{#if busy && !plugins.length}
		<p class="text-dim small">Завантаження…</p>
	{:else if err && !plugins.length}
		<div class="empty">
			<Puzzle size={30} strokeWidth={1.6} />
			<b>Не вдалося завантажити плагіни</b>
			<span class="text-dim small">{err}</span>
			<button class="act" onclick={() => void load()}>
				<RefreshCw size={14} /> Спробувати ще
			</button>
		</div>
	{:else if !plugins.length}
		<div class="empty" in:springIn={{ duration: 420, start: 0.94, y: 10 }}>
			<Puzzle size={30} strokeWidth={1.6} />
			<b>Магазин розширень поки порожній</b>
			<span class="text-dim small">
				Завантажте перший плагін — zip-архівом або окремими файлами.
				Плагіни живуть у пісочниці: без мережі, файлів і доступу
				до особистих даних.
			</span>
			<div class="empty-acts">
				<button class="act primary" onclick={() => (uploadOpen = true)}>
					<Upload size={14} /> Додати плагін
				</button>
				<button class="act" onclick={() => (infoOpen = true)}>
					<Info size={14} /> Що таке плагіни
				</button>
			</div>
		</div>
	{:else}
		<div class="tab-head">
			<h2>Плагіни <span class="cnt">{plugins.length}</span></h2>
			<div class="chips-row">
				<button class="act" title="Що таке плагіни?" aria-label="Що таке плагіни" onclick={() => (infoOpen = true)}>
					<Info size={14} />
				</button>
				<button class="act" onclick={() => void load()} aria-label="Оновити">
					<RefreshCw size={14} />
				</button>
				<button class="act primary" onclick={() => (uploadOpen = true)}>
					<Upload size={14} /> Додати плагін
				</button>
			</div>
		</div>

		<div class="grid" use:stagger={{ step: 50, max: 10, y: 12, scale: true }}>
			{#each plugins as p (p.id)}
				{@const vb = visBadge(p)}
				<article class="pc" class:off={p.installed && !p.enabled}
					class:flash-update={flashId === p.id}
					data-pid={p.id}
					animate:flip={{ duration: 360 }}
					in:springIn={{ duration: 360, start: 0.95, y: 10 }}
					out:blurFade={{ duration: 200, amount: 0 }}>
					<header class="pc-head">
						<span class="pc-ico"><Puzzle size={17} strokeWidth={2} /></span>
						<div class="pc-name">
							<b>{p.name}</b>
							<span class="pc-meta">v{p.version}{#if p.author} · {p.author}{/if}</span>
							{#if p.verified}
								<span class="badge ok" title="Перевірений автором M1 ID">
									<ShieldCheck size={12} /> верифікований
								</span>
							{:else}
								<span class="badge warn-b" title="Не перевірений — встановлюйте на свій ризик">
									не верифікований
								</span>
							{/if}
						</div>
						{#if p.installed}
							<label class="switch" title={p.enabled ? 'Увімкнено' : 'Вимкнено'}>
								<input type="checkbox" checked={p.enabled}
									onchange={() => void toggle(p)} />
								<i></i>
							</label>
						{/if}
					</header>

					<p class="pc-desc">{p.description || 'Без опису.'}</p>

					<div class="pc-chips">
						{#if vb}
							<span class="chip"><vb.icon size={11} /> {vb.label}</span>
						{/if}
						{#each p.permissions as perm (perm)}
							<span class="chip"><Lock size={11} /> {perm}</span>
						{/each}
						{#each p.tg_commands as cmd (cmd.command)}
							<span class="chip cmd"><MessageSquare size={11} /> /{cmd.command}</span>
						{/each}
					</div>

					{#if p.stats}
						<div class="stats-row">
							<span class="chip"><Users size={11} /> {p.stats.installs} інсталяцій</span>
							<span class="chip"><Terminal size={11} /> {p.stats.runs} запусків</span>
							<span class="sp"></span>
							<button class="act" title="Скачати .zip"
								onclick={() => void api.pluginDownload(p.id)}>
								<Download size={14} /> Завантажити
							</button>
							{#if p.is_admin}
								<button class="act" title="Верифікація — лише адміністратор"
									onclick={() => void verify(p)}>
									<ShieldCheck size={14} /> {p.verified ? 'Зняти ✓' : 'Верифікувати'}
								</button>
							{/if}
							<button class="act danger" title="Видалити плагін із маркетплейсу"
								onclick={() => void removePlugin(p)}>
								<Trash2 size={14} /> Видалити з маркетплейсу
							</button>
						</div>
					{/if}

					<footer class="pc-foot">
						{#if p.installed}
							<button class="act" onclick={() => (settingsFor = p)}>
								<Terminal size={14} /> Налаштувати
							</button>
							<button class="act" onclick={() => (runsFor = p)}>
								<Terminal size={14} /> Логи
							</button>
							{#if p.hooks?.on_ui || p.ui?.entry}
								<button class="act" onclick={() => openUi(p)}>
									<Puzzle size={14} /> Відкрити вкладку
								</button>
							{/if}
							<span class="sp"></span>
							<button class="act danger" title="Вимкнути й видалити дані"
								onclick={() => void uninstall(p)}>
								<Trash2 size={14} /> Видалити
							</button>
						{:else}
							<button class="act primary" use:pressable onclick={() => (confirmPerm = p)}>
								<PuzzleIcon size={14} /> Встановити
							</button>
							<button class="act" title="Згенерувати share-посилання"
								onclick={() => void makeLink(p)}>
								<Link2 size={14} /> Посилання
							</button>
						{/if}
					</footer>

					{#if linkTokens[p.id] || p.share_token}
						<div class="share-row" in:blurFade={{ duration: 260, amount: 0 }} out:fade={{ duration: 120 }}>
							<code>{shareUrl(linkTokens[p.id] || p.share_token)}</code>
							<button class="act" onclick={() => void copyShare(linkTokens[p.id] || p.share_token)}>
								Копіювати
							</button>
						</div>
					{/if}

					{#if uiOpenId === p.id}
						<div class="pc-ui" in:blurFade={{ duration: 320, amount: 0, y: 6 }}>
							{#if uiHtml}
								<iframe class="plg-frame" sandbox="allow-scripts"
									bind:this={uiFrame} onload={onFrameLoad}
									srcdoc={uiHtml} title={p.name}></iframe>
							{:else if uiData !== null}
								<pre class="plg-ui-data">{JSON.stringify(uiData, null, 2)}</pre>
							{/if}
							{#if uiErr}<p class="small warn">{uiErr}</p>{/if}
						</div>
					{/if}
				</article>
			{/each}
		</div>
	{/if}
</div>

{#if confirmPerm}
	<div class="ov"
		use:portal transition:fade={{ duration: 140 }}
		onclick={() => (confirmPerm = null)} aria-hidden="true"></div>
	<div class="dlg glass"
		use:portal role="dialog" aria-modal="true"
		transition:fade={{ duration: 160 }}>
		<header>
			<h3><Puzzle size={18} /> Встановити «{confirmPerm.name}»?</h3>
			<button class="x" onclick={() => (confirmPerm = null)} aria-label="Закрити">
				<X size={18} />
			</button>
		</header>
		<p class="small">Плагін отримає доступ до:</p>
		<ul class="plg-perms">
			{#each confirmPerm.permissions as perm (perm)}
				<li><span class="chip"><Lock size={11} /> {perm}</span></li>
			{/each}
		</ul>
		{#if !confirmPerm.verified}
			<p class="small warn">
				⚠️ Цей плагін НЕ верифікований автором M1 ID: можливі помилки
				або неочікувана поведінка. Встановлюйте на свій ризик.
			</p>
		{/if}
		<div class="chips-row">
			<button class="act primary" onclick={() => void install(confirmPerm!)}>Погоджуюсь, встановити</button>
			<button class="act" onclick={() => (confirmPerm = null)}>Скасувати</button>
		</div>
	</div>
{/if}

{#if infoOpen}
	<PluginInfoModal open={infoOpen} onclose={() => (infoOpen = false)} />
{/if}

{#if uploadOpen}
	<PluginUploadModal open={uploadOpen} onclose={() => (uploadOpen = false)} onuploaded={onUploaded} />
{/if}

{#if settingsFor}
	<PluginSettings plugin={settingsFor} onclose={() => (settingsFor = null)} />
{/if}

{#if runsFor}
	<PluginRuns plugin={runsFor} onclose={() => (runsFor = null)} />
{/if}

<svelte:window onkeydown={onKeydown} />

<style>
	.plg {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.tab-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
	}

	.tab-head h2 {
		margin: 0;
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.cnt {
		display: inline-grid;
		place-items: center;
		min-width: 22px;
		height: 22px;
		padding: 0 6px;
		font-size: 11.5px;
		font-weight: 700;
		color: var(--accent);
		background: var(--accent-soft);
		border-radius: 999px;
	}

	.chips-row {
		display: flex;
		flex-wrap: wrap;
		gap: 7px;
		align-items: center;
	}

	/* --- картка плагіна --- */
	.pc {
		display: flex;
		flex-direction: column;
		gap: 9px;
		padding: 14px 15px;
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-lg);
		transition: opacity 0.2s ease;
		content-visibility: auto;
		contain-intrinsic-size: auto 210px;
	}

	.pc.off { opacity: 0.55; }

	.pc-head {
		display: flex;
		align-items: center;
		gap: 10px;
		flex-wrap: wrap;
	}

	.pc-ico {
		flex: none;
		display: grid;
		place-items: center;
		width: 34px;
		height: 34px;
		border-radius: var(--radius-md);
		background: var(--accent-soft);
		color: var(--accent);
	}

	.pc-name {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
		flex: 1;
		min-width: 0;
	}

	.pc-name b { font-size: 14.5px; }

	.pc-meta { font-size: 11.5px; color: var(--text-faint); }

	.badge {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-size: 11px;
		padding: 3px 9px;
		border-radius: 999px;
		font-weight: 600;
	}
	.badge.ok { background: rgba(52, 199, 89, 0.14); color: #34c759; }
	.badge.warn-b { background: rgba(255, 179, 0, 0.14); color: #ffb300; }

	.pc-desc {
		margin: 0;
		font-size: 13px;
		color: var(--text-dim);
		line-height: 1.45;
	}

	.pc-chips { display: flex; flex-wrap: wrap; gap: 6px; }

	.chip {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		height: 24px;
		padding: 0 9px;
		font-size: 11px;
		font-weight: 600;
		color: var(--text-dim);
		background: var(--surface-2);
		border: 1px solid var(--glass-border);
		border-radius: 999px;
	}

	.chip.cmd {
		color: var(--accent);
		border-color: var(--accent-soft);
		background: var(--accent-soft);
	}

	.pc-foot {
		display: flex;
		align-items: center;
		gap: 7px;
		flex-wrap: wrap;
	}

	.sp { flex: 1; }

	.act {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		height: 32px;
		padding: 0 12px;
		font-size: 12.5px;
		font-weight: 600;
		color: var(--text-dim);
		background: var(--glass-bg);
		border: 1.5px solid var(--glass-border);
		border-radius: 999px;
		cursor: pointer;
		transition:
			border-color 0.2s ease,
			color 0.2s ease,
			background 0.2s ease,
			transform 0.1s ease,
			filter 0.15s ease;
	}
	.act:hover { border-color: var(--accent); color: var(--accent); }
	.act:active { transform: scale(0.97); }

	.act.primary {
		color: #fff;
		background: var(--accent);
		border-color: var(--accent);
	}
	.act.primary:hover { filter: brightness(1.1); color: #fff; }

	.act.danger { color: var(--danger); }
	.act.danger:hover { border-color: var(--danger); color: var(--danger); }

	/* перемикач (як у TelegramPanel) */
	.switch {
		position: relative;
		display: inline-block;
		width: 42px;
		height: 24px;
		cursor: pointer;
		flex: none;
		margin-left: auto;
	}
	.switch input { opacity: 0; width: 0; height: 0; }
	.switch i {
		position: absolute;
		inset: 0;
		background: var(--glass-bg-hover);
		border: 1px solid var(--glass-border);
		border-radius: 999px;
		transition: background 0.2s ease;
	}
	.switch i::before {
		content: '';
		position: absolute;
		top: 2px;
		left: 2px;
		width: 18px;
		height: 18px;
		border-radius: 50%;
		background: var(--surface-2);
		box-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
		transition:
			transform 0.18s var(--ease-spring),
			background 0.2s ease;
	}
	.switch input:checked + i { background: var(--accent-soft); }
	.switch input:checked + i::before {
		transform: translateX(18px);
		background: var(--accent);
	}

	.stats-row {
		display: flex;
		align-items: center;
		gap: 7px;
		flex-wrap: wrap;
		padding-top: 9px;
		border-top: 1px dashed var(--glass-border);
	}

	.share-row {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 7px 10px;
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-sm);
		background: var(--surface-2);
	}
	.share-row code {
		flex: 1;
		min-width: 0;
		font-size: 11.5px;
		overflow-wrap: anywhere;
	}

	.pc-ui { display: flex; flex-direction: column; gap: 6px; }
	.plg-frame {
		width: 100%;
		min-height: 220px;
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-md);
		background: transparent;
	}
	.plg-ui-data {
		font-size: 12px;
		padding: 10px;
		border-radius: var(--radius-md);
		background: var(--surface-2);
		overflow: auto;
		max-height: 320px;
	}

	.empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 8px;
		padding: 34px 16px;
		text-align: center;
		color: var(--text-dim);
	}
	.empty b { font-size: 15px; color: var(--text); }
	.empty .small { max-width: 380px; }

	/* модалка інсталяції (portal у body) */
	.ov {
		position: fixed;
		inset: 0;
		background: rgba(5, 7, 12, 0.6);
		-webkit-backdrop-filter: blur(calc(6px + 0px));
		backdrop-filter: blur(6px);
		z-index: 90;
	}
	:global(html[data-perf='lite']) .ov {
		-webkit-backdrop-filter: none;
		backdrop-filter: none;
		background: rgba(5, 7, 12, 0.82);
	}
	.dlg {
		position: fixed;
		z-index: 91;
		inset: 0;
		margin: auto;
		height: fit-content;
		width: min(460px, calc(100vw - 32px));
		max-height: calc(100dvh - 48px);
		overflow-y: auto;
		border-radius: var(--radius-lg);
		padding: 20px;
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.dlg header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	.dlg h3 {
		display: flex;
		align-items: center;
		gap: 8px;
		margin: 0;
		font-family: var(--font-display);
		font-size: 17px;
	}
	.dlg .x {
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
	.dlg .x:hover { background: var(--glass-bg); color: var(--text); }

	.plg-perms {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		list-style: none;
		padding: 0;
		margin: 0;
	}
	.warn { color: #ffb454; }
</style>