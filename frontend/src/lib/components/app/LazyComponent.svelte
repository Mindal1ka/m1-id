<script lang="ts">
	import type { Component } from 'svelte';

	/**
	 * Ліниве підвантаження важкого компонента окремим чанком.
	 *
	 * Мета — легший першопочатковий JS сторінки /app: вкладки, що відкриваються
	 * не одразу (магазин, харчування, плагіни…), і модалки не тягнуться
	 * разом із Головною. Сервіс-воркер у `install` обходить граф `import()`
	 * (див. static/sw.js), тож офлайн ці чанки теж доступні.
	 *
	 *  - now=true (за замовчуванням): вантажимо одразу при монтуванні;
	 *  - now=false: чанк підвантажується у простої браузера, а компонент
	 *    монтується одразу після завантаження (модалка з open=false). Щойно
	 *    `now` стає true (напр. відкриття модалки) — вантажимо негайно.
	 */
	interface Props {
		/** Динамічний імпорт компонента: () => import('…svelte'). */
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		load: () => Promise<{ default: Component<any> }>;
		/** Пропси цільового компонента (реактивні). */
		props?: Record<string, unknown>;
		now?: boolean;
	}
	let { load, props = {}, now = true }: Props = $props();

	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	let Comp = $state<Component<any> | null>(null);
	let failed = $state(false);
	let started = false;

	function start(): void {
		if (started) return;
		started = true;
		failed = false;
		load()
			.then((m) => (Comp = m.default))
			.catch((ex) => {
				console.warn('[lazy] не вдалося завантажити чанк:', ex);
				started = false;
				failed = true;
			});
	}

	$effect(() => {
		if (now) {
			start();
			return;
		}
		// простій браузера (Safari без requestIdleCallback → таймер)
		if (typeof requestIdleCallback === 'function') {
			const id = requestIdleCallback(() => start(), { timeout: 4000 });
			return () => cancelIdleCallback(id);
		}
		const t = setTimeout(start, 1500);
		return () => clearTimeout(t);
	});
</script>

{#if Comp}
	<Comp {...props} />
{:else if failed && now}
	<p class="lazy-fail text-faint">
		Не вдалося завантажити розділ.
		<button class="btn link" onclick={start}>Повторити</button>
	</p>
{/if}
