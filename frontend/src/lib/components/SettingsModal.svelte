<script lang="ts">
	import { Moon, Sun, Zap, Sparkles, Palette, Wand2, Code2, MousePointer2, Star } from '@lucide/svelte';
	import { Dialog, Button, Segmented, SettingRow, Divider } from '$lib/ui';
	import { theme, type ModeKey, type AnimKey } from '$lib/theme.svelte';
	import { fx, FX_EVENTS } from '$lib/fx.svelte';
	import { dev } from '$lib/devmode.svelte';
	import { stagger, motionOK, ease, applyPerf, getPerfMode, type PerfMode } from '$lib/motion';

	let { open = $bindable(false), onclose }: { open?: boolean; onclose?: () => void } = $props();

	const MODE_ICONS = { dark: Moon, light: Sun, neon: Zap } as const;

	const modeItems = $derived(
		theme.modes.map((m) => ({ value: m.key, label: m.name, icon: MODE_ICONS[m.key] }))
	);
	const animItems = $derived(theme.anims.map((a) => ({ value: a.key, label: a.name })));

	// продуктивність: режим зберігає сам applyPerf (localStorage)
	const perfItems = [
		{ value: 'auto', label: 'Авто' },
		{ value: 'full', label: 'Максимум' },
		{ value: 'lite', label: 'Економно' }
	];
	let perf = $state<PerfMode>(getPerfMode());

	const paletteItems = [
		{ value: 'accent', label: 'В акценті' },
		{ value: 'party', label: 'Святкові' }
	];

	// кільце виділення «перелітає» між свотчами пружиною
	let swWrap = $state<HTMLElement>();
	let ring = $state<HTMLElement>();
	let ringReady = false;

	function placeRing(): void {
		if (!swWrap || !ring) return;
		const sel = swWrap.querySelector<HTMLElement>('.swatch.sel');
		if (!sel) return;
		const x = sel.offsetLeft - 5;
		const y = sel.offsetTop - 5;
		if (!ringReady || !motionOK()) {
			ring.style.transition = 'none';
			ring.style.transform = `translate(${x}px, ${y}px)`;
			ring.style.setProperty('--sw', getComputedStyle(sel).getPropertyValue('--sw'));
			// форсуємо застосування стилю без переходу
			void ring.offsetWidth;
			ring.style.transition = '';
			ringReady = true;
			return;
		}
		ring.animate(
			[{ transform: ring.style.transform || 'none' }, { transform: `translate(${x}px, ${y}px)` }],
			{ duration: 520, easing: ease('spring') }
		);
		ring.style.transform = `translate(${x}px, ${y}px)`;
		ring.style.setProperty('--sw', getComputedStyle(sel).getPropertyValue('--sw'));
	}

	$effect(() => {
		void theme.accent;
		void swWrap;
		void ring;
		// чекаємо оновлення класу .sel
		queueMicrotask(placeRing);
	});

	/** Елемент-джерело для частинок: той, що зараз у фокусі. */
	function origin(): HTMLElement | null {
		return document.activeElement instanceof HTMLElement ? document.activeElement : null;
	}
</script>

<svelte:window onresize={placeRing} />

<Dialog bind:open {onclose} size="md" title="Налаштування" description="Вигляд, ефекти та режим розробника">
	<div class="body" use:stagger={{ selector: ':scope > section', step: 90, y: 14 }}>
		<!-- ===== ВИГЛЯД ===== -->
		<section>
			<h3><Palette size={16} /> Вигляд</h3>

			<div class="group">
				<span class="lbl">Тема</span>
				<Segmented
					block
					aria-label="Тема оформлення"
					items={modeItems}
					value={theme.mode}
					onchange={(v) => {
						theme.setMode(v as ModeKey);
						fx.celebrate('style', origin());
					}}
				/>
			</div>

			<div class="group">
				<span class="lbl">Акцент · <b>{theme.curAccent.name}</b></span>
				<div class="swatches" bind:this={swWrap}>
					<span class="ring" bind:this={ring} aria-hidden="true"></span>
					{#each theme.accents as t (t.key)}
						<button
							type="button"
							class="swatch"
							class:sel={theme.accent === t.key}
							style="--sw:{t.accent}"
							title={t.name}
							aria-label={'Акцент ' + t.name}
							aria-pressed={theme.accent === t.key}
							onclick={(e) => {
								theme.setAccent(t.key);
								fx.celebrate('style', e.currentTarget);
							}}
						></button>
					{/each}
				</div>
			</div>

			<div class="group">
				<span class="lbl">Анімація появи</span>
				<Segmented
					block
					aria-label="Анімація появи"
					items={animItems}
					value={theme.anim}
					onchange={(v) => theme.setAnim(v as AnimKey)}
				/>
				<p class="hint">Як картки й віджети з'являються при відкритті вкладки.</p>
			</div>

			<div class="group">
				<span class="lbl">Продуктивність</span>
				<Segmented
					block
					aria-label="Продуктивність"
					items={perfItems}
					value={perf}
					onchange={(v) => {
						perf = v as PerfMode;
						applyPerf(perf);
					}}
				/>
				<p class="hint">Економно — вимикає розмиття, скло й підсвічування, анімації лишаються.</p>
			</div>

			<div class="rows">
				<SettingRow
					icon={Sparkles}
					title="Фон «Північне сяйво»"
					description="Анімовані кольорові плями на фоні. Може навантажувати слабкі пристрої."
					checked={theme.aurora}
					onchange={(v) => theme.setAurora(v)}
				/>
				<SettingRow
					icon={MousePointer2}
					title="Підсвітка карток"
					description="Картки підсвічуються акцентом при наведенні."
					checked={theme.hoverGlow}
					onchange={(v) => theme.setHoverGlow(v)}
				/>
			</div>
		</section>

		<Divider />

		<!-- ===== ЕФЕКТИ ===== -->
		<section>
			<h3><Wand2 size={16} /> Ефекти</h3>

			<div class="rows">
				<SettingRow
					icon={Star}
					title="Святкові частинки"
					description="Зірочки, що вилітають, коли ти робиш щось важливе."
					checked={fx.enabled}
					onchange={(v) => fx.set({ enabled: v })}
				/>
			</div>

			{#if fx.enabled}
				<div class="group">
					<span class="lbl">Кількість частинок · <b>{fx.count}</b></span>
					<input
						class="rng"
						type="range"
						min="4"
						max="30"
						step="1"
						aria-label="Кількість частинок"
						value={fx.count}
						oninput={(e) => fx.set({ count: e.currentTarget.valueAsNumber })}
					/>
				</div>

				<div class="group">
					<span class="lbl">Кольори частинок</span>
					<Segmented
						block
						aria-label="Кольори частинок"
						items={paletteItems}
						value={fx.palette}
						onchange={(v) => fx.set({ palette: v as 'accent' | 'party' })}
					/>
				</div>

				<div class="group">
					<span class="lbl">Коли показувати</span>
					<div class="rows">
						{#each FX_EVENTS as ev (ev.key)}
							<SettingRow
								title={ev.name}
								description={ev.hint}
								checked={fx.events[ev.key]}
								onchange={(v) => fx.setEvent(ev.key, v)}
							/>
						{/each}
					</div>
				</div>

				<div>
					<Button variant="soft" icon={Sparkles} onclick={() => fx.celebrate('style', null, true)}>
						Перевірити
					</Button>
				</div>
			{/if}
		</section>

		<Divider />

		<!-- ===== ДЛЯ РОЗРОБНИКА ===== -->
		<section>
			<h3><Code2 size={16} /> Для розробника</h3>
			<div class="rows">
				<SettingRow
					icon={Code2}
					title="Режим розробника"
					description="Показує технічну вкладку «Дані» (знімки кешу з MyStat) і технічні дані в профілі."
					checked={dev.enabled}
					onchange={(v) => dev.set(v)}
				/>
			</div>
		</section>
	</div>
</Dialog>

<style>
	.body {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
	}

	section {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}

	h3 {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin: 0;
		font-size: var(--text-base);
		font-weight: var(--weight-semibold);
		color: var(--color-text);
	}

	.group {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.rows {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.lbl {
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}

	.lbl b {
		color: var(--color-text);
		font-weight: var(--weight-semibold);
	}

	.hint {
		margin: 0;
		font-size: var(--text-xs);
		color: var(--color-text-subtle);
	}

	/* --- акцентні кольори --- */
	.swatches {
		position: relative;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(36px, 1fr));
		gap: var(--space-2);
	}

	.swatch {
		width: 36px;
		height: 36px;
		padding: 0;
		border: 2px solid transparent;
		border-radius: var(--radius-full);
		background: var(--sw);
		cursor: pointer;
		outline: 2px solid transparent;
		outline-offset: 2px;
		transition:
			transform var(--dur-fast) var(--ease-out),
			outline-color var(--dur-fast) var(--ease-out);
	}

	.swatch:hover {
		transform: scale(1.08);
	}

	.swatch:focus-visible {
		outline-color: var(--color-text);
	}

	.swatch.sel {
		border-color: var(--color-surface);
	}

	/* єдине кільце, що їде до обраного свотча */
	.ring {
		position: absolute;
		left: 0;
		top: 0;
		width: 46px;
		height: 46px;
		border-radius: var(--radius-full);
		border: 2px solid var(--sw, var(--color-accent));
		pointer-events: none;
		transition: border-color var(--dur-slow) var(--ease-out);
	}

	/* --- слайдер --- */
	.rng {
		width: 100%;
		accent-color: var(--color-accent);
		cursor: pointer;
	}
</style>
