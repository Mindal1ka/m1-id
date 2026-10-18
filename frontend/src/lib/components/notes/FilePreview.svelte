<script lang="ts">
	import LazyComponent from '$lib/components/app/LazyComponent.svelte';

	/** Перегляд файла: той самий переглядач, що й для вкладень домашки
	 *  (картинки, PDF, текст, docx, zip-галерея), підвантажується за потреби. */
	let {
		file,
		onclose
	}: {
		file: { url: string; name: string } | null;
		onclose: () => void;
	} = $props();
</script>

{#if file}
	<LazyComponent
		load={() => import('$lib/components/FileViewerModal.svelte')}
		props={{ open: true, url: file.url, name: file.name, onclose }}
	/>
{/if}
