<script lang="ts">
	import { Save, Users, Check } from '@lucide/svelte';
	import { api, type PluginOut, type PluginSettingsResp } from '$lib/api/client';
	import { friendlyError } from '$lib/errors';
	import { Button, Dialog, Field, Input, Select, SettingRow, Skeleton, Textarea } from '$lib/ui';

	let {
		plugin,
		onclose
	}: {
		plugin: PluginOut;
		onclose: () => void;
	} = $props();

	let open = $state(true);
	let resp = $state<PluginSettingsResp | null>(null);
	let values = $state<Record<string, unknown>>({});
	let accSeqs = $state<number[]>([]);
	let accounts = $state<{ account_seq: number; login?: string; label?: string; fio?: string }[]>([]);
	let err = $state('');
	let okMsg = $state('');
	let busy = $state(false);

	$effect(() => {
		void (async () => {
			try {
				const [r, tg] = await Promise.all([
					api.pluginSettings(plugin.id),
					api.tgStatus().catch(() => null)
				]);
				resp = r;
				values = { ...(r.values || {}) };
				accSeqs = [...(r.account_seqs || [])];
				accounts = (tg?.accounts ?? []) as typeof accounts;
				// дефолти зі schema для порожніх значень
				for (const s of r.schema ?? []) {
					if (values[s.key] === undefined && s.default !== undefined) {
						values[s.key] = s.default;
					}
				}
			} catch (e) {
				err = friendlyError(e);
			}
		})();
	});

	function toggleAcc(seq: number): void {
		if (accSeqs.includes(seq)) {
			accSeqs = accSeqs.filter((x) => x !== seq);
		} else {
			accSeqs = [...accSeqs, seq];
		}
	}

	async function save(): Promise<void> {
		busy = true;
		err = '';
		try {
			await api.pluginSaveSettings(plugin.id, values, accSeqs);
			okMsg = 'Збережено';
			setTimeout(() => (okMsg = ''), 2000);
		} catch (e) {
			err = friendlyError(e);
		} finally {
			busy = false;
		}
	}

	function fieldVal(key: string): string {
		const v = values[key];
		return v === undefined || v === null ? '' : String(v);
	}

	function setVal(key: string, raw: string, type: string): void {
		if (type === 'number') {
			const n = Number(raw);
			values[key] = raw === '' ? undefined : (Number.isFinite(n) ? n : raw);
		} else {
			values[key] = raw;
		}
	}

	/** Підказка під полем за типом (у схемі плагіна окремого опису немає). */
	function hintFor(type: string): string | undefined {
		if (type === 'number') return 'Введи число.';
		if (type === 'textarea') return 'Можна кілька рядків.';
		if (type === 'select') return 'Обери один з варіантів.';
		if (type === 'boolean') return undefined;
		return 'Текстове значення.';
	}
</script>

<Dialog bind:open title={plugin.name} size="md" {onclose}>
	<div class="form">
		{#if !resp && !err}
			<Skeleton lines={3} height={40} radius="var(--radius-md)" />
		{/if}
		{#if err && !resp}<p class="warnline" role="alert">{err}</p>{/if}

		{#if accounts.length > 0}
			<Field label="Акаунти" hint="Порожньо = усі акаунти.">
				{#snippet children()}
					<div class="accseg">
						{#each accounts as a (a.account_seq)}
							<button
								type="button"
								class:sel={accSeqs.includes(a.account_seq)}
								aria-pressed={accSeqs.includes(a.account_seq)}
								onclick={() => toggleAcc(a.account_seq)}
							>
								{#if accSeqs.includes(a.account_seq)}<Check size={12} aria-hidden="true" />{:else}<Users size={12} aria-hidden="true" />{/if}
								{a.login || a.fio || a.label || `Акаунт ${a.account_seq}`}
							</button>
						{/each}
					</div>
				{/snippet}
			</Field>
		{/if}

		{#if resp && !resp.schema?.length}
			<p class="note">У цього плагіна немає налаштувань.</p>
		{:else}
			{#each resp?.schema ?? [] as s (s.key)}
				{#if s.type === 'boolean'}
					<SettingRow
						title={s.label || s.key}
						checked={!!values[s.key]}
						onchange={(v) => (values[s.key] = v)}
					/>
				{:else}
					<Field label={s.label || s.key} hint={hintFor(s.type)}>
						{#snippet children({ id, describedBy })}
							{#if s.type === 'select'}
								<Select
									{id}
									aria-describedby={describedBy}
									value={fieldVal(s.key)}
									options={(s.options ?? []).map((o) => ({ value: o, label: o }))}
									onchange={(e) => setVal(s.key, (e.target as HTMLSelectElement).value, s.type)}
								/>
							{:else if s.type === 'textarea'}
								<Textarea
									{id}
									aria-describedby={describedBy}
									rows={3}
									value={fieldVal(s.key)}
									oninput={(e) => setVal(s.key, (e.target as HTMLTextAreaElement).value, s.type)}
								/>
							{:else}
								<Input
									{id}
									aria-describedby={describedBy}
									type={s.type === 'number' ? 'number' : 'text'}
									value={fieldVal(s.key)}
									oninput={(e) => setVal(s.key, (e.target as HTMLInputElement).value, s.type)}
								/>
							{/if}
						{/snippet}
					</Field>
				{/if}
			{/each}
		{/if}

		{#if okMsg}<p class="okline" role="status"><Check size={14} aria-hidden="true" /> {okMsg}</p>{/if}
		{#if err && resp}<p class="warnline" role="alert">{err}</p>{/if}
	</div>

	{#snippet footer()}
		<Button variant="ghost" onclick={() => { open = false; onclose(); }}>Скасувати</Button>
		<Button icon={Save} loading={busy} onclick={() => void save()}>
			{busy ? 'Зберігаю…' : 'Зберегти'}
		</Button>
	{/snippet}
</Dialog>

<style>
	.form {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}

	.accseg {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	.accseg button {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		min-height: var(--control-h-sm);
		padding: 0 var(--space-3);
		font: inherit;
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
		color: var(--color-text-muted);
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-full);
		cursor: pointer;
		transition:
			border-color var(--dur-fast) var(--ease-out),
			color var(--dur-fast) var(--ease-out),
			background var(--dur-fast) var(--ease-out);
	}

	.accseg button:focus-visible {
		outline: 2px solid var(--color-accent);
		outline-offset: 2px;
	}

	.accseg button.sel {
		color: var(--color-accent-text);
		border-color: var(--color-accent);
		background: var(--color-accent-soft);
	}

	.note {
		font-size: var(--text-md);
		color: var(--color-text-muted);
	}

	.okline,
	.warnline {
		display: flex;
		align-items: center;
		gap: var(--space-1);
		margin: 0;
		font-size: var(--text-sm);
	}

	.okline {
		color: var(--color-success);
	}

	.warnline {
		color: var(--color-danger);
	}
</style>
