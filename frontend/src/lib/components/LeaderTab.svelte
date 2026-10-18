<script lang="ts">
	import { Trophy, Users, Globe, Coins } from '@lucide/svelte';
	import { AnimatedNumber, slideX, stagger } from '$lib/motion';
	import {
		api,
		type LeaderboardView,
		type LbSection
	} from '$lib/api/client';
	import { friendlyError, isNetworkError, OFFLINE_EMPTY } from '$lib/errors';
	import { initials } from '$lib/sections';

	let {
		account_id,
		my_fio,
		/** Тик «Оновити» з +page: змінився → перечитуємо з force=true. */
		refreshTick = 0
	}: {
		account_id: number;
		my_fio?: string | null;
		refreshTick?: number;
	} = $props();

	let data = $state<LeaderboardView | null>(null);
	/** Вибір користувача (рядки); валідність перевіряють derived -
	 *  якщо гілка mapi не має такого scope/period, беремо перший
	 *  доступний (школа: month/semester/year, академія: month/all_time). */
	let scope = $state<string>('');
	let period = $state<string>('');
	let err = $state('');

	async function load(force = false): Promise<void> {
		try {
			data = await api.leaderboard(account_id, force);
		} catch (e) {
			err = isNetworkError(e) ? OFFLINE_EMPTY : friendlyError(e);
		}
	}

	void load();

	// «Оновити» в топбарі: тик змінився → форс-перечитування (мимо кеша).
	$effect(() => {
		if (refreshTick > 0) void load(true);
	});

	const scopesMeta = $derived(data?.scopes ?? []);
	const curScope = $derived.by(() => {
		if (scopesMeta.some((s) => s.key === scope)) return scope;
		return scopesMeta[0]?.key ?? '';
	});
	const periodsMeta = $derived(
		scopesMeta.find((s) => s.key === curScope)?.periods ?? []
	);
	const curPeriod = $derived.by(() => {
		if (periodsMeta.some((p) => p.key === period)) return period;
		return periodsMeta[0]?.key ?? '';
	});
	const sec = $derived<LbSection>(
		data?.sections?.[curScope]?.[curPeriod] ?? {
			top: [],
			nearby: [],
			new_students: []
		}
	);
	const pts = $derived(data?.points?.[curScope] ?? null);

	/** Порівняння ПІБ без урахування порядку слів і регістру: профіль mapi
	 *  віддає «Іван Мендєлєєв» (name), а таблиця лідерів —
	 *  «Мендєлєєв Іван Олексійович» (fio_stud). */
	function fioWords(s: string): Set<string> {
		return new Set(
			s
				.toLowerCase()
				.replace(/[^\p{L}\s]/gu, ' ')
				.split(/\s+/)
				.filter((w) => w.length > 1)
		);
	}

	const myWords = $derived(
		my_fio ? fioWords(my_fio) : new Set<string>()
	);

	function isMe(r: { fio: string }): boolean {
		if (myWords.size === 0) return false;
		const w = fioWords(r.fio);
		for (const x of myWords) {
			if (!w.has(x)) return false;
		}
		return true;
	}

	/* ── Вигляд 1:1 як віджет «Лідери» на Головній ─────────────────
	 * Єдина стрічка: ①②③ медальйони, далі звичайні позиції, новенькі 🌱.
	 * «Поруч з тобою» — окремого заголовка немає: список суцільний,
	 * розрив позицій позначає «⋯» (як у віджеті). */
	const rows = $derived.by(() => {
		const all = [
			...sec.top,
			...sec.nearby,
			...sec.new_students
		];
		const seen = new Set<string>();
		return all.filter((r) => {
			const k = String(r.id);
			if (seen.has(k)) return false; // дублікати id (top ∩ nearby)
			seen.add(k);
			return true;
		});
	});
	const showGap = $derived(
		rows.length > 3 && (rows[3]?.position ?? 99) > 4
	);
	const myPos = $derived.by(() => {
		const mine = rows.find((r) => isMe(r));
		return mine?.position ?? pts?.position ?? null;
	});
</script>

<div class="b-head">
	<div class="b-swrow">
		<div class="b-sw" role="group" aria-label="Охоплення">
			{#each scopesMeta as s (s.key)}
				<button class:active={curScope === s.key}
					onclick={() => (scope = s.key)} title={s.label}>
					{#if s.key === 'stream'}
						<Globe size={13} />
					{:else}
						<Users size={13} />
					{/if}
					{s.label}
				</button>
			{/each}
		</div>
		<div class="b-sw" role="group" aria-label="Період">
			{#each periodsMeta as p (p.key)}
				<button class:active={curPeriod === p.key}
					onclick={() => (period = p.key)}>{p.label}</button>
			{/each}
		</div>
		<div class="flex-sp"></div>
		{#if myPos != null}
			<span class="me-chip-sm" title="Моє місце">
				<Trophy size={13} /> #<AnimatedNumber value={myPos} duration={700} />
				{#if pts?.total != null}<span class="of">з <AnimatedNumber
						value={pts.total} duration={700} /></span>{/if}
			</span>
		{/if}
	</div>
</div>

{#if err && !data}
	<p class="err">⚠ {err}</p>
{:else if !data}
	<div class="skel"></div>
{:else if rows.length}
	<!-- стек: старий і новий список накладаються в одній клітинці — кросфейд без стрибка висоти -->
	<div class="b-stack">
		{#key curScope + '|' + curPeriod}
			<div class="b-list wide"
				in:slideX={{ distance: 14, duration: 240 }}
				use:stagger={{ selector: '.b-row', step: 24, max: 12, y: 6 }}>
				{#each rows as r, ri (r.id)}
					<div class="b-row" class:me={isMe(r)}
						class:gap-before={ri === 3 && showGap}>
						{#if r.position != null && r.position <= 3}
							<span class="bmedal m{r.position}">{r.position}</span>
						{:else if r.position == null}
							<span class="bseed">🌱</span>
						{:else}
							<span class="bnum mono">{r.position}</span>
						{/if}
						{#if r.photo}
							<img class="b-ava" src={r.photo} alt={r.fio} loading="lazy" />
						{:else}
							<span class="b-ava ini">{initials(r.fio)}</span>
						{/if}
						<b class="fio">{r.fio}</b>
						<span class="flex-sp"></span>
						<span class="award coins">
							<Coins size={12} /> <AnimatedNumber value={r.amount ?? 0}
								duration={700} format={(n) => n.toLocaleString('uk-UA')} /></span>
					</div>
				{/each}
			</div>
		{/key}
	</div>
{:else}
	<p class="text-faint empty">Таблиця порожня</p>
{/if}

<style>
	/* ── Піксель-у-піксель стилі віджета «Лідери» з +page (b-*) ── */
	.b-swrow {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
		margin-bottom: 10px;
	}

	.b-sw {
		display: inline-flex;
		gap: 2px;
		padding: 2px;
		border-radius: 999px;
		background: var(--surface-2);
	}

	.b-sw button {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		border: 0;
		background: transparent;
		color: var(--text-dim);
		font: inherit;
		font-size: 0.76rem;
		padding: 4px 11px;
		border-radius: 999px;
		cursor: pointer;
		white-space: nowrap;
	}

	.b-sw button.active {
		background: var(--accent);
		color: #fff;
		font-weight: 600;
	}

	.me-chip-sm {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 5px 10px;
		border: 1px solid rgba(255, 180, 84, 0.35);
		border-radius: 999px;
		background: rgba(255, 180, 84, 0.12);
		color: var(--amber);
		font-size: 0.8rem;
	}

	.me-chip-sm .of {
		color: var(--text-faint);
		font-size: 0.72rem;
	}

	.b-list {
		display: flex;
		flex-direction: column;
	}

	/* широка вкладка → дві колонки, як у віджеті на всю ширину */
	.b-list.wide {
		display: block;
		columns: 2;
		column-gap: 24px;
	}

	.b-list .b-row,
	.b-list .b-gap {
		break-inside: avoid;
	}

	.b-row {
		display: flex;
		align-items: center;
		gap: 9px;
		padding: 5.5px 8px;
		border-radius: 10px;
		min-width: 0;
	}

	.b-row.me {
		position: relative;
		background: var(--accent-soft);
	}

	/* моє місце: м'яка акцентна пульсація один раз (лише opacity) */
	.b-row.me::after {
		content: '';
		position: absolute;
		inset: 0;
		border-radius: inherit;
		pointer-events: none;
		box-shadow:
			0 0 0 1.5px color-mix(in srgb, var(--accent) 70%, transparent),
			0 0 20px var(--accent-soft);
		opacity: 0;
		animation: me-glow 1.5s var(--ease-out) 0.4s 1;
	}

	@keyframes me-glow {
		0%,
		100% {
			opacity: 0;
		}
		35% {
			opacity: 1;
		}
	}

	.b-stack {
		display: grid;
	}

	.b-stack > .b-list {
		grid-area: 1 / 1;
	}

	/* розрив позицій «⋯» (раніше окремий елемент; animate: вимагає єдиної дитини) */
	.b-row.gap-before {
		position: relative;
		margin-top: 16px;
	}

	.b-row.gap-before::before {
		content: '⋯';
		position: absolute;
		top: -15px;
		left: 0;
		right: 0;
		text-align: center;
		color: var(--text-faint);
		letter-spacing: 4px;
		line-height: 1.1;
		pointer-events: none;
	}

	.b-row.me .fio {
		color: var(--accent);
	}

	.b-row .fio {
		font-size: 0.87rem;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.bmedal {
		width: 21px;
		height: 21px;
		flex: 0 0 21px;
		display: grid;
		place-items: center;
		border-radius: 50%;
		font-size: 0.68rem;
		font-weight: 800;
		color: #241a00;
	}

	/* подіум: медалі «вистрибують» по черзі 1 → 2 → 3 */
	.bmedal {
		animation: medal-pop 440ms var(--ease-spring) backwards;
	}
	.bmedal.m1 {
		animation-delay: 160ms;
	}
	.bmedal.m2 {
		animation-delay: 220ms;
	}
	.bmedal.m3 {
		animation-delay: 280ms;
	}
	@keyframes medal-pop {
		from {
			transform: scale(0) rotate(-50deg);
			opacity: 0;
		}
		60% {
			opacity: 1;
		}
	}
	:global(html[data-anim='off']) .bmedal,
	:global(html[data-anim='off']) .b-row.me::after {
		animation: none;
	}

	.bmedal.m1 {
		background: #ffd35c;
	}

	.bmedal.m2 {
		background: #c9d4e4;
	}

	.bmedal.m3 {
		background: #e0985a;
	}

	.bnum {
		min-width: 21px;
		text-align: center;
		color: var(--text-faint);
		font-size: 0.8rem;
	}

	.bseed {
		width: 21px;
		text-align: center;
	}

	.b-gap {
		text-align: center;
		color: var(--text-faint);
		letter-spacing: 4px;
		padding: 0;
		line-height: 1.1;
	}

	.b-ava {
		width: 30px;
		height: 30px;
		flex: 0 0 30px;
		border-radius: 50%;
		object-fit: cover;
	}

	.b-ava.ini {
		display: grid;
		place-items: center;
		background: var(--accent-soft);
		color: var(--accent);
		font-size: 0.62rem;
		font-weight: 700;
	}

	.award.coins {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		color: var(--amber);
		font-size: 0.82rem;
		font-variant-numeric: tabular-nums;
	}

	.flex-sp {
		flex: 1;
	}

	.err {
		color: var(--danger);
		padding: 18px 4px;
	}

	.empty {
		padding: 24px 4px;
	}

	.skel {
		height: 220px;
		border-radius: var(--radius-md);
		background: var(--glass-bg);
		animation: pulse 1.4s ease-in-out infinite;
	}

	@keyframes pulse {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0.55;
		}
	}

	@media (max-width: 700px) {
		.b-list.wide {
			columns: 1;
		}
	}
</style>
