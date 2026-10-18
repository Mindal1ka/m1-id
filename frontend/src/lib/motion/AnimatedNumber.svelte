<script lang="ts">
	/** Число, що «докручується» до нового значення (бали, монети, лічильники). */
	import { Tween } from 'svelte/motion';
	import { cubicOut } from 'svelte/easing';
	import { motionOK } from './index';
	import { replay } from './replay.svelte';

	interface Props {
		value: number;
		/** знаків після коми */
		decimals?: number;
		duration?: number;
		/** формат (напр. toLocaleString) — отримує вже округлене число */
		format?: (n: number) => string;
		class?: string;
	}

	let { value, decimals = 0, duration = 900, format, class: cls = '' }: Props = $props();

	const tween = new Tween(0, { duration: 0, easing: cubicOut });

	let seenTick = replay.tick;
	$effect(() => {
		const v = Number.isFinite(value) ? value : 0;
		// повторний показ збереженої вкладки: рахуємо з нуля, як при монтуванні
		if (replay.tick !== seenTick) {
			seenTick = replay.tick;
			void tween.set(0, { duration: 0 });
		}
		void tween.set(v, { duration: motionOK() ? duration : 0 });
	});

	const shown = $derived.by(() => {
		const n = Number(tween.current.toFixed(decimals));
		return format ? format(n) : n.toFixed(decimals);
	});
</script>

<span class="an {cls}">{shown}</span>

<style>
	.an {
		font-variant-numeric: tabular-nums;
	}
</style>
