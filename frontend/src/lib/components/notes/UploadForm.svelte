<script lang="ts">
	import { untrack } from 'svelte';
	import { CloudUpload, Package, X } from '@lucide/svelte';
	import { api, type FileItem } from '$lib/api/client';
	import { friendlyError } from '$lib/errors';
	import { badgeOf, fmtSize } from './fileUtils';
	import { filesStore } from './files.svelte';
	import { flip } from 'svelte/animate';
	import { blurFade, pressable, springIn, stagger } from '$lib/motion';

	/**
	 * Форма завантаження файлів. Один файл — як є; кілька — сервер пакує їх в
	 * один zip з одним токеном (так само, як у здачі домашки). Файл іде через
	 * наш бекенд на fs itstep від імені АКТИВНОГО акаунта MyStat.
	 */
	let {
		account,
		initial = [],
		onuploaded,
		oncancel
	}: {
		account: number;
		initial?: File[];
		onuploaded: (f: FileItem) => void;
		oncancel: () => void;
	} = $props();

	const MAX_FILE = 25 * 1024 * 1024;
	const MAX_TOTAL = 60 * 1024 * 1024;
	const MAX_COUNT = 50;

	// початкові файли (кинуті в редактор) читаємо один раз
	let picked = $state<File[]>(untrack(() => [...initial]));
	let name = $state('');
	let nameTouched = $state(false);
	let description = $state('');
	let busy = $state(false);
	let phase = $state<'idle' | 'up' | 'server'>('idle');
	let pct = $state(0);
	let err = $state('');
	let over = $state(false);
	let input = $state<HTMLInputElement | null>(null);

	$effect(() => {
		if (!nameTouched) name = picked.length === 1 ? picked[0].name : '';
	});

	const total = $derived(picked.reduce((s, f) => s + f.size, 0));

	function add(list: File[]): void {
		err = '';
		const next = [...picked];
		for (const f of list) {
			if (next.some((x) => x.name === f.name && x.size === f.size)) continue;
			next.push(f);
		}
		if (next.length > MAX_COUNT) {
			err = `Не більше ${MAX_COUNT} файлів за раз`;
			return;
		}
		const big = next.find((f) => f.size > MAX_FILE);
		if (big) {
			err = `«${big.name}» більший за 25 МБ`;
			return;
		}
		if (next.reduce((s, f) => s + f.size, 0) > MAX_TOTAL) {
			err = 'Разом не більше 60 МБ';
			return;
		}
		if (next.some((f) => f.size === 0)) {
			err = 'Порожні файли не завантажуються';
			return;
		}
		picked = next;
	}

	function onPick(e: Event): void {
		const t = e.currentTarget as HTMLInputElement;
		add(Array.from(t.files ?? []));
		t.value = '';
	}

	function onDrop(e: DragEvent): void {
		e.preventDefault();
		over = false;
		add(Array.from(e.dataTransfer?.files ?? []));
	}

	async function submit(): Promise<void> {
		if (busy || !picked.length) return;
		if (!account) {
			err = 'Спершу підключи акаунт MyStat — файли вантажаться через нього';
			return;
		}
		busy = true;
		err = '';
		phase = 'up';
		pct = 0;
		try {
			const f = await api.filesUpload(
				picked,
				{ name: name.trim(), description: description.trim() },
				account,
				(l, t) => {
					pct = t ? Math.round((l / t) * 100) : 0;
					if (pct >= 100) phase = 'server';
				}
			);
			filesStore.upsert(f);
			onuploaded(f);
		} catch (e) {
			err = friendlyError(e);
			phase = 'idle';
		} finally {
			busy = false;
		}
	}
</script>

<div class="uf">
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="drop"
		class:over
		ondragover={(e) => {
			e.preventDefault();
			over = true;
		}}
		ondragleave={() => (over = false)}
		ondrop={onDrop}
		onclick={() => input?.click()}
		role="button"
		tabindex="0"
		onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && input?.click()}
	>
		<CloudUpload size={30} />
		<b>Перетягни файли сюди</b>
		<span>або натисни, щоб вибрати · до 25 МБ кожен</span>
		<input bind:this={input} type="file" multiple hidden onchange={onPick} />
	</div>

	{#if picked.length}
		<ul class="list" use:stagger={{ step: 30, max: 10, y: 8 }}>
			{#each picked as f, i (f.name + f.size + i)}
				<li
					animate:flip={{ duration: 300 }}
					in:springIn={{ duration: 320, start: 0.94, y: 8 }}
					out:blurFade={{ duration: 160, amount: 0 }}
				>
					<span class="bx">{badgeOf({ orig_name: f.name, name: f.name, kind: 'file' })}</span>
					<span class="nm">{f.name}</span>
					<span class="sz">{fmtSize(f.size)}</span>
					<button
						class="rm"
						aria-label="Прибрати {f.name}"
						disabled={busy}
						onclick={() => (picked = picked.filter((_x, j) => j !== i))}><X size={14} /></button
					>
				</li>
			{/each}
		</ul>
		{#if picked.length > 1}
			<p class="zipnote" in:blurFade={{ duration: 300, amount: 5 }}>
				<Package size={15} />
				<span>
					Файлів кілька — вони будуть запаковані в один архів
					<b>{(name.trim() || 'files').replace(/\.zip$/i, '')}.zip</b> з одним токеном ({fmtSize(total)})
				</span>
			</p>
		{/if}
	{/if}

	<label class="fld">
		<span>Назва</span>
		<input
			bind:value={name}
			maxlength="200"
			placeholder={picked.length > 1 ? 'Назва архіву' : 'Як підписати файл'}
			oninput={() => (nameTouched = true)}
			disabled={busy}
		/>
	</label>
	<label class="fld">
		<span>Опис <i>(необов'язково)</i></span>
		<textarea bind:value={description} rows="2" maxlength="2000" placeholder="Про що цей файл" disabled={busy}
		></textarea>
	</label>

	{#if busy}
		<div
			class="prog"
			role="progressbar"
			aria-valuenow={pct}
			aria-valuemin="0"
			aria-valuemax="100"
			in:blurFade={{ duration: 240, amount: 3 }}
		>
			<div class="bar" style="transform:scaleX({(phase === 'server' ? 100 : pct) / 100})" class:pulse={phase === 'server'}></div>
		</div>
		<p class="ph" in:blurFade={{ duration: 240, amount: 3 }}>
			{phase === 'server' ? 'Передаємо на сервер IT Step…' : `Завантаження… ${pct}%`}
		</p>
	{/if}
	{#if err}<p class="err" role="alert">⚠ {err}</p>{/if}

	<div class="act">
		<button class="btn" onclick={oncancel} disabled={busy}>Скасувати</button>
		<button class="btn btn-primary" use:pressable onclick={submit} disabled={busy || !picked.length}>
			{busy ? 'Завантаження…' : picked.length > 1 ? `Завантажити (${picked.length})` : 'Завантажити'}
		</button>
	</div>
</div>

<style>
	.uf {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	.drop {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 4px;
		padding: 22px 14px;
		text-align: center;
		color: var(--text-faint);
		border: 2px dashed var(--glass-border);
		border-radius: var(--radius-md);
		cursor: pointer;
		position: relative;
		transition:
			border-color 0.18s ease,
			background 0.18s ease,
			color 0.18s ease,
			transform 0.42s var(--ease-spring, cubic-bezier(0.34, 1.56, 0.64, 1));
	}

	/* світіння рамки при dragover — лише opacity */
	.drop::after {
		content: '';
		position: absolute;
		inset: -2px;
		border-radius: inherit;
		pointer-events: none;
		box-shadow:
			0 0 0 1px var(--accent),
			0 0 26px var(--accent-soft);
		opacity: 0;
		transition: opacity 0.25s ease;
	}

	.drop.over {
		transform: scale(1.01);
	}

	.drop.over::after {
		opacity: 1;
	}

	.drop.over :global(svg) {
		animation: uf-bounce 0.9s var(--ease-spring, ease-in-out) infinite;
	}

	@keyframes uf-bounce {
		0%,
		100% {
			transform: translateY(0);
		}
		40% {
			transform: translateY(-6px);
		}
	}

	:global(html[data-anim='off']) .drop.over,
	:global(html[data-anim='off']) .drop.over :global(svg) {
		transform: none;
		animation: none;
	}

	.drop b {
		color: var(--text);
		font-size: 14px;
	}

	.drop span {
		font-size: 12.5px;
	}

	.drop:hover,
	.drop.over {
		color: var(--accent);
		border-color: var(--accent);
		background: var(--accent-soft);
	}

	.list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 6px;
		max-height: 170px;
		overflow-y: auto;
	}

	.list li {
		display: flex;
		align-items: center;
		gap: 9px;
		padding: 6px 8px;
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: 10px;
		font-size: 13.5px;
	}

	.bx {
		flex: none;
		min-width: 34px;
		padding: 2px 6px;
		font-size: 10px;
		font-weight: 700;
		text-align: center;
		color: #fff;
		background: var(--text-faint);
		border-radius: 999px;
	}

	.nm {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.sz {
		flex: none;
		font-size: 12px;
		color: var(--text-faint);
	}

	.rm {
		flex: none;
		display: inline-flex;
		padding: 4px;
		color: var(--text-faint);
		background: none;
		border: 0;
		border-radius: 6px;
		cursor: pointer;
	}

	.rm:hover {
		color: var(--danger);
	}

	.zipnote :global(svg) {
		flex: none;
		margin-top: 2px;
	}

	.zipnote {
		display: flex;
		align-items: flex-start;
		gap: 7px;
		margin: 0;
		padding: 9px 12px;
		font-size: 13px;
		color: var(--text-dim);
		background: var(--accent-soft);
		border-radius: 10px;
	}

	.fld {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.fld span {
		font-size: 11.5px;
		font-weight: 600;
		color: var(--text-faint);
	}

	.fld i {
		font-style: normal;
		font-weight: 400;
	}

	.fld input,
	.fld textarea {
		width: 100%;
		box-sizing: border-box;
		padding: 8px 11px;
		font: inherit;
		font-size: 14px;
		color: var(--text);
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-sm);
		outline: 0;
		resize: vertical;
	}

	.fld input:focus,
	.fld textarea:focus {
		border-color: var(--accent);
	}

	.prog {
		height: 6px;
		overflow: hidden;
		background: var(--glass-bg-hover);
		border-radius: 999px;
	}

	.bar {
		height: 100%;
		background: var(--accent);
		border-radius: 999px;
		transform-origin: left center;
		transition: transform 0.25s var(--ease-out, ease-out);
	}

	.bar.pulse {
		animation: uf-pulse 1.1s ease-in-out infinite;
	}

	@keyframes uf-pulse {
		50% {
			opacity: 0.45;
		}
	}

	.ph {
		margin: -4px 0 0;
		font-size: 12.5px;
		color: var(--text-dim);
	}

	.err {
		margin: 0;
		font-size: 13px;
		color: var(--danger);
	}

	.act {
		display: flex;
		justify-content: flex-end;
		gap: 10px;
	}
</style>
