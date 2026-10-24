<script lang="ts">
	/**
	 * Вміст єдиного спливного вікна застосунку: урок (розклад / «Сьогодні»)
	 * та оцінка (вкладка Оцінки / віджет). Сама механіка — ui/HoverCard.
	 */
	import { MapPin } from '@lucide/svelte';
	import HoverCard from '$lib/ui/HoverCard.svelte';
	import { hoverCard, type HoverPayload } from '$lib/app/hovercards.svelte';
	import { markLabel, mkCls, wasLabel, cleanTeacher } from '$lib/app/helpers';
	import { initials } from '$lib/sections';

	interface Props {
		/** «Переглянути всі» → вкладка Домашка. */
		onall: () => void;
	}
	let { onall }: Props = $props();

	const MONTHS_GEN = [
		'січня', 'лютого', 'березня', 'квітня', 'травня', 'червня',
		'липня', 'серпня', 'вересня', 'жовтня', 'листопада', 'грудня'
	];

	/** «2026-05-16» → «16 травня 2026 р.». */
	function fmtDateUk(dateIso: string): string {
		const [y, mo, d] = String(dateIso).slice(0, 10).split('-').map(Number);
		if (!y || !mo || !d) return String(dateIso);
		return `${d} ${MONTHS_GEN[mo - 1]} ${y} р.`;
	}

	const roleOf = (d: HoverPayload): 'tooltip' | 'dialog' =>
		d.kind === 'lesson' && d.l.homeworks?.length ? 'dialog' : 'tooltip';
	const labelOf = (d: HoverPayload): string =>
		d.kind === 'lesson' ? d.l.subject : d.m.subject;
</script>

<HoverCard ctl={hoverCard} role={roleOf} label={labelOf}>
	{#snippet content(d: HoverPayload)}
		{#if d.kind === 'lesson'}
			{@const l = d.l}
			<div class="lc">
				<b class="lc-subj">{l.subject}</b>
				<div class="lc-meta">
					<span class="mono">{l.start} – {l.end}</span>
					<span class="lc-room"><MapPin size={13} /> {l.room}</span>
				</div>
				<div class="lc-att" class:no={!l.was}>
					{#if l.was}
						✓ {wasLabel(l)}
					{:else}
						✗ Не був
					{/if}
				</div>
				{#if l.theme}
					<div class="lc-theme">{l.theme}</div>
				{/if}
				{#if l.teacher}
					<div class="lc-teach text-dim">{cleanTeacher(l.teacher)}</div>
				{/if}
				{#if l.mark != null}
					<div class="lc-mark">
						<span class="mk2 {mkCls(l.mark)}" class:ex={!!l.exam}>{l.mark}</span>
						<span>{markLabel(l)}</span>
					</div>
				{:else if l.not_allowed}
					<div class="lc-mark">
						<span class="mk2 low">н/д</span>
						<span>Не допущено</span>
					</div>
				{/if}
				{#if l.homeworks?.length}
					<div class="lc-sect">Завдання до виконання</div>
					<div class="lc-hw">
						<span class="okv">✓</span>
						<span class="lc-hw-t">{l.theme || 'Домашнє завдання'}</span>
						<span class="arr">↗</span>
					</div>
					<button class="lc-all" type="button" onclick={onall}>Переглянути всі</button>
				{/if}
			</div>
		{:else}
			{@const m = d.m}
			<div class="mc">
				<div class="mc-top">
					<b class="mc-subj">{m.subject}</b>
					<span class="mk-chip {d.cls}">{m.mark}</span>
				</div>
				<span class="mc-date">{fmtDateUk(m.date)}</span>
				<div class="mc-theme">
					{#if m.theme}<b>{m.theme}</b>{/if}
					{#if m.teacher}
						<div class="mc-teach">
							{#if m.photo}
								<img src={m.photo} alt={cleanTeacher(m.teacher)} />
							{:else}
								<span class="mc-ava">{initials(cleanTeacher(m.teacher))}</span>
							{/if}
							<span>{cleanTeacher(m.teacher)}</span>
						</div>
					{/if}
				</div>
				<span class="mc-type {d.cls}">{d.label}</span>
			</div>
		{/if}
	{/snippet}
</HoverCard>

<style>
	.mono {
		font-family: ui-monospace, Consolas, monospace;
		font-size: 11.5px;
	}

	/* ── урок ── */
	.lc {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.lc-subj {
		font-size: 0.98rem;
		padding-right: 18px;
	}

	.lc-meta {
		display: flex;
		gap: 10px;
		align-items: center;
		font-size: 0.78rem;
		color: var(--text-dim);
		flex-wrap: wrap;
	}

	.lc-room {
		display: inline-flex;
		align-items: center;
		gap: 4px;
	}

	.lc-att {
		font-size: 0.78rem;
		color: var(--success);
	}

	.lc-att.no {
		color: var(--danger);
	}

	.lc-theme {
		font-size: 0.82rem;
		background: rgba(255, 255, 255, 0.05);
		border-radius: 8px;
		padding: 6px 9px;
		overflow-wrap: anywhere;
	}

	.lc-teach {
		font-size: 0.8rem;
	}

	.lc-mark {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 0.8rem;
		color: var(--text-dim);
	}

	.mk2 {
		min-width: 26px;
		height: 26px;
		padding: 0 6px;
		border-radius: 9px;
		display: grid;
		place-items: center;
		font-size: 0.85rem;
		font-weight: 800;
		color: #fff;
		box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
	}

	.mk2.hi {
		background: var(--success);
	}

	.mk2.mid {
		background: var(--amber);
	}

	.mk2.low {
		background: var(--danger);
	}

	.mk2.ex {
		box-shadow: 0 0 0 2px var(--amber), 0 2px 8px rgba(0, 0, 0, 0.35);
	}

	.lc-sect {
		font-size: 0.68rem;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--text-faint);
		margin-top: 2px;
	}

	.lc-hw {
		display: flex;
		align-items: center;
		gap: 7px;
		font-size: 0.8rem;
		background: rgba(255, 255, 255, 0.05);
		padding: 7px 9px;
		border-radius: 8px;
	}

	.okv {
		color: var(--success);
		font-weight: 800;
	}

	.lc-hw-t {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.arr {
		color: var(--text-faint);
	}

	.lc-all {
		align-self: flex-start;
		background: none;
		border: none;
		color: var(--accent);
		font-size: 0.78rem;
		cursor: pointer;
		padding: 2px 0;
	}

	/* ── оцінка ── */
	.mc-top {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
		padding-right: 18px;
	}

	.mc-subj {
		font-size: 0.95rem;
	}

	/* чип оцінки в шапці вікна (кольори .tw-* — глобальні з MarksChipsCard) */
	.mk-chip {
		min-width: 40px;
		height: 32px;
		padding: 0 10px;
		display: inline-grid;
		place-items: center;
		border: 1px solid transparent;
		border-radius: 10px;
		font-size: 0.95rem;
		font-weight: 700;
	}

	.mc-date {
		display: block;
		margin-top: 2px;
		font-size: 0.8rem;
		color: var(--text-faint);
	}

	.mc-theme {
		display: grid;
		gap: 6px;
		margin-top: 10px;
		font-size: 0.88rem;
	}

	.mc-teach {
		display: flex;
		align-items: center;
		gap: 8px;
		color: var(--text-dim);
		font-size: 0.85rem;
	}

	.mc-teach img {
		width: 22px;
		height: 22px;
		border-radius: 50%;
		object-fit: cover;
	}

	.mc-ava {
		width: 22px;
		height: 22px;
		display: grid;
		place-items: center;
		border-radius: 50%;
		background: var(--accent-soft);
		color: var(--accent);
		font-size: 0.58rem;
		font-weight: 700;
	}

	.mc-type {
		display: inline-block;
		margin-top: 10px;
		padding: 4px 10px;
		border-radius: 999px;
		font-size: 0.78rem;
		font-weight: 600;
	}
</style>
