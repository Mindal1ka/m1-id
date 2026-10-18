<script lang="ts">
	import { api, type ExtrasStatus } from '$lib/api/client';
	import { friendlyError } from '$lib/errors';
	import {
		BellRing,
		CheckCheck,
		Clock,
		Plug,
		PlugZap,
		Sparkles,
		Star
	} from '@lucide/svelte';
	import { blurFade, pressable, springIn, stagger } from '$lib/motion';

	let { active = false }: { active?: boolean } = $props();

	let status = $state<ExtrasStatus | null>(null);
	let loading = $state(true);
	let err = $state('');
	let note = $state('');
	let busy = $state(false);
	let selectedSeq = $state<number | null>(null);

	async function load(): Promise<void> {
		try {
			err = '';
			status = await api.extrasStatus();
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

	// Поки вкладка відкрита: тримаємо статус свіжим (стан з'єднання
	// підключення відображається наживо)
	$effect(() => {
		if (!active) return;
		void load();
		const t = window.setInterval(() => {
			// у фоновій вкладці браузера не смикаємо мережу й DOM
			if (!document.hidden) void load();
		}, 8000);
		return () => window.clearInterval(t);
	});

	const selected = $derived(
		status?.accounts?.find((a) => a.account_seq === selectedSeq) ?? null
	);

	async function toggle(key: 'socket_enabled' | 'auto_eval', val: boolean): Promise<void> {
		if (selectedSeq === null || busy) return;
		const acc = status?.accounts?.find((a) => a.account_seq === selectedSeq);
		if (!acc) return;
		const prev = { socket_enabled: acc.socket_enabled, auto_eval: acc.auto_eval };
		acc[key] = val;
		try {
			const fresh = await api.extrasSaveSettings({ account_seq: selectedSeq, [key]: val });
			acc.socket_enabled = fresh.socket_enabled;
			acc.auto_eval = fresh.auto_eval;
			err = '';
			if (key === 'auto_eval' && val) {
				note = 'Автооцінювання ввімкнено - сокет підключається…';
				window.setTimeout(() => (note = ''), 3500);
			}
		} catch (e) {
			acc.socket_enabled = prev.socket_enabled;
			acc.auto_eval = prev.auto_eval;
			err = friendlyError(e);
		}
	}

	function fmtWhen(iso: string | null): string {
		if (!iso) return '- ще не було';
		try {
			return new Date(iso).toLocaleTimeString('uk-UA', {
				hour: '2-digit',
				minute: '2-digit'
			});
		} catch {
			return iso;
		}
	}

	function accTitle(seq: number): string {
		const a = status?.accounts?.find((x) => x.account_seq === seq);
		return a?.login || `Акаунт #${seq}`;
	}
</script>

<div class="ex">
	{#if loading}
		<p class="text-dim small">Завантаження…</p>
	{:else if status && !status.available}
		<div class="glass card-warn">
			<Plug size={18} strokeWidth={2} />
			<p>Сокет-клієнт не встановлено на сервері (<code>python-socketio</code>).
				Постав залежності та перезапусти бекенд.</p>
		</div>
	{:else if status && status.accounts.length}
		{#if status.accounts.length > 1}
			<span class="lbl">Акаунт (налаштування окремі для кожного):</span>
			<div class="accseg">
				{#each status.accounts as a (a.account_seq)}
					<button
						class:on={selectedSeq === a.account_seq}
						onclick={() => (selectedSeq = a.account_seq)}
					>{a.login || `Акаунт #${a.account_seq}`}</button>
				{/each}
			</div>
		{/if}

		{#if selected}
			<p class="hint">
				Що вмикається для <b>{accTitle(selected.account_seq)}</b>:
			</p>

			{#key selectedSeq}
			<div class="rows" use:stagger={{ step: 55, max: 8, y: 10, scale: true }}>
				<div class="row">
					<span class="t-ico"><PlugZap size={16} strokeWidth={2} /></span>
					<div class="txt">
						<span class="ttl">Миттєві оновлення</span>
						<span class="desc">
							Нова домашка, оцінка або зміна рейтингу - дізнаєтеся за
							секунди, а не через пів години. Сервер MyStat сам
							повідомляє про кожну зміну.
						</span>
					</div>
					<label class="switch">
						<input
							type="checkbox"
							checked={selected.socket_enabled}
							onchange={(e) => toggle('socket_enabled', e.currentTarget.checked)}
						/>
						<i></i>
					</label>
				</div>

				<div class="row">
					<span class="t-ico"><Star size={16} strokeWidth={2} /></span>
					<div class="txt">
						<span class="ttl">Автооцінювання уроків</span>
						<span class="desc">
							MyStat просить «оцінити заняття»? Оцінимо самі: 5 за урок і
							5 викладачу, без коментаря. Одразу, як тільки урок надійде.
						</span>
					</div>
					<label class="switch">
						<input
							type="checkbox"
							checked={selected.auto_eval}
							onchange={(e) => toggle('auto_eval', e.currentTarget.checked)}
						/>
						<i></i>
					</label>
				</div>

				<div class="row" class:dim={!selected.socket_enabled}>
					<span class="t-ico"><Plug size={16} strokeWidth={2} /></span>
					<div class="txt">
						<span class="ttl">Статус</span>
						<span class="desc">
							{#key !selected.socket_enabled ? 'off' : selected.connected ? 'on' : 'wait'}
								<span class="stx" in:blurFade={{ duration: 300, amount: 4 }}>
									{#if !selected.socket_enabled}
										Вимкнено - увімкніть тумблер вище
									{:else if selected.connected}
										Підключено до MyStat - усе працює
									{:else}
										Підключаємося…{selected.last_error ? ` (${selected.last_error})` : ''}
									{/if}
								</span>
							{/key}
						</span>
					</div>
				</div>

				{#if selected.auto_eval}
					<div class="row" class:dim={!selected.socket_enabled}
						in:springIn={{ duration: 380, start: 0.95, y: 8 }}
						out:blurFade={{ duration: 180, amount: 0 }}>
						<span class="t-ico"><CheckCheck size={16} strokeWidth={2} /></span>
						<div class="txt">
							<span class="ttl">Остання оцінка</span>
							<span class="desc">
								{#if selected.last_eval}
									{selected.last_eval.theme || 'Урок'} - о {fmtWhen(selected.last_eval.rated_at)}
								{:else}
									Ще нічого не оцінювали - оцінимо перший урок, що прийде
								{/if}
							</span>
						</div>
					</div>
					{#if selected.pending_evals > 0}
						<div class="row" in:springIn={{ duration: 380, start: 0.95, y: 8 }}
							out:blurFade={{ duration: 180, amount: 0 }}>
							<span class="t-ico"><Clock size={16} strokeWidth={2} /></span>
							<div class="txt">
								<span class="ttl">Чекає ранку</span>
								<span class="desc">
									{selected.pending_evals} урок(ів) надійшли вночі -
									оцінимо після 05:00
								</span>
							</div>
						</div>
					{/if}
					<div class="row" in:springIn={{ duration: 380, start: 0.95, y: 8, delay: 70 }}
						out:blurFade={{ duration: 180, amount: 0 }}>
						<span class="t-ico"><BellRing size={16} strokeWidth={2} /></span>
						<div class="txt">
							<span class="ttl">Повідомлення про оцінки</span>
							<span class="desc">
								Хочете знати, що урок оцінено? Увімкніть «Оцінка уроку»
								у налаштуваннях Telegram.
							</span>
						</div>
					</div>
				{/if}
			</div>
			{/key}

			<p class="soon" in:blurFade={{ duration: 400, amount: 4, delay: 300 }}>
				<Sparkles size={13} strokeWidth={2} />
				Тут незабаром з'явиться ще більше функцій
			</p>
		{/if}
	{:else}
		<p class="text-dim small">Підключіть акаунт MyStat - і тут з'являться налаштування.</p>
	{/if}

	{#if note}<p class="note" in:springIn={{ duration: 340, start: 0.94, y: 6 }} out:blurFade={{ duration: 180, amount: 3 }}>{note}</p>{/if}
	{#if err}<p class="err">{err}</p>{/if}
</div>

<style>
	.ex {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.card-warn {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 12px 14px;
		border-radius: var(--radius-md);
		font-size: 13px;
		color: var(--text-dim);
	}

	.card-warn p {
		margin: 0;
	}

	.card-warn code {
		font-size: 12px;
		color: var(--cyan);
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

	.row.dim {
		opacity: 0.55;
	}

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

	.soon {
		margin: 2px 0 0;
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 12px;
		color: var(--text-faint);
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
