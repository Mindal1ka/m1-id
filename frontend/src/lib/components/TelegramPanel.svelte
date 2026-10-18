<script lang="ts">
	import { confirm } from '$lib/ui';
	import {
		api,
		type LbScopeMeta,
		type TelegramAccountInfo,
		type TelegramSettings,
		type TelegramStatus
	} from '$lib/api/client';
	import { friendlyError } from '$lib/errors';
	import { safeUrl } from '$lib/sanitize';
	import { blurFade, pressable, springIn, stagger } from '$lib/motion';
	import {
		AlarmClock,
		BookOpen,
		Bell,
		CalendarClock,
		CalendarDays,
		GraduationCap,
		Eye,
		Medal,
		MoonStar,
		Send,
		ShoppingBag,
		Star,
		Sunrise,
		Trophy,
		Unlink
	} from '@lucide/svelte';
	let { active = false }: { active?: boolean } = $props();

	let status = $state<TelegramStatus | null>(null);
	let loading = $state(true);
	let err = $state('');
	let note = $state('');
	let busy = $state(false);
	let unlinking = $state(false);
	let selectedSeq = $state<number | null>(null);

	async function load(): Promise<void> {
		try {
			err = '';
			status = await api.tgStatus();
			// тримаємо вибір користувача, якщо акаунт ще існує
			const accs = status.accounts ?? [];
			if (selectedSeq === null || !accs.some((a) => a.account_seq === selectedSeq)) {
				selectedSeq = accs[0]?.account_seq ?? null;
			}
		} catch (e) {
			err = friendlyError(e);
		} finally {
			loading = false;
		}
	}

	// Поки вкладка відкрита: завантажити статус; якщо не прив'язано -
	// опитувати кожні 3с, щоб прив'язка через QR підхопилась автоматично.
	$effect(() => {
		if (!active) return;
		void load();
		const t = window.setInterval(() => {
			if (!document.hidden && (status === null || !status.linked)) void load();
		}, 3000);
		return () => window.clearInterval(t);
	});

	/** Фаза панелі (завантаження / прив'язано / ні) — ключ для кросфейду. */
	const phase = $derived(loading ? 'loading' : status?.linked ? 'linked' : 'unlinked');

	const selected = $derived(
		status?.accounts?.find((a) => a.account_seq === selectedSeq) ?? null
	);

	type ToggleKey = {
		[K in keyof TelegramSettings]: TelegramSettings[K] extends boolean ? K : never
	}[keyof TelegramSettings];

	/* Іконки - з основного паку сайту (Lucide), без емодзі */
	const TOGGLES: {
		key: ToggleKey;
		icon: typeof BookOpen;
		title: string;
		desc: string;
	}[] = [
		{ key: 'homework_new', icon: BookOpen, title: 'Нова домашка', desc: 'Коли викладач додав завдання' },
		{
			key: 'deadlines',
			icon: AlarmClock,
			title: 'Нагадування про дедлайн',
			desc: 'За 24 год і за 3 год до здачі домашки'
		},
		{ key: 'marks_new', icon: GraduationCap, title: 'Нові оцінки', desc: 'Коли з’явиться нова оцінка' },
		{ key: 'rating_change', icon: Medal, title: 'Зміна рейтингу', desc: 'Коли зміниться ваш рейтинг' },
		{
			key: 'schedule_week_change',
			icon: CalendarDays,
			title: 'Розклад тижня змінився',
			desc: 'Заміни в поточному тижні'
		},
		{
			key: 'schedule_day_change',
			icon: CalendarClock,
			title: 'Розклад на сьогодні змінився',
			desc: 'Заміни пар на сьогодні'
		},
		{
			key: 'schedule_daily',
			icon: Sunrise,
			title: 'Розклад на день о 06:00',
			desc: 'Щоранку - розклад на сьогодні'
		},
		{
			key: 'leaderboard_change',
			icon: Trophy,
			title: 'Зміни лідерборду',
			desc: 'Коли зміниться порядок учасників'
		},
		{
			key: 'shop_change',
			icon: ShoppingBag,
			title: 'Зміни в магазині',
			desc: 'Нові або оновлені товари'
		},
		{
			key: 'quiet_hours',
			icon: MoonStar,
			title: 'Тихі години 23:00-05:00',
			desc: 'Уночі не смікати MyStat; усе накопичене прийде зранку (рекомендовано)'
		},
		{
			key: 'auto_eval_notify',
			icon: Star,
			title: 'Оцінка уроку',
			desc: 'Повідомляти, коли урок оцінено автоматично (Автооцінювання - у вкладці «Додаткові»)'
		},
		{
			key: 'link_open_notify',
			icon: Eye,
			title: 'Посилання відкрили',
			desc: 'Хтось відкрив ваше посилання з домашки (M1 Provider)'
		}
	];

	async function toggle(key: ToggleKey, val: boolean): Promise<void> {
		if (selectedSeq === null || busy) return;
		const acc = status?.accounts?.find((a) => a.account_seq === selectedSeq);
		if (!acc) return;
		const prev = acc.settings;
		if (prev) acc.settings = { ...prev, [key]: val };
		try {
			const fresh = await api.tgSaveSettings({ account_seq: selectedSeq, [key]: val });
			if (prev) acc.settings = fresh;
			err = '';
		} catch (e) {
			if (prev) acc.settings = prev;
			err = friendlyError(e);
		}
	}

	/* Який лідерборд моніторити: зрізи беремо з кешованого лідерборду
	 * акаунта (динамічні: школа - month/semester/year, академія -
	 * month/all_time). '' = стежити за всіма зрізами. */
	let lbScopes = $state<LbScopeMeta[]>([]);
	let lbScopesSeq = $state<number | null>(null);
	let lbLoading = $state(false);

	$effect(() => {
		const seq = selectedSeq;
		const want = selected?.settings?.leaderboard_change ?? false;
		if (!active || !want || seq === null || lbScopesSeq === seq) return;
		lbLoading = true;
		api.leaderboard(seq)
			.then((v) => {
				lbScopes = v.scopes ?? [];
				lbScopesSeq = seq;
			})
			.catch(() => {
				lbScopes = [];
				lbScopesSeq = seq;
			})
			.finally(() => (lbLoading = false));
	});

	function lbCurrent(): string {
		const s = selected?.settings;
		if (!s || (!s.leaderboard_scope && !s.leaderboard_period)) return '';
		return `${s.leaderboard_scope || ''}:${s.leaderboard_period || ''}`;
	}

	async function onLbPick(val: string): Promise<void> {
		if (selectedSeq === null || busy) return;
		const acc = status?.accounts?.find((a) => a.account_seq === selectedSeq);
		if (!acc?.settings) return;
		const i = val.indexOf(':');
		const scope = val === '' ? '' : val.slice(0, i);
		const period = val === '' ? '' : val.slice(i + 1);
		const prev = acc.settings;
		acc.settings = {
			...prev,
			leaderboard_scope: scope,
			leaderboard_period: period
		};
		try {
			const fresh = await api.tgSaveSettings({
				account_seq: selectedSeq,
				leaderboard_scope: scope,
				leaderboard_period: period
			});
			acc.settings = fresh;
			err = '';
		} catch (e) {
			acc.settings = prev;
			err = friendlyError(e);
		}
	}

	async function sendTest(): Promise<void> {
		if (busy) return;
		busy = true;
		try {
			await api.tgTest(selectedSeq ?? undefined);
			note = 'Тестове сповіщення надіслано - перевірте Telegram';
			window.setTimeout(() => (note = ''), 3500);
		} catch (e) {
			err = friendlyError(e);
		} finally {
			busy = false;
		}
	}

	async function unlink(): Promise<void> {
		if (unlinking) return;
		const ok = await confirm({
			title: 'Відв’язати Telegram?',
			message: 'Сповіщення більше не приходитимуть. Прив’язати акаунт знову можна будь-коли.',
			confirmText: 'Відв’язати',
			danger: true
		});
		if (!ok) return;
		unlinking = true;
		try {
			await api.tgUnlink();
			loading = true;
			await load();
		} catch (e) {
			err = friendlyError(e);
		} finally {
			unlinking = false;
		}
	}

	function accTitle(a: TelegramAccountInfo): string {
		return a.login || a.fio || a.label || `Акаунт #${a.account_seq}`;
	}
</script>

<div class="tg">
{#key phase}
<div class="tg st" in:blurFade|global={{ duration: 380, amount: 0, y: 6 }}>
	{#if loading}
		<p class="text-dim small">Завантаження…</p>
	{:else if status?.linked}
		<div class="linked">
			<span class="dot"></span>
			<span>
				<b>Акаунт прив'язано</b>
				{#if status.bot_username}
					<span class="text-dim small">· @{status.bot_username}</span>
				{/if}
			</span>
		</div>

		{#if (status.accounts?.length ?? 0) > 1}
			<span class="lbl">Акаунт (у кожного свій конфіг сповіщень):</span>
			<div class="accseg">
				{#each status.accounts as a (a.account_seq)}
					<button
						class:on={selectedSeq === a.account_seq}
						onclick={() => (selectedSeq = a.account_seq)}
						title={a.fio || a.label}
					>{accTitle(a)}</button>
				{/each}
			</div>
		{/if}

		{#if selected}
			<p class="hint">
				Що приходитиме в Telegram для <b>{accTitle(selected)}</b>:
			</p>
			{#key selectedSeq}
			<div class="rows" use:stagger={{ step: 28, max: 12, y: 8 }}>
				{#each TOGGLES as t (t.key)}
					{@const TIcon = t.icon}
					<div class="row">
						<span class="t-ico"><TIcon size={16} strokeWidth={2} /></span>
						<div class="txt">
							<span class="ttl">{t.title}</span>
							<span class="desc">{t.desc}</span>
						</div>
						<label class="switch">
							<input
								type="checkbox"
								checked={selected.settings?.[t.key] ?? false}
								disabled={!selected.settings}
								onchange={(e) => toggle(t.key, e.currentTarget.checked)}
							/>
							<i></i>
						</label>
					</div>
				{/each}
			</div>
			{/key}

			{#if selected.settings?.leaderboard_change}
				<span class="lbl" in:blurFade={{ duration: 300, amount: 4 }}>Лідерборд - сповіщати коли:</span>
				<div class="seg" in:springIn={{ duration: 380, start: 0.96, y: 6 }}>
					<button
						class:on={selected.settings.leaderboard_mine_only}
						onclick={() => toggle('leaderboard_mine_only', true)}
					>Лише моя позиція</button>
					<button
						class:on={!selected.settings.leaderboard_mine_only}
						onclick={() => toggle('leaderboard_mine_only', false)}
					>Усі зміни порядку</button>
				</div>
				<span class="lbl">Який саме лідерборд моніторити:</span>
				<select
					class="sel"
					in:springIn={{ duration: 380, start: 0.96, y: 6, delay: 60 }}
					value={lbCurrent()}
					disabled={lbLoading}
					onchange={(e) => onLbPick(e.currentTarget.value)}
				>
					<option value="">Усі зрізи (за замовчуванням)</option>
					{#each lbScopes as s (s.key)}
						{#each s.periods as p (p.key)}
							<option value={`${s.key}:${p.key}`}>{s.label} - {p.label}</option>
						{/each}
					{/each}
				</select>
				{#if lbLoading}
					<p class="desc">Завантаження зрізів…</p>
				{:else if !lbScopes.length}
					<p class="desc">
						Перелік зрізів з'явиться після першого відкриття
						лідерборду на сайті
					</p>
				{/if}
			{/if}
		{/if}

		{#if err}<p class="err">{err}</p>{/if}

		<div class="acts">
			<button class="cta" use:pressable onclick={sendTest} disabled={busy}>
				<Bell size={15} strokeWidth={2} />
				Тестове сповіщення
			</button>
			<button class="danger" onclick={unlink} disabled={unlinking}>
				<Unlink size={15} strokeWidth={2} />
				Відв'язати
			</button>
		</div>
		{#if note}<p class="note" in:springIn={{ duration: 340, start: 0.94, y: 6 }} out:blurFade={{ duration: 180, amount: 3 }}>{note}</p>{/if}
	{:else}
		<div class="bind">
			<div class="bind-info">
				<h5><Send size={16} strokeWidth={2} /> Підключіть Telegram</h5>
				<p>
					Сповіщення про <b>домашку, оцінки, заміни розкладу,
					рейтинг і магазин</b> - прямо в чат.
				</p>
				<ol class="steps">
					<li>Наведіть камеру телефона на QR-код - Telegram відкриється сам.</li>
					<li>Не спрацювало? Тисніть кнопку та надішліть боту <b>/start</b>.</li>
				</ol>
				{#if err}<p class="err">{err}</p>{/if}
				{#if status?.deep_link}
					<p class="copylbl text-dim small">Або скопіюйте посилання:</p>
					<code class="deeplink">{status.deep_link}</code>
				{/if}
			</div>
			<div class="bind-qr">
				{#if status?.qr_data_uri}
					<img class="qr" in:springIn|global={{ duration: 620, start: 0.7, y: 0, delay: 120 }} src={status.qr_data_uri}
						alt="QR-код для прив'язки Telegram" width="216" height="216" />
				{/if}
				{#if status?.deep_link}
					<a class="cta open" href={safeUrl(status.deep_link)} target="_blank"
						rel="noopener noreferrer">Відкрити в Telegram</a>
				{:else if status && !status.bot_configured}
					<p class="err">Бот ще не підключено на сервері - зайдіть пізніше.</p>
				{/if}
			</div>
		</div>
	{/if}
</div>
{/key}
</div>

<style>
	.tg {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	/* обгортка фази: той самий flex-стек, що й .tg (для кросфейду) */
	.tg.st {
		gap: 12px;
	}

	.linked {
		display: flex;
		align-items: center;
		gap: 9px;
		font-size: 14px;
	}

	.dot {
		width: 9px;
		height: 9px;
		border-radius: 50%;
		background: #37d67a;
		box-shadow: 0 0 8px rgba(55, 214, 122, 0.7);
		flex: none;
	}

	.hint {
		margin: 0;
		font-size: 13px;
		color: var(--text-dim);
	}

	.lbl {
		font-size: 13px;
		color: var(--text-dim);
	}

	/* --- вибір акаунта (логіни, як на сайті) --- */
	.accseg {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}

	.accseg button {
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
			background 0.2s ease;
	}

	.accseg button.on {
		color: var(--accent);
		border-color: var(--accent);
		background: var(--accent-soft);
	}

	.rows {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.row {
		display: flex;
		align-items: center;
		gap: 11px;
		padding: 9px 11px;
		text-align: left;
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-md);
	}

	/* іконка розділу - з паку сайту (Lucide), акцентна */
	.t-ico {
		flex: none;
		display: inline-flex;
		color: var(--accent);
		opacity: 0.9;
	}

	.txt {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 1px;
		min-width: 0;
		text-align: left;
	}

	.ttl {
		font-size: 13.5px;
		font-weight: 600;
	}

	.desc {
		font-size: 11.5px;
		color: var(--text-faint);
	}

	/* --- перемикач --- */
	.switch {
		position: relative;
		display: inline-block;
		width: 44px;
		height: 25px;
		cursor: pointer;
		flex: none;
	}

	.switch input {
		opacity: 0;
		width: 0;
		height: 0;
	}

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
		width: 19px;
		height: 19px;
		border-radius: 50%;
		background: var(--surface-2);
		box-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
		transition:
			transform 0.18s var(--ease-spring),
			background 0.2s ease;
	}

	.switch input:checked + i {
		background: var(--accent-soft);
	}

	.switch input:checked + i::before {
		transform: translateX(19px);
		background: var(--accent);
	}

	/* --- вибір режиму лідерборду --- */
	.seg {
		display: flex;
		gap: 8px;
	}

	.seg button {
		flex: 1;
		height: 34px;
		font-size: 12.5px;
		font-weight: 600;
		color: var(--text-dim);
		background: var(--glass-bg);
		border: 1.5px solid var(--glass-border);
		border-radius: var(--radius-md);
		cursor: pointer;
		transition:
			border-color 0.2s ease,
			color 0.2s ease,
			background 0.2s ease;
	}

	.seg button.on {
		color: var(--accent);
		border-color: var(--accent);
		background: var(--accent-soft);
	}

	/* вибір зрізу лідерборду (scope:period) */
	.sel {
		width: 100%;
		height: 36px;
		padding: 0 10px;
		font-size: 13px;
		color: var(--text);
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-md);
		outline: none;
	}

	.sel:focus {
		border-color: var(--accent);
	}

	.sel:disabled {
		opacity: 0.6;
	}

	/* --- кнопки --- */
	.acts {
		display: flex;
		gap: 8px;
		margin-top: 2px;
	}

	.cta {
		flex: 1;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
		height: 40px;
		font-size: 13px;
		font-weight: 700;
		color: #fff;
		background: var(--accent-strong);
		border: none;
		border-radius: var(--radius-md);
		cursor: pointer;
		text-decoration: none;
		box-shadow: 0 3px 14px color-mix(in srgb, var(--accent) 45%, transparent);
		transition: transform 0.15s var(--ease-spring), filter 0.2s ease;
	}

	.cta:hover {
		transform: translateY(-1px);
		filter: brightness(1.07);
	}

	.cta:disabled {
		opacity: 0.6;
		cursor: default;
	}

	/* кнопка прив'язки - звичайної ширини, по центру під QR */
	.cta.open {
		flex: none;
		width: auto;
		padding: 0 18px;
	}

	.danger {
		height: 40px;
		padding: 0 14px;
		font-size: 13px;
		font-weight: 600;
		color: #ff7a7a;
		background: transparent;
		border: 1.5px solid color-mix(in srgb, #ff7a7a 45%, transparent);
		border-radius: var(--radius-md);
		cursor: pointer;
		transition: background 0.2s ease;
	}

	.danger:hover {
		background: color-mix(in srgb, #ff7a7a 12%, transparent);
	}

	/* --- прив'язка: QR + кроки --- */
	.bind {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 10px 26px;
	}

	.bind-info {
		flex: 1 1 230px;
		display: flex;
		flex-direction: column;
		gap: 10px;
		min-width: 0;
	}

	.bind-info h5 {
		margin: 0;
		font-family: var(--font-display);
		font-size: 16px;
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.bind-info h5 :global(svg) {
		color: var(--accent);
	}

	.bind-info p {
		margin: 0;
		font-size: 13.5px;
		line-height: 1.5;
	}

	.bind-qr {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 12px;
		margin: 0 auto;
	}

	.steps {
		margin: 0;
		padding-left: 20px;
		font-size: 13px;
		color: var(--text-dim);
		display: flex;
		flex-direction: column;
		gap: 6px;
	}

	.qr {
		width: 216px;
		height: 216px;
		padding: 12px;
		background: #fff;
		border-radius: var(--radius-lg);
		box-shadow: var(--shadow-card);
	}

	.copylbl {
		margin: 0;
	}

	.deeplink {
		display: block;
		font-size: 11px;
		word-break: break-all;
		padding: 8px 10px;
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-md);
		color: var(--text-dim);
		user-select: all;
	}

	.err {
		margin: 0;
		font-size: 12.5px;
		color: #ff8f8f;
	}

	.note {
		margin: 0;
		font-size: 12.5px;
		color: #6fe3a1;
	}
</style>
