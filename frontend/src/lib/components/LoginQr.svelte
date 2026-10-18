<script lang="ts">
	import { onMount } from 'svelte';
	import { Copy, Check } from '@lucide/svelte';
	import { api } from '$lib/api/client';
	import { auth } from '$lib/stores/auth.svelte';
	import { springIn, blurFade } from '$lib/motion';

	let { onlogin }: { onlogin: () => void } = $props();

	let qr = $state<{ token: string; secret: string; url: string; qr: string; code: string } | null>(
		null
	);
	let failed = $state(false);
	let copied = $state(false);
	let msg = $state('');
	let approved = $state(false);
	let ttl = $state(0);

	let timer: ReturnType<typeof setTimeout> | undefined;
	let alive = true;
	let expiresAt = 0;

	async function start() {
		try {
			const r = await api.qrStart();
			qr = r;
			failed = false;
			expiresAt = Date.now() + r.expires_in * 1000;
			ttl = r.expires_in;
		} catch {
			qr = null;
			failed = true;
		}
		schedule();
	}

	async function tick() {
		if (!alive) return;
		if (!qr || Date.now() >= expiresAt - 1500) return start();
		try {
			const r = await api.qrPoll(qr.token, qr.secret);
			if (r.status === 'approved' && r.pair) {
				alive = false;
				auth.setSession(r.pair);
				approved = true;
				// даємо відіграти анімації галочки перед переходом
				setTimeout(onlogin, 750);
				return;
			}
			if (r.status === 'denied') {
				msg = 'Вхід відхилено на іншому пристрої.';
				return start();
			}
			if (r.status === 'expired' || r.status === 'consumed') return start();
		} catch {
			/* мережевий збій — спробуємо на наступному тіку */
		}
		schedule();
	}

	function schedule() {
		clearTimeout(timer);
		if (alive) timer = setTimeout(tick, failed ? 5000 : 2000);
	}

	async function copy() {
		if (!qr) return;
		try {
			await navigator.clipboard.writeText(qr.url);
		} catch {
			const ta = document.createElement('textarea');
			ta.value = qr.url;
			document.body.appendChild(ta);
			ta.select();
			document.execCommand('copy');
			ta.remove();
		}
		copied = true;
		setTimeout(() => (copied = false), 2000);
	}

	onMount(() => {
		start();
		return () => {
			alive = false;
			clearTimeout(timer);
		};
	});
</script>

<div class="qrbox">
	<p class="ttl">Вхід за QR-кодом</p>
	{#if qr}
		{#key qr.token}
			<div class="qrwrap" in:springIn={{ start: 0.86, duration: 460 }}>
				<img class="qr" src={qr.qr} alt="QR-код для входу" width="200" height="200" />
				<span class="scan" aria-hidden="true"></span>
				{#if approved}
					<div class="ok" aria-hidden="true">
						<svg viewBox="0 0 52 52" width="72" height="72">
							<circle class="ok-c" cx="26" cy="26" r="23" pathLength="1" />
							<path class="ok-p" d="M15 27 l8 8 l15 -17" pathLength="1" />
						</svg>
					</div>
				{/if}
			</div>
			{#if ttl > 0 && !approved}
				<svg class="ring" viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
					<circle class="ring-bg" cx="12" cy="12" r="9" />
					<circle class="ring-fg" cx="12" cy="12" r="9" pathLength="1" style="animation-duration:{ttl}s" />
				</svg>
			{/if}
			<p class="code">
				Код збігу:
				<b>{#each qr.code.split('') as ch, i (i)}<span class="dg" style="animation-delay:{260 + i * 80}ms">{ch}</span>{/each}</b>
			</p>
		{/key}
		<p class="hint text-dim">
			Скануйте з телефона, де ви вже увійшли, або надішліть фото чи посилання боту в Telegram.
		</p>
		<button type="button" class="btn copy" onclick={copy}>
			{#if copied}<Check size={16} /> Скопійовано{:else}<Copy size={16} /> Скопіювати{/if}
		</button>
	{:else if failed}
		<p class="hint text-dim">Не вдалося завантажити QR. Повторюємо…</p>
	{:else}
		<div class="qr ph"></div>
	{/if}
	{#if msg}<p class="hint warn" in:blurFade={{ y: 4 }}>{msg}</p>{/if}
</div>

<style>
	.qrbox {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 10px;
	}
	.ttl {
		font-weight: 700;
		font-size: 15px;
	}
	.qr {
		width: 200px;
		height: 200px;
		border-radius: 12px;
		background: #fff;
	}
	.ph {
		opacity: 0.15;
	}
	.qrwrap {
		position: relative;
		width: 200px;
		height: 200px;
		border-radius: 12px;
		overflow: hidden;
	}
	.scan {
		position: absolute;
		left: 0;
		right: 0;
		top: 0;
		height: 2px;
		pointer-events: none;
		background: linear-gradient(90deg, transparent, var(--color-accent, var(--accent)), transparent);
		box-shadow: 0 0 14px 2px color-mix(in srgb, var(--color-accent, var(--accent)) 60%, transparent);
		opacity: 0;
		animation: lq-scan 900ms var(--ease-in-out) 260ms 1 both;
	}
	@keyframes lq-scan {
		0% { opacity: 0; transform: translateY(0); }
		12% { opacity: 1; }
		88% { opacity: 1; }
		100% { opacity: 0; transform: translateY(198px); }
	}
	/* кільце відліку до завершення терміну дії */
	.ring {
		transform: rotate(-90deg);
		margin-bottom: -4px;
	}
	.ring circle {
		fill: none;
		stroke-width: 2.5;
		stroke-linecap: round;
	}
	.ring-bg {
		stroke: var(--color-border, rgba(128, 128, 128, 0.3));
	}
	.ring-fg {
		stroke: var(--color-accent, var(--accent));
		stroke-dasharray: 1;
		stroke-dashoffset: 0;
		animation: lq-ring linear 1 forwards;
	}
	@keyframes lq-ring {
		to { stroke-dashoffset: 1; }
	}
	/* цифри коду з'являються по черзі */
	.dg {
		display: inline-block;
		animation: lq-dg 480ms var(--ease-spring) both;
	}
	@keyframes lq-dg {
		from { opacity: 0; transform: translateY(8px) scale(0.5); }
	}
	/* успіх: коло + галочка */
	.ok {
		position: absolute;
		inset: 0;
		display: grid;
		place-items: center;
		background: color-mix(in srgb, #000 55%, transparent);
		backdrop-filter: blur(3px);
		animation: lq-fade 240ms var(--ease-out) both;
	}
	.ok svg {
		fill: none;
		stroke: #fff;
		stroke-width: 3;
		stroke-linecap: round;
		stroke-linejoin: round;
	}
	.ok-c,
	.ok-p {
		stroke-dasharray: 1;
		stroke-dashoffset: 1;
	}
	.ok-c {
		animation: lq-draw 420ms var(--ease-out) 60ms forwards;
	}
	.ok-p {
		animation: lq-draw 320ms var(--ease-out) 380ms forwards;
	}
	@keyframes lq-draw {
		to { stroke-dashoffset: 0; }
	}
	@keyframes lq-fade {
		from { opacity: 0; }
	}
	:global(html[data-anim='off']) :is(.scan, .ring-fg, .dg, .ok, .ok-c, .ok-p) {
		animation: none;
	}
	:global(html[data-anim='off']) :is(.ok-c, .ok-p) {
		stroke-dashoffset: 0;
	}
	.code {
		font-size: 14px;
	}
	.code b {
		font-size: 20px;
		letter-spacing: 2px;
		color: var(--accent);
	}
	.hint {
		font-size: 12.5px;
		text-align: center;
		max-width: 300px;
	}
	.warn {
		color: var(--danger);
	}
	.copy {
		display: inline-flex;
		gap: 6px;
		align-items: center;
		width: 100%;
		justify-content: center;
	}
</style>
