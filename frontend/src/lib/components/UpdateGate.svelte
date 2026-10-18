<script lang="ts">
	import { springIn, magnetic, pressable, blurFade } from '$lib/motion';
	import { Check, Loader2, Rocket } from '@lucide/svelte';
	import { PROJECT_NAME } from '$lib/config';
	import { purgeAllCaches } from '$lib/cachePurge';
	import { focusTrap, inertBackground } from '$lib/actions/focusTrap';

	let { version }: { version: string } = $props();

	/**
	 * Блокуюче оновлення: жодної «скасувати» — фон заблюрений й
	 * неклікабельний, єдиний шлях вперед — кнопка «Оновити».
	 * Очищаються ЛИШЕ service worker + кеші (щоб гарантовано
	 * завантажилась нова збірка), локальні дані користувача —
	 * акаунти, налаштування, віджети, тема — недоторкані.
	 */
	let phase = $state<'idle' | 'working' | 'done'>('idle');
	type Step = { label: string; st: 'wait' | 'run' | 'ok' };
	let steps = $state<Step[]>([
		{ label: 'Зупиняємо стару версію', st: 'wait' },
		{ label: 'Чистимо кеш', st: 'wait' },
		{ label: 'Завантажуємо оновлення', st: 'wait' }
	]);

	function step(i: number, st: Step['st']): void {
		steps[i] = { ...steps[i], st };
	}

	const sleep = (ms: number): Promise<void> =>
		new Promise((r) => window.setTimeout(r, ms));

	function bustedUrl(): string {
		// ?v= ламає будь-який HTTP-кеш index.html; нова вкладка прибере
		// цей параметр сама після завантаження
		const u = new URL(window.location.href);
		u.searchParams.set('v', version);
		return u.href;
	}

	async function apply(): Promise<void> {
		if (phase !== 'idle') return;
		phase = 'working';
		try {
			step(0, 'run');
			// повне чищення: SW + усі Cache Storage + localStorage-кеші за
			// префіксами (m1id.cache.*, меню їдальні fs_menu_*). Сесія, тема,
			// звуки та інші налаштування залишаються (див. purgeAllCaches).
			await purgeAllCaches();
			step(0, 'ok');
			await sleep(320);
			step(1, 'run');
			await sleep(500); // людський темп - видно процес
			step(1, 'ok');
			step(2, 'run');
			await sleep(500);
			step(2, 'ok');
			phase = 'done';
			await sleep(650);
		} catch {
			/* щось не вичистилося - все одно перезавантажуємось */
		}
		location.replace(bustedUrl());
	}
</script>

<div class="gate" role="alertdialog" aria-modal="true" aria-label="Доступне оновлення"
	use:focusTrap use:inertBackground>
	<div class="card" in:springIn={{ start: 0.92, duration: 460, y: 14 }}>
		<div class="badge"><Rocket size={22} strokeWidth={2.2} /></div>
		<h3>Вийшла нова версія</h3>
		<p class="sub">
			{PROJECT_NAME} щойно оновився. Оновіть сторінку, щоб
			продовжити — це займе кілька секунд.
		</p>

		{#if phase === 'idle'}
			<button class="cta" use:magnetic={{ strength: 0.22 }} use:pressable={{ scale: 0.97 }} onclick={apply}>
				<Rocket size={16} strokeWidth={2.2} />
				Оновити
			</button>
		{:else}
			<ul class="steps" in:blurFade={{ duration: 320, amount: 6, y: 6 }}>
				{#each steps as s, i (i)}
					<li class:ok={s.st === 'ok'} class:run={s.st === 'run'}>
						<span class="ico">
							{#if s.st === 'ok'}
								<Check size={12} strokeWidth={3} />
							{:else if s.st === 'run'}
								<Loader2 size={12} class="spin" />
							{:else}
								<span class="dot"></span>
							{/if}
						</span>
						<span class="lbl">{s.label}</span>
					</li>
				{/each}
			</ul>
		{/if}

		<p class="tiny">Акаунти, налаштування та ваші дані залишаться без змін</p>
	</div>
</div>

<style>
	.gate {
		position: fixed;
		inset: 0;
		z-index: 10000;
		display: grid;
		place-items: center;
		padding: 20px;
		background: rgba(5, 7, 12, 0.55);
		/* IMPORTANT: пара -webkit/стандарт обов'язкова (cssPrefixGuard) */
		-webkit-backdrop-filter: blur(16px) saturate(1.1);
		backdrop-filter: blur(16px) saturate(1.1);
		animation: gate-fade 0.2s ease both;
	}

	@keyframes gate-fade {
		from {
			opacity: 0;
		}
		to {
			opacity: 1;
		}
	}

	.card {
		width: min(400px, 100%);
		padding: 26px 24px 18px;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 10px;
		text-align: center;
		background: var(--surface-a94, rgba(18, 22, 31, 0.94));
		border: 1px solid var(--glass-border);
		border-radius: var(--radius-lg);
		box-shadow: 0 24px 70px rgba(0, 0, 0, 0.45);
	}

	.badge {
		width: 52px;
		height: 52px;
		border-radius: 16px;
		display: grid;
		place-items: center;
		color: #fff;
		background: linear-gradient(
			135deg,
			var(--accent),
			color-mix(in srgb, var(--accent) 50%, #8b5cf6)
		);
		box-shadow: 0 10px 26px color-mix(in srgb, var(--accent) 40%, transparent);
	}

	h3 {
		margin: 2px 0 0;
		font-family: var(--font-display);
		font-size: 17px;
		letter-spacing: 0.01em;
	}

	.sub {
		margin: 0;
		font-size: 13.5px;
		line-height: 1.5;
		color: var(--text-dim);
	}

	.cta {
		margin-top: 8px;
		width: 100%;
		height: 42px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
		font-size: 14px;
		font-weight: 700;
		color: #fff;
		background: linear-gradient(
			135deg,
			var(--accent),
			color-mix(in srgb, var(--accent) 60%, #8b5cf6)
		);
		border: none;
		border-radius: var(--radius-md);
		cursor: pointer;
		box-shadow: 0 10px 24px color-mix(in srgb, var(--accent) 35%, transparent);
		transition: transform 0.15s ease, box-shadow 0.15s ease;
	}

	.cta:hover {
		transform: translateY(-1px);
	}

	.cta:active {
		transform: translateY(0);
	}

	.steps {
		list-style: none;
		margin: 6px 0 0;
		padding: 0;
		width: 100%;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.steps li {
		display: flex;
		align-items: center;
		gap: 9px;
		font-size: 13px;
		color: var(--text-faint);
		text-align: left;
		transition: color 0.2s ease;
	}

	.steps li.run {
		color: var(--text);
	}

	.steps li.ok {
		color: var(--success);
	}

	.ico {
		flex: none;
		width: 20px;
		height: 20px;
		border-radius: 50%;
		display: grid;
		place-items: center;
		background: var(--glass-bg);
		border: 1px solid var(--glass-border);
		transition: background 0.2s ease, border-color 0.2s ease, color 0.2s ease;
	}

	.steps li.ok .ico {
		color: var(--success);
		background: color-mix(in srgb, var(--success) 16%, transparent);
		border-color: color-mix(in srgb, var(--success) 40%, transparent);
	}

	.dot {
		width: 5px;
		height: 5px;
		border-radius: 50%;
		background: currentColor;
		opacity: 0.55;
	}

	.tiny {
		margin: 8px 0 0;
		font-size: 11.5px;
		color: var(--text-faint);
	}

	/* class прилітає на внутрішній <svg> lucide-компонента → :global */
	.ico :global(.spin) {
		animation: gate-spin 0.9s linear infinite;
	}

	@keyframes gate-spin {
		to {
			transform: rotate(360deg);
		}
	}
</style>
