<script lang="ts">
	import { Download, ShieldCheck } from '@lucide/svelte';
	import { Button, Dialog } from '$lib/ui';

	let {
		open = $bindable(false),
		onclose
	}: { open?: boolean; onclose?: () => void } = $props();
</script>

<Dialog bind:open title="Плагіни M1 ID" size="md" {onclose}>
	<div class="info">
		<p>
			Плагін — це маленьке розширення для M1 ID, яке виконується на сервері у повній ізоляції.
			Він не працює у фоні: прокидається <b>лише</b> на подію — Telegram-команда, нові дані з
			сайту (poller) або відкриття вкладки — відпрацьовує ≤ 2 секунди й одразу вимикається.
		</p>

		<ul class="list">
			<li><b>Пісочниця коду</b>: Python-код перевіряється аналізатором — жодних файлів, мережі, exec/eval, доступу до системи. Лише безпечні модулі (json, math, random, re, datetime…).</li>
			<li><b>Сліпий API</b>: твої ПІБ, пошта і телефон передаються плагіну у вигляді псевдонімів (#T1, #T2…). Імена в лідерборді — публічні.</li>
			<li><b>Telegram</b>: плагін може надсилати тобі повідомлення — максимум 60/год на всі плагіни разом, 30/год на один.</li>
			<li><b>Вкладки й віджети</b>: інтерфейс плагіна рендериться в ізольованому iframe (sandbox), без доступу до основного застосунку.</li>
			<li><span class="vok"><ShieldCheck size={14} aria-hidden="true" /></span> <b>Верифікація</b>: плагіни з позначкою перевірені автором M1 ID. Невірифіковані — встановлюй на свій ризик.</li>
			<li><b>Видимість</b>: публічний (усім), за посиланням (тільки у кого є лінк) або приватний (лише ти й адмін).</li>
		</ul>

		<p class="faint">Розробка: маніфест + plugin.py (хуки) + опційний index.html.</p>
	</div>

	{#snippet footer()}
		<Button
			variant="secondary"
			icon={Download}
			href="/plugins/DEV.md"
			{...{ download: 'm1-plugins-DEV.md' }}
		>
			DEV.md
		</Button>
	{/snippet}
</Dialog>

<style>
	.info {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	.list {
		margin: 0;
		padding-left: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		font-size: var(--text-md);
	}

	.vok {
		display: inline-flex;
		vertical-align: -2px;
		color: var(--color-success);
	}

	.faint {
		font-size: var(--text-sm);
		color: var(--color-text-subtle);
	}
</style>
