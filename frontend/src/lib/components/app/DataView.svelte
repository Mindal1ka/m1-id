<script lang="ts">
	import type { SnapshotMeta } from '$lib/api/client';
	import { sectionLabel } from '$lib/sections';

	interface Props {
		snapshots: SnapshotMeta[];
		openSection: string | null;
		sectionPayload: unknown;
		onshow: (section: string) => void;
	}
	let { snapshots, openSection, sectionPayload, onshow }: Props = $props();
</script>

					<ul class="sections">
						{#each snapshots as s (s.section)}
							<li>
								<button
									class="glass row"
									class:open={openSection === s.section}
									onclick={() => onshow(s.section)}>
									<b>{sectionLabel(s.section)}</b>
									<span class="text-faint mono">
										{s.size_bytes} B · {s.fetched_at?.slice(11, 19) ?? ''}</span>
								</button>
								{#if openSection === s.section}
									<pre class="glass payload">{JSON.stringify(
											sectionPayload,
											null,
											2
										)}</pre>
								{/if}
							</li>
						{/each}
					</ul>

<style>

	/* База — нейтральна; колір задає mkCls (hi/mid/low), як у віджетах */

	.mono {
		font-family: ui-monospace, Consolas, monospace;
		font-size: 11.5px;
	}

	/* ── захист плиток від «мімо-кліків» під час скрола ──
	   1) cooldown: 160мс після останньої scroll-події клік/hover
	      по картках не проходить (pointer-events: none);
	   2) tapGuard (use: на .grid) гасить кліки зі зсувом >8px
	      від точки натискання;
	   3) touch-action: pan-y — вертикальний жест завжди віддається
	      скролу; драг/резайз у режимі редагування живуть на грипі
	      та ресайзерах із touch-action: none. */

	.sections {
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: 10px;
		max-width: 980px;
	}

	.row {
		width: 100%;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
		padding: 13px 16px;
		border-radius: var(--radius-md);
		cursor: pointer;
		text-align: left;
		font: inherit;
		color: var(--text);
	}

	.row.open {
		outline: 1.5px solid var(--accent);
	}

	.payload {
		margin-top: -4px;
		padding: 14px;
		max-height: 340px;
		overflow: auto;
		font-family: ui-monospace, Consolas, monospace;
		font-size: 12px;
		color: var(--cyan);
		white-space: pre-wrap;
		word-break: break-word;
	}

</style>
