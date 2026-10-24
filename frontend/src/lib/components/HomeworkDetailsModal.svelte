<script lang="ts">
	import {
		CalendarDays,
		Coins,
		Eye,
		ExternalLink,
		FileText,
		Link2,
		MessageCircle,
		Paperclip,
		Send,
		Trash2,
		User,
		X
	} from '@lucide/svelte';
	import { api, ApiError, type HwCard, type HwItem } from '$lib/api/client';
	import { untrack } from 'svelte';
	import { friendlyError } from '$lib/errors';
	import { showToast } from '$lib/stores/toast.svelte';
	import Spinner from '$lib/ui/Spinner.svelte';
	import { safeUrl } from '$lib/sanitize';
	import { cleanTeacher, hwKindTag } from '$lib/app/helpers';
	import M1LinkModal from './M1LinkModal.svelte';
	import FileViewerModal from './FileViewerModal.svelte';
	import { stagger, pressable, blurFade, shake, AnimatedNumber } from '$lib/motion';

	let {
		open = false,
		hw = null,
		account = 0,
		onsubmitrequest = () => {},
		// ⚠️ інакше після видалення здачі onchanged() падає з TypeError
		// (був лише в типі, але не в деструктуризації $props)
		onchanged = () => {},
		onclose = () => {}
	}: {
		open?: boolean;
		hw?: HwItem | null;
		account?: number;
		onsubmitrequest?: (kind: 'submit' | 'resubmit') => void;
		onchanged?: () => void;
		onclose?: () => void;
	} = $props();

	// Двоетапне підтвердження: перший клік «озброює» кнопку на ARM_MS мс
	// (червоний стан + смужка-таймер), другий клік виконує дію.
	const ARM_MS = 3000;
	type DelPhase = 'idle' | 'armed' | 'busy';
	let armResub = $state(false);
	let delPhase = $state<DelPhase>('idle');
	let delBtn = $state<HTMLElement>();
	let resubBtn = $state<HTMLElement>();
	let delTimer: ReturnType<typeof setTimeout> | undefined;
	let resubTimer: ReturnType<typeof setTimeout> | undefined;
	// після успішного видалення сервер (MyStat) може ще віддати стару картку —
	// тоді локальний стан «не на перевірці» має пріоритет до наступного відкриття
	let justDeleted = false;

	// M1 Provider: повноцінна модалка керування посиланнями
	let m1ModalOpen = $state(false);
	let m1Count = $state(0);
	let m1Opens = $state(0);

	// лічильники поколінь: відповідь для вже неактуального ДЗ ігноруємо
	let loadGen = 0;
	let linksGen = 0;

	async function loadLinks(): Promise<void> {
		const gen = ++linksGen;
		m1Count = 0;
		m1Opens = 0;
		if (!open || !hw || !account) return;
		try {
			const items = (await api.links(account, hw.id)).items;
			if (gen !== linksGen) return;
			m1Count = items.length;
			m1Opens = items.reduce((s, l) => s + (l.opens || 0), 0);
		} catch { /* некритично */ }
	}
	function disarm(): void {
		clearTimeout(delTimer);
		clearTimeout(resubTimer);
		armResub = false;
		if (delPhase === 'armed') delPhase = 'idle';
	}

	function onResubClick(): void {
		if (!armResub) {
			clearTimeout(delTimer);
			if (delPhase === 'armed') delPhase = 'idle';
			armResub = true;
			clearTimeout(resubTimer);
			resubTimer = setTimeout(() => (armResub = false), ARM_MS);
		} else {
			disarm();
			onsubmitrequest('resubmit');
		}
	}

	function onDeleteClick(): void {
		if (delPhase === 'busy') return; // подвійне видалення неможливе
		if (delPhase === 'idle') {
			armResub = false;
			clearTimeout(resubTimer);
			delPhase = 'armed';
			clearTimeout(delTimer);
			delTimer = setTimeout(() => {
				if (delPhase === 'armed') delPhase = 'idle';
			}, ARM_MS);
		} else {
			void delSubmission();
		}
	}

	// клік поза кнопкою, що чекає підтвердження, скасовує його
	$effect(() => {
		if (delPhase !== 'armed' && !armResub) return;
		const onDown = (e: PointerEvent): void => {
			const t = e.target as Node | null;
			if (t && (delBtn?.contains(t) || resubBtn?.contains(t))) return;
			disarm();
		};
		window.addEventListener('pointerdown', onDown, true);
		return () => window.removeEventListener('pointerdown', onDown, true);
	});

	$effect(() => () => {
		clearTimeout(delTimer);
		clearTimeout(resubTimer);
	});

	async function delSubmission(): Promise<void> {
		if (!card || delPhase === 'busy' || !account) return;
		const id = hw?.id ?? card.id;
		clearTimeout(delTimer);
		delPhase = 'busy';
		try {
			await api.deleteSubmission(account, id);
			justDeleted = true;
			// одразу оновлюємо модалку: робота більше не «на перевірці»
			if (card) card = { ...card, submission_id: null, status: 3, status_label: 'До виконання' };
			showToast('Роботу видалено з перевірки', 3500, 'success');
			onchanged(); // список домашок у батька
			void load(); // синхронізація з сервером без скелетона
		} catch (ex) {
			showToast(friendlyError(ex as ApiError), 4500, 'error');
			void load(); // можливо, стан уже інший (напр. роботу вже видалено)
		} finally {
			delPhase = 'idle';
		}
	}

	let errEl = $state<HTMLElement>();
	$effect(() => {
		if (err && errEl) shake(errEl);
	});

	let loading = $state(false);
	let err = $state('');
	let card: HwCard | null = $state(null);

	// Вхідна анімація вмісту — один раз за відкриття: стару картку не скидаємо
	// при оновленні, лише при новому відкритті/іншому ДЗ.
	// ⚠️ Ефект залежить ЛИШЕ від open/hwId/account. load() читає `card` — без untrack
	// ефект перезапускався при кожному оновленні картки: нескінченний цикл запитів
	// і постійний disarm() (через це кнопка підтвердження миттєво «відкочувалась»).
	let shownHwId: number | string | null = null;
	const hwId = $derived(hw?.id ?? null);
	$effect(() => {
		const isOpen = open;
		const id = hwId;
		const acc = account;
		untrack(() => {
			if (isOpen && id !== null && acc) {
				if (shownHwId !== id) {
					shownHwId = id;
					card = null;
					justDeleted = false;
				}
				disarm();
				void load();
				void loadLinks();
			} else if (!isOpen) {
				shownHwId = null;
				loadGen++;
				linksGen++;
				disarm();
			}
		});
	});

	async function load(): Promise<void> {
		if (!hw || !account) return;
		const gen = ++loadGen;
		const reqId = hw.id;
		const hadCard = !!card;
		loading = !hadCard; // скелетон лише при першому завантаженні
		if (!hadCard) err = '';
		try {
			const fresh = await api.hwCard(account, reqId);
			if (gen !== loadGen) return; // застаріла відповідь (інше ДЗ або новіший запит)
			card =
				justDeleted && fresh.submission_id
					? { ...fresh, submission_id: null, status: 3, status_label: 'До виконання' }
					: fresh;
			err = '';
		} catch (ex) {
			if (gen !== loadGen) return;
			// фонове оновлення не ховає вже показану картку — лише тост
			if (hadCard) showToast(friendlyError(ex as ApiError), 4000, 'error');
			else err = friendlyError(ex as ApiError);
		} finally {
			if (gen === loadGen) loading = false;
		}
	}

	function close(): void {
		onclose();
	}

	const STATUS_CLS: Record<number, string> = {
		3: 'c-accent',
		2: 'c-cyan',
		1: 'c-success',
		5: 'c-danger',
		6: 'c-danger'
	};

	function fmtD(s?: string | null): string {
		if (!s || s.startsWith('-0001')) return '—';
		const d = s.slice(0, 10);
		const p = d.split('-');
		return p.length === 3 ? `${p[2]}.${p[1]}.${p[0]}` : d;
	}

	function initials(fio?: string | null): string {
		const parts = (fio ?? '').trim().split(/\s+/).slice(0, 2);
		return parts.map((p) => p[0]?.toUpperCase() ?? '').join('') || '?';
	}

	function who(t?: string | null): string {
		if (!t) return '';
		if (t.includes('student')) return 'Ви';
		if (t.includes('teacher')) return 'Викладач';
		return t;
	}

	// переглядач файлів ДЗ: «Спробувати відкрити в браузері?» → рендер у модалці
	let viewerOpen = $state(false);
	let viewerUrl = $state('');
	let viewerName = $state('');

	function openViewer(u?: string | null): void {
		if (!u) return;
		viewerUrl = u;
		viewerName = '';
		try {
			const p = new URL(u, window.location.href);
			viewerName = decodeURIComponent(p.pathname.split('/').pop() ?? '') || '';
		} catch { viewerName = ''; }
		viewerOpen = true;
	}

	// capture-фаза: переглядач файлів/M1-модалка поверх ще "відкриті" на момент події
	function onKeydown(e: KeyboardEvent): void {
		if (!open || e.key !== 'Escape' || e.defaultPrevented) return;
		if (viewerOpen || m1ModalOpen) return; // Esc закриє лише верхнє вікно
		if (delPhase === 'armed' || armResub) {
			e.preventDefault();
			disarm(); // Esc спершу скасовує підтвердження
			return;
		}
		if (delPhase === 'busy') return;
		close();
	}
</script>

<svelte:window onkeydowncapture={onKeydown} />

{#if open}
	<div
		class="ovl"
		onclick={close}
		onkeydown={(e) => e.key === 'Enter' && close()}
		role="button"
		tabindex="-1"
		aria-label="Закрити вікно"></div>
	<div
		class="panel glass {STATUS_CLS[card?.status ?? hw?.status ?? 0] ?? ''}"
		role="dialog"
		aria-modal="true"
		aria-label="Деталі завдання">
		<header>
			<h3><FileText size={18} /> Деталі завдання</h3>
			<button class="x" onclick={close} aria-label="Закрити"><X size={20} /></button>
		</header>

		<div class="body">
			{#if loading}
				<div class="skl">
					<div class="sk-line shimmer w60"></div>
					<div class="sk-line shimmer w40"></div>
					<div class="sk-line shimmer"></div>
					<div class="sk-line shimmer w80"></div>
				</div>
			{:else if err}
				<p class="err" bind:this={errEl} in:blurFade={{ y: 4 }}>⚠ {err}</p>
				<button class="btn ghost" use:pressable onclick={() => void load()}>Спробувати ще раз</button>
			{:else if card}
				<div
					class="content"
					in:blurFade={{ duration: 380, amount: 6, y: 6 }}
					use:stagger={{ selector: ':scope > *', step: 35, y: 12, max: 10 }}
				>
				<div class="chips">
					<span class="chip st">{card.status === 6 && (!card.status_label || card.status_label === '?') ? 'Прострочено' : card.status_label}</span>
					{#if hwKindTag(card.kind)}<span class="chip">{hwKindTag(card.kind).toLowerCase()}</span>{/if}
					{#if card.mark !== null && card.mark !== ''}
						<span class="chip mark">оцінка {card.mark}</span>
					{/if}
					{#if card.late_penalty}
						<span class="chip coins" title="Дедлайн давно минув — здача коштує монети">
							<Coins size={13} /> −<AnimatedNumber value={Number(card.late_penalty) || 0} duration={700} />
						</span>
					{/if}
				</div>

				<h4>{card.title}</h4>
				<p class="subj text-dim small">{card.subject}</p>

				<div class="teacher">
					{#if card.teach_photo}
						<img src={card.teach_photo} alt="" class="ava" />
					{:else}
						<span class="ava ini">{initials(cleanTeacher(card.teacher))}</span>
					{/if}
					<span>
						<small class="text-faint">Викладач</small>
						<b>{cleanTeacher(card.teacher) || '—'}</b>
					</span>
				</div>

				<dl class="facts">
					<div><dt><CalendarDays size={14} /> Створено</dt><dd>{fmtD(card.assigned)}</dd></div>
					<div><dt><CalendarDays size={14} /> Дедлайн</dt><dd>{fmtD(card.due)}</dd></div>
					{#if card.submitted_at && !card.submitted_at.startsWith('-0001')}
						<div><dt><CalendarDays size={14} /> Здано</dt><dd>{fmtD(card.submitted_at)}</dd></div>
					{/if}
					{#if card.completed}
						<div><dt><CalendarDays size={14} /> Завершено</dt><dd>{fmtD(card.completed)}</dd></div>
					{/if}
				</dl>

				{#if card.description}
					<h5><FileText size={15} /> Опис</h5>
					<p class="block">{card.description}</p>
				{/if}

				{#if card.attachment}
					<button class="attach" onclick={() => openViewer(card?.attachment)}>
						<Paperclip size={16} />
						<span class="att-label">Відкрити завдання</span>
						<ExternalLink size={15} />
					</button>
				{/if}

				{#if card.answer_text || card.answer_files.length}
					<h5><Send size={15} /> Моя відповідь</h5>
					{#if card.answer_text}<p class="block me">{card.answer_text}</p>{/if}
					{#each card.answer_files as f, i (f)}
						<!-- свої файли: без переглядача, просто пряме посилання -->
						<a class="flink" href={safeUrl(f)} target="_blank" rel="noopener">
							<FileText size={15} /> Файл відповіді {i + 1}<ExternalLink size={13} />
						</a>
					{/each}
				{/if}

				{#if m1Count > 0}
					<button class="flink" onclick={() => (m1ModalOpen = true)}>
						<Link2 size={15} /> M1 Provider
						<span class="m1-badge"><Eye size={11} /> <AnimatedNumber value={m1Opens} duration={700} /></span>
					</button>
				{/if}
				{#if card.teacher_comment}
					<h5><MessageCircle size={15} /> Коментар викладача</h5>
					<p class="block tc">{card.teacher_comment}</p>
				{/if}

				{#if card.history.length > 1 || (card.history.length === 1 && !card.answer_text)}
					<h5><MessageCircle size={15} /> Історія</h5>
					<ul class="hist" use:stagger={{ step: 40, y: 10, max: 8 }}>
						{#each card.history as h, i (i)}
							<li style="--i:{i}">
								<small class="text-faint">{who(h.type)} · {fmtD(h.date)}</small>
								{#if h.text}<p>{h.text}</p>{/if}
								{#if h.file}
									{#if who(h.type) === 'Ви'}
										<!-- свій файл: без переглядача, пряме посилання -->
										<a class="flink" href={safeUrl(h.file)} target="_blank" rel="noopener">
											<FileText size={14} /> файл<ExternalLink size={12} />
										</a>
									{:else}
										<button class="flink" onclick={() => openViewer(h.file)}>
											<FileText size={14} /> файл<ExternalLink size={12} />
										</button>
									{/if}
								{/if}
							</li>
						{/each}
					</ul>
				{/if}
				</div>
			{/if}
		</div>

		{#if !loading && !err && card}
			<footer use:stagger={{ selector: ':scope > *', step: 50, y: 8, max: 6 }}>
				{#if card.status !== 1 && card.status !== 2}
					<button class="btn primary" use:pressable onclick={() => onsubmitrequest('submit')}>
						<Send size={16} /> Здати роботу
						{#if card.late_penalty}
							<span class="cost" title="Дедлайн давно минув — здача коштує монети">−{card.late_penalty} <Coins size={13} /></span>
						{/if}
					</button>
				{:else if card.status === 1}
					<button
						bind:this={resubBtn}
						class="btn primary armable"
						class:armed={armResub}
						use:pressable
						onclick={onResubClick}>
						{#if armResub}<span class="fill" aria-hidden="true"></span>{/if}
						<Send size={16} />
						{#key armResub}<span class="lbl" in:blurFade={{ duration: 220, amount: 4, y: 5 }}
								>{armResub ? 'Точно перездати?' : 'Перездати'}</span
							>{/key}
						<span class="cost" title="Запит на перездачу коштує монети">−{card.retake_cost ?? 2} <Coins size={13} /></span>
					</button>
				{/if}

				{#if card.submission_id && card.status === 2}
					<button
						bind:this={delBtn}
						class="btn ghost armable"
						class:armed={delPhase === 'armed'}
						class:busy={delPhase === 'busy'}
						use:pressable
						disabled={delPhase === 'busy'}
						aria-busy={delPhase === 'busy'}
						onclick={onDeleteClick}>
						{#if delPhase === 'armed'}<span class="fill" aria-hidden="true"></span>{/if}
						{#if delPhase === 'busy'}<Spinner size={16} label="Видаляю" />{:else}<Trash2 size={16} />{/if}
						{#key delPhase}<span class="lbl" in:blurFade={{ duration: 220, amount: 4, y: 5 }}
								>{delPhase === 'busy' ? 'Видаляю…' : delPhase === 'armed' ? 'Точно видалити?' : 'Видалити з перевірки'}</span
							>{/key}
					</button>
				{/if}

				<button class="btn ghost" use:pressable onclick={close}>Закрити</button>
			</footer>
		{/if}
	</div>
{/if}

{#if open && hw}
<M1LinkModal
	open={m1ModalOpen}
	hwId={hw?.id ?? 0}
	hwTitle={hw?.title ?? ''}
	account={account}
	onclose={() => (m1ModalOpen = false)}
	onchanged={() => { void load(); void loadLinks(); }}
/>
{/if}

<FileViewerModal
	open={viewerOpen}
	url={viewerUrl}
	name={viewerName}
	onclose={() => (viewerOpen = false)}
/>

<style>
	.ovl {
		position: fixed;
		inset: 0;
		background: rgba(5, 7, 12, 0.62);
		-webkit-backdrop-filter: blur(calc(6px + 0px));
		backdrop-filter: blur(calc(6px + 0px));
		z-index: 60;
		animation: m1-fade 0.18s ease;
	}
	/* lite: без backdrop-filter, темніший суцільний фон */
	:global(html[data-perf='lite']) .ovl {
		-webkit-backdrop-filter: none;
		backdrop-filter: none;
		background: rgba(5, 7, 12, 0.78);
	}

	.panel {
		position: fixed;
		left: 50%;
		top: 50%;
		transform: translate(-50%, -50%);
		width: min(560px, 94vw);
		max-height: 88dvh;
		display: flex;
		flex-direction: column;
		border-radius: var(--radius-lg, 16px);
		z-index: 61;
		animation: m1-pop 0.22s cubic-bezier(0.34, 1.56, 0.64, 1);
		border-left: 3px solid var(--text-faint);
	}

	.panel.c-accent { border-left-color: var(--accent); }
	.panel.c-cyan { border-left-color: var(--cyan); }
	.panel.c-success { border-left-color: var(--success); }
	.panel.c-danger { border-left-color: var(--danger); }

	header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 14px 16px 8px;
	}

	header h3 {
		margin: 0;
		font-size: 16px;
		display: inline-flex;
		align-items: center;
		gap: 8px;
		color: var(--accent);
	}

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

	.body {
		padding: 4px 16px 10px;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	h4 { margin: 0; font-size: 17px; line-height: 1.3; }

	.content { display: flex; flex-direction: column; gap: 10px; }

	.chips { display: flex; gap: 6px; flex-wrap: wrap; }

	/* чіпи статусу «вискакують» по черзі */
	.chips .chip { animation: hd-chip 460ms var(--ease-spring) both; }
	.chips .chip:nth-child(1) { animation-delay: 140ms; }
	.chips .chip:nth-child(2) { animation-delay: 210ms; }
	.chips .chip:nth-child(3) { animation-delay: 280ms; }
	.chips .chip:nth-child(4) { animation-delay: 350ms; }
	@keyframes hd-chip {
		from { opacity: 0; transform: scale(0.5); }
	}

	.chip {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 3px 9px;
		border-radius: 999px;
		background: var(--surface-2);
		font-size: 12px;
		color: var(--text-dim);
	}

	.chip.mark { color: var(--amber, #ffb454); font-weight: 600; }
	.chip.st { color: var(--text); border: 1px solid var(--surface-2); }
	.chip.coins { color: var(--amber, #ffb454); }
	.cost {
		display: inline-flex;
		align-items: center;
		gap: 3px;
		margin-left: 6px;
		padding: 1px 7px;
		border-radius: 999px;
		font-size: 12px;
		font-weight: 600;
		color: var(--amber, #ffb454);
		background: color-mix(in srgb, var(--amber, #ffb454) 14%, transparent);
	}

	.teacher {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 9px 11px;
		border-radius: 12px;
		background: var(--surface-2);
		width: fit-content;
		max-width: 100%;
	}

	.teacher b { display: block; font-size: 13.5px; }

	.ava {
		width: 34px;
		height: 34px;
		border-radius: 50%;
		object-fit: cover;
		flex-shrink: 0;
	}

	.ini {
		display: grid;
		place-items: center;
		background: var(--accent);
		color: #fff;
		font-size: 12px;
		font-weight: 700;
	}

	.facts {
		margin: 0;
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
		gap: 8px 14px;
	}

	.facts dt {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		font-size: 11.5px;
		color: var(--text-faint);
	}

	.facts dd { margin: 1px 0 0; font-size: 13.5px; }

	h5 {
		margin: 6px 0 0;
		font-size: 12px;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-dim);
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}

	.block {
		margin: 0;
		padding: 10px 12px;
		background: var(--surface-2);
		border-radius: 12px;
		font-size: 13.5px;
		line-height: 1.55;
		white-space: pre-wrap;
		word-break: break-word;
	}

	.block.tc { border-left: 2px solid var(--amber, #ffb454); }

	.attach {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 11px 13px;
		border-radius: 12px;
		border: 1px dashed var(--accent);
		background: transparent;
		color: var(--accent);
		cursor: pointer;
		font: inherit;
		font-weight: 600;
		transition: background 0.15s ease;
	}

	.attach:hover { background: rgba(108, 124, 255, 0.08); }
	.att-label { flex: 1; text-align: left; }

	.flink {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 7px 11px;
		border-radius: 10px;
		border: none;
		background: var(--surface-2);
		color: var(--cyan);
		cursor: pointer;
		font-size: 13px;
		width: fit-content;
		text-decoration: none;
	}

	.flink:hover { filter: brightness(1.15); }

	.hist { position: relative; list-style: none; margin: 0; padding: 0 0 0 20px; display: flex; flex-direction: column; gap: 8px; }
	/* вертикальний конектор таймлайну «малюється» зверху вниз */
	.hist::before {
		content: '';
		position: absolute;
		left: 6px;
		top: 12px;
		bottom: 12px;
		width: 2px;
		border-radius: 2px;
		background: linear-gradient(var(--accent), color-mix(in srgb, var(--accent) 15%, transparent));
		transform-origin: top;
		animation: hd-line 700ms var(--ease-out) 150ms both;
	}
	@keyframes hd-line { from { transform: scaleY(0); } }
	.hist li { position: relative; padding: 8px 11px; background: var(--surface-2); border-radius: 10px; font-size: 13px; }
	.hist li::before {
		content: '';
		position: absolute;
		left: -18px;
		top: 14px;
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: var(--accent);
		box-shadow: 0 0 0 3px var(--surface);
		animation: hd-dot 420ms var(--ease-spring) both;
		animation-delay: calc(min(var(--i, 0), 7) * 40ms + 250ms);
	}
	@keyframes hd-dot { from { opacity: 0; transform: scale(0); } }
	.hist li p { margin: 3px 0 0; white-space: pre-wrap; word-break: break-word; }

	footer {
		display: flex;
		gap: 8px;
		padding: 10px 16px 14px;
		border-top: 1px solid var(--surface-2);
		flex-wrap: wrap;
	}

	.btn.danger {
		background: var(--danger);
		border-color: transparent;
		color: #fff;
	}

	.btn.danger:hover:not(:disabled) {
		filter: brightness(1.08);
	}

	/* двоетапне підтвердження: колір плавно «заливається», підпис перетікає */
	.btn.armable {
		position: relative;
		overflow: hidden;
		transition: color 240ms var(--ease-out), border-color 240ms var(--ease-out);
	}
	.btn.armable::before {
		content: '';
		position: absolute;
		inset: 0;
		border-radius: inherit;
		background: var(--danger);
		opacity: 0;
		transition: opacity 260ms var(--ease-out);
	}
	.btn.armable.armed,
	.btn.armable.busy {
		color: #fff;
		border-color: transparent;
		animation: hd-arm 420ms var(--ease-spring);
	}
	.btn.armable.armed::before,
	.btn.armable.busy::before { opacity: 1; }
	.btn.armable.busy { animation: none; cursor: progress; }
	.btn.armable.busy:disabled { opacity: 1; }
	.btn.armable > :global(*):not(.fill) { position: relative; }
	/* смужка-таймер: спорожнюється за ARM_MS (3с), потім підтвердження скидається */
	.fill {
		position: absolute;
		left: 0;
		right: 0;
		bottom: 0;
		height: 3px;
		background: rgba(255, 255, 255, 0.7);
		transform-origin: left center;
		animation: hd-drain 3000ms linear forwards;
		pointer-events: none;
	}
	@keyframes hd-drain { from { transform: scaleX(1); } to { transform: scaleX(0); } }
	.lbl { display: inline-block; }
	@keyframes hd-arm {
		0% { transform: scale(1); }
		40% { transform: scale(1.04); }
		100% { transform: scale(1); }
	}
	:global(html[data-anim='off']) :is(.chips .chip, .hist::before, .hist li::before, .btn.armable.armed) {
		animation: none;
	}
	:global(html[data-anim='off']) .btn.armable,
	:global(html[data-anim='off']) .btn.armable::before {
		transition: none;
	}

	.err { margin: 8px 0; color: var(--danger); font-size: 14px; }

	.skl { display: flex; flex-direction: column; gap: 9px; padding: 6px 0; }
	.sk-line { height: 14px; border-radius: 7px; background: var(--surface-2); animation: m1-pulse 1.2s ease infinite; width: 100%; }
	.sk-line.w40 { width: 40%; }
	.sk-line.w60 { width: 60%; }
	.sk-line.w80 { width: 80%; }

	/* Нижня панель (≤900px): модалка центрується у вільній зоні над нею. */
	@media (max-width: 900px) {
		.panel {
			top: calc((100dvh - var(--nav-total, 0px)) / 2);
			max-height: calc(100dvh - var(--nav-total, 0px) - 24px);
		}
	}

	@media (max-width: 640px) {
		.panel {
			width: min(560px, 100vw - 24px);
			max-height: calc(100dvh - var(--nav-total, 0px) - 20px);
		}
	}

	@keyframes m1-fade { from { opacity: 0; } }
	@keyframes m1-pop { from { opacity: 0; transform: translate(-50%, -46%) scale(0.96); } }
	@keyframes m1-sheet { from { transform: translateY(40%); opacity: 0; } }

	.m1-badge {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 2px 8px;
		border-radius: 999px;
		background: rgba(108, 124, 255, 0.14);
		color: var(--accent);
		font-size: 11px;
		margin-left: 6px;
	}

	.flink.dim {
		opacity: 0.6;
	}

	.mini {
		border: 1px solid var(--glass-border);
		border-radius: 8px;
		background: transparent;
		color: var(--text-dim);
		font: inherit;
		font-size: 12px;
		padding: 4px 8px;
		cursor: pointer;
		flex-shrink: 0;
	}

	.mini:hover {
		color: var(--accent);
		border-color: var(--accent);
	}

	.mini.danger:hover {
		color: var(--danger);
		border-color: var(--danger);
	}

	.mini.ok {
		color: var(--success);
		border-color: var(--success);
	}

	.editrow {
		display: flex;
		gap: 6px;
		margin: -4px 0 4px;
	}

	.editrow input {
		flex: 1;
		min-width: 0;
		padding: 7px 10px;
		border: 1px solid var(--glass-border);
		border-radius: 8px;
		background: var(--surface-2);
		color: var(--text);
		font: inherit;
		font-size: 12.5px;
	}

	.editrow input:focus {
		outline: none;
		border-color: var(--accent);
	}
</style>
