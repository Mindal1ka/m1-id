<script lang="ts">
	/** Кастомний вибір зі списку (заміна «голого» <select>): кнопка-чип із іконкою,
	 *  випадаючий список з галочкою, пошуком (для довгих списків) і клавіатурою;
	 *  на телефоні відкривається нижнім аркушем. */
	import type { Component } from 'svelte';
	import { Check, ChevronDown, Search } from '@lucide/svelte';
	import Popover from './Popover.svelte';

	interface Option {
		value: string;
		label: string;
		/** Другий рядок дрібним шрифтом (необов'язково). */
		hint?: string;
		/** Коротший підпис для кнопки-чипа (напр. «Всі» замість «Всі предмети»). */
		short?: string;
	}

	interface Props {
		value: string;
		options: Option[];
		/** Назва поля: aria-label, заголовок аркуша й підпис над значенням. */
		label: string;
		icon?: Component<{ size?: number; strokeWidth?: number }>;
		/** Значення «за замовчуванням» (напр. 'all'): коли воно не вибране — чип підсвічується. */
		resetValue?: string;
		/** true / false; за замовчуванням — пошук з'являється від 8 пунктів. */
		searchable?: boolean;
		onchange?: (v: string) => void;
	}

	let {
		value = $bindable(),
		options,
		label,
		icon: Icon,
		resetValue,
		searchable,
		onchange
	}: Props = $props();

	let open = $state(false);
	let query = $state('');
	let active = $state(0);
	let listEl = $state<HTMLElement | null>(null);

	const current = $derived(options.find((o) => o.value === value));
	const showSearch = $derived(searchable ?? options.length > 7);
	const filtered = $derived.by(() => {
		const q = query.trim().toLowerCase();
		return q ? options.filter((o) => o.label.toLowerCase().includes(q)) : options;
	});
	const changed = $derived(resetValue !== undefined && value !== resetValue);

	// відкриття: скидаємо пошук, активний пункт = поточний
	$effect(() => {
		if (!open) return;
		query = '';
		const i = options.findIndex((o) => o.value === value);
		active = i < 0 ? 0 : i;
	});

	// активний пункт завжди видно
	$effect(() => {
		if (!open || !listEl) return;
		void active;
		listEl.querySelector<HTMLElement>('[data-active="true"]')?.scrollIntoView({ block: 'nearest' });
	});

	// пошук змінився → активним стає перший знайдений
	$effect(() => {
		void query;
		active = 0;
	});

	function pick(o: Option): void {
		value = o.value;
		open = false;
		onchange?.(o.value);
	}

	function onKey(e: KeyboardEvent): void {
		const n = filtered.length;
		if (!n) return;
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			active = (active + 1) % n;
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			active = (active - 1 + n) % n;
		} else if (e.key === 'Home') {
			e.preventDefault();
			active = 0;
		} else if (e.key === 'End') {
			e.preventDefault();
			active = n - 1;
		} else if (e.key === 'Enter') {
			e.preventDefault();
			const o = filtered[active];
			if (o) pick(o);
		}
	}

	/** Фокус у пошук — лише з мишею/клавіатурою: на дотику він викликав би клавіатуру. */
	function focusSearch(node: HTMLElement): void {
		if (window.matchMedia('(pointer: coarse)').matches) return;
		queueMicrotask(() => node.focus());
	}
</script>

<Popover bind:open placement="bottom-start" role="listbox" {label} sheetOnMobile offset={6}>
	{#snippet trigger({ toggle })}
		<button
			type="button"
			class="dd-btn"
			class:changed
			class:open
			aria-haspopup="listbox"
			aria-expanded={open}
			aria-label={label}
			onclick={toggle}
		>
			{#if Icon}<span class="dd-ico"><Icon size={16} strokeWidth={2.1} /></span>{/if}
			<span class="dd-txt">
				<span class="dd-lab">{label}</span>
				<span class="dd-val">{current ? (current.short ?? current.label) : '—'}{#if current?.hint}<span class="dd-val-hint">· {current.hint}</span>{/if}</span>
			</span>
			<span class="dd-chev" aria-hidden="true"><ChevronDown size={16} /></span>
		</button>
	{/snippet}

	<div class="dd" role="presentation" onkeydown={onKey}>
		{#if showSearch}
			<label class="dd-search">
				<Search size={15} />
				<input
					type="text"
					placeholder="Пошук…"
					autocomplete="off"
					bind:value={query}
					use:focusSearch
				/>
			</label>
		{/if}
		<ul class="dd-list" bind:this={listEl} role="presentation">
			{#each filtered as o, i (o.value)}
				<li role="presentation">
					<button
						type="button"
						role="option"
						class="dd-opt"
						class:sel={o.value === value}
						data-active={i === active}
						aria-selected={o.value === value}
						onclick={() => pick(o)}
						onpointermove={() => (active = i)}
					>
						<span class="dd-o-txt">
							<span class="dd-o-lab">{o.label}</span>
							{#if o.hint}<span class="dd-o-hint">{o.hint}</span>{/if}
						</span>
						{#if o.value === value}<Check size={16} strokeWidth={2.4} />{/if}
					</button>
				</li>
			{:else}
				<li class="dd-empty" role="presentation">Нічого не знайдено</li>
			{/each}
		</ul>
	</div>
</Popover>

<style>
	/* ---------- кнопка-чип ---------- */
	.dd-btn {
		display: inline-flex;
		align-items: center;
		gap: 10px;
		min-width: 0;
		max-width: 100%;
		height: 46px;
		padding: 0 12px 0 12px;
		font: inherit;
		text-align: left;
		color: var(--color-text);
		background: var(--color-surface-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		cursor: pointer;
		-webkit-tap-highlight-color: transparent;
		touch-action: manipulation;
		transition:
			border-color var(--dur-fast) ease,
			background var(--dur-fast) ease,
			box-shadow var(--dur-fast) ease;
	}
	.dd-btn:hover {
		border-color: var(--color-border-strong);
	}
	.dd-btn:focus-visible {
		outline: 2px solid var(--color-accent);
		outline-offset: 2px;
	}
	.dd-btn.open,
	.dd-btn.changed {
		border-color: color-mix(in srgb, var(--color-accent) 55%, transparent);
		background: color-mix(in srgb, var(--color-accent) 9%, var(--color-surface-2));
	}
	.dd-btn.open {
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-accent) 18%, transparent);
	}
	.dd-ico {
		display: inline-grid;
		place-items: center;
		flex-shrink: 0;
		width: 28px;
		height: 28px;
		border-radius: var(--radius-sm);
		color: var(--color-accent-text);
		background: var(--color-accent-soft);
	}
	.dd-txt {
		display: flex;
		flex-direction: column;
		min-width: 0;
		line-height: 1.15;
	}
	.dd-lab {
		font-size: 10.5px;
		letter-spacing: 0.02em;
		text-transform: uppercase;
		color: var(--color-text-subtle);
	}
	.dd-val {
		font-size: 13.5px;
		font-weight: var(--weight-medium, 500);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 190px;
	}
	.dd-val-hint {
		margin-left: 6px;
		font-weight: 400;
		color: var(--color-text-muted);
	}
	.dd-btn.changed .dd-val {
		color: var(--color-accent-text);
	}
	.dd-chev {
		display: inline-flex;
		flex-shrink: 0;
		margin-left: auto;
		color: var(--color-text-muted);
		transition: transform var(--dur-base) ease;
	}
	.dd-btn.open .dd-chev {
		transform: rotate(180deg);
	}

	/* ---------- панель ---------- */
	.dd {
		display: flex;
		flex-direction: column;
		min-width: 220px;
		max-width: min(360px, calc(100vw - 24px));
		padding: 6px;
	}
	.dd-search {
		display: flex;
		align-items: center;
		gap: 8px;
		margin: 2px 2px 6px;
		padding: 0 10px;
		height: 38px;
		color: var(--color-text-muted);
		background: var(--color-surface-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
	}
	.dd-search:focus-within {
		border-color: var(--color-accent);
	}
	.dd-search input {
		flex: 1;
		min-width: 0;
		font: inherit;
		font-size: 14px;
		color: var(--color-text);
		background: none;
		border: none;
		outline: none;
	}
	.dd-list {
		list-style: none;
		margin: 0;
		padding: 0;
		max-height: min(320px, 52dvh);
		overflow-y: auto;
		overscroll-behavior: contain;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.dd-opt {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		width: 100%;
		min-height: 42px;
		padding: 8px 12px;
		font: inherit;
		font-size: 14px;
		text-align: left;
		color: var(--color-text);
		background: none;
		border: none;
		border-radius: var(--radius-md);
		cursor: pointer;
		-webkit-tap-highlight-color: transparent;
	}
	.dd-opt[data-active='true'] {
		background: var(--color-accent-soft);
	}
	.dd-opt.sel {
		color: var(--color-accent-text);
		font-weight: var(--weight-semibold, 600);
	}
	.dd-o-txt {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}
	.dd-o-lab {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.dd-o-hint {
		font-size: 12px;
		font-weight: 400;
		color: var(--color-text-muted);
	}
	.dd-empty {
		padding: 14px 12px;
		font-size: 13.5px;
		color: var(--color-text-muted);
		text-align: center;
	}

	@media (max-width: 640px) {
		/* у нижньому аркуші пункти зручніші для пальця */
		.dd {
			min-width: 0;
			max-width: none;
			width: 100%;
			padding: 2px 0 6px;
		}
		.dd-list {
			max-height: min(56dvh, 460px);
		}
		.dd-opt {
			min-height: 50px;
			font-size: 15.5px;
			padding: 10px 14px;
		}
	}
</style>
