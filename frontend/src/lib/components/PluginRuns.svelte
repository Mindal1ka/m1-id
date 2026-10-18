<script lang="ts">
	import { RefreshCw, Terminal, Check, X } from '@lucide/svelte';
	import { api, type PluginOut, type PluginRunRow } from '$lib/api/client';
	import { friendlyError } from '$lib/errors';
	import { Button, Dialog, EmptyState, ErrorState, Skeleton } from '$lib/ui';

	let {
		plugin,
		onclose
	}: {
		plugin: PluginOut;
		onclose: () => void;
	} = $props();

	let open = $state(true);
	let rows = $state<PluginRunRow[]>([]);
	let err = $state('');
	let busy = $state(false);

	async function load(): Promise<void> {
		busy = true;
		err = '';
		try {
			rows = (await api.pluginRuns(plugin.id)) ?? [];
		} catch (e) {
			err = friendlyError(e);
		} finally {
			busy = false;
		}
	}

	$effect(() => {
		void load();
	});

	function label(trigger: string): string {
		const map: Record<string, string> = {
			tg_command: 'TG-команда',
			on_event: 'Подія',
			ui: 'Вкладка',
			on_daily: 'Щодня',
			button: 'TG-кнопка',
			test: 'Тест'
		};
		return map[trigger] ?? trigger;
	}

	function fmtAt(at: string): string {
		const d = new Date(at);
		return Number.isNaN(d.getTime()) ? at : d.toLocaleString('uk-UA');
	}
</script>

<Dialog bind:open title={`Логи: ${plugin.name}`} size="md" {onclose}>
	{#if err}
		<ErrorState title="Не вдалося завантажити логи" description={err} onretry={() => void load()} />
	{:else if busy && !rows.length}
		<Skeleton lines={4} height={44} radius="var(--radius-md)" />
	{:else if !rows.length}
		<EmptyState
			icon={Terminal}
			title="Ще немає запусків"
			description="Відкрий вкладку плагіна або виклич його команду в Telegram."
		/>
	{:else}
		<div class="rows">
			{#each rows as r, idx (idx)}
				<div class="row">
					<span class="st" class:ok={r.ok} role="img" aria-label={r.ok ? 'Успіх' : 'Помилка'}>
						{#if r.ok}<Check size={16} />{:else}<X size={16} />{/if}
					</span>
					<div class="mid">
						<span class="trg">{label(r.trigger)}{r.detail ? ` · ${r.detail}` : ''}</span>
						{#if r.error}
							<span class="err-txt">{r.error}</span>
						{/if}
					</div>
					<span class="meta">{r.ms} мс · {fmtAt(r.at)}</span>
				</div>
			{/each}
		</div>
	{/if}

	{#snippet footer()}
		<Button variant="secondary" icon={RefreshCw} loading={busy} onclick={() => void load()}>
			Оновити
		</Button>
	{/snippet}
</Dialog>

<style>
	.rows {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.row {
		display: flex;
		align-items: baseline;
		gap: var(--space-3);
		padding: var(--space-2) var(--space-3);
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
	}

	.st {
		display: inline-flex;
		flex: none;
		align-self: center;
		color: var(--color-danger);
	}

	.st.ok {
		color: var(--color-success);
	}

	.mid {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}

	.trg {
		font-size: var(--text-sm);
		font-weight: var(--weight-semibold);
	}

	.err-txt {
		font-size: var(--text-xs);
		color: var(--color-danger);
		overflow-wrap: anywhere;
	}

	.meta {
		flex: none;
		font-size: var(--text-xs);
		color: var(--color-text-subtle);
	}

	@media (max-width: 640px) {
		.row {
			flex-wrap: wrap;
		}

		.meta {
			flex-basis: 100%;
		}
	}
</style>
