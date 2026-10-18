<script lang="ts">
	import { api } from '$lib/api/client';
	import { friendlyError } from '$lib/errors';
	import { Dialog, ErrorState, Skeleton } from '$lib/ui';
	import { springIn, blurFade } from '$lib/motion';

	let {
		open = $bindable(false),
		account_id,
		fio,
		onclose
	}: {
		open: boolean;
		account_id: number;
		fio?: string | null;
		onclose: () => void;
	} = $props();

	let data = $state('');
	let busy = $state(false);
	let err = $state('');

	async function load(): Promise<void> {
		if (busy) return;
		busy = true;
		err = '';
		try {
			data = (await api.qr(account_id)).qr;
		} catch (e) {
			err = friendlyError(e);
		} finally {
			busy = false;
		}
	}

	// при кожному відкритті — свіже завантаження (після помилки теж спрацює)
	let seenOpen = false;
	$effect(() => {
		if (open && !seenOpen) {
			seenOpen = true;
			void load();
		}
		if (!open) seenOpen = false;
	});
</script>

<Dialog bind:open title="QR Студента" size="sm" {onclose}>
	<div class="qr">
		{#if busy}
			<Skeleton width={220} height={220} radius="var(--radius-md)" />
		{:else if err}
			<ErrorState title="Не вдалося завантажити QR" description={err} onretry={() => void load()} />
		{:else if data}
			<div class="qr-wrap" in:springIn={{ start: 0.86, duration: 460 }}>
				<img class="qr-img" src={data} alt="QR-код студента" />
				<!-- одноразовий «скан»: тонка лінія проходить зверху вниз -->
				<span class="scan" aria-hidden="true"></span>
			</div>
			{#if fio}<p class="qr-fio" in:blurFade={{ delay: 220, y: 6 }}>{fio}</p>{/if}
		{/if}
	</div>
</Dialog>

<style>
	.qr {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-3);
	}

	.qr-wrap {
		position: relative;
		width: 220px;
		height: 220px;
		border-radius: var(--radius-md);
		overflow: hidden;
		box-shadow: 0 0 0 0 transparent;
		animation: qr-glow 900ms var(--ease-out) 200ms 1 both;
	}
	.scan {
		position: absolute;
		left: 0;
		right: 0;
		top: 0;
		height: 2px;
		pointer-events: none;
		background: linear-gradient(90deg, transparent, var(--color-accent), transparent);
		box-shadow: 0 0 14px 2px color-mix(in srgb, var(--color-accent) 60%, transparent);
		opacity: 0;
		animation: qr-scan 900ms var(--ease-in-out) 260ms 1 both;
	}
	@keyframes qr-scan {
		0% { opacity: 0; transform: translateY(0); }
		12% { opacity: 1; }
		88% { opacity: 1; }
		100% { opacity: 0; transform: translateY(218px); }
	}
	@keyframes qr-glow {
		0% { filter: drop-shadow(0 0 0 transparent); }
		40% { filter: drop-shadow(0 0 14px color-mix(in srgb, var(--color-accent) 45%, transparent)); }
		100% { filter: drop-shadow(0 0 0 transparent); }
	}
	:global(html[data-anim='off']) :is(.scan, .qr-wrap) {
		animation: none;
	}

	/* білий фон потрібен для надійного сканування QR у будь-якій темі */
	.qr-img {
		width: 220px;
		height: 220px;
		padding: var(--space-3);
		background: var(--color-text-on-accent);
		border-radius: var(--radius-md);
	}

	.qr-fio {
		font-size: var(--text-md);
		font-weight: var(--weight-semibold);
		text-align: center;
	}
</style>
