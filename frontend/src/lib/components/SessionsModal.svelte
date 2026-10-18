<script lang="ts">
	import { api, type SessionInfo } from '$lib/api/client';
	import { auth } from '$lib/stores/auth.svelte';
	import { friendlyError } from '$lib/errors';
	import { Monitor, Smartphone, LogOut, Check, AlertTriangle } from '@lucide/svelte';
	import { Dialog, Button, Badge, Skeleton, confirm } from '$lib/ui';
	import { untrack } from 'svelte';
	import { flip } from 'svelte/animate';
	import { cubicOut } from 'svelte/easing';
	import { stagger, blurFade, motionOK, fx } from '$lib/motion';

	let { open = $bindable(false), onclose }: { open?: boolean; onclose: () => void } = $props();

	let sessions = $state<SessionInfo[]>([]);
	let loading = $state(false);
	let err = $state('');
	let busy = $state('');
	let msg = $state('');
	// лічильник запитів: відповідь застарілого запиту ігнорується
	let loadGen = 0;

	/** Exit animation of a session row: shrink + shift (blur only at the full level). */
	function sessOut(node: Element) {
		if (!motionOK()) return { duration: 0 };
		const blur = fx();
		return {
			duration: 320,
			easing: cubicOut,
			css: (t: number, u: number) =>
				`opacity:${t};transform:scale(${0.92 + 0.08 * t}) translateX(${u * 30}px)` +
				(blur ? `;filter:blur(${u * 4}px)` : '')
		};
	}

	async function load(silent = false): Promise<void> {
		const my = ++loadGen;
		if (!silent) loading = true;
		err = '';
		try {
			const list = await api.sessionsList(auth.refreshToken);
			if (my !== loadGen) return; // застаріла відповідь
			sessions = list;
		} catch (ex) {
			if (my !== loadGen) return;
			err = friendlyError(ex);
		} finally {
			if (my === loadGen) loading = false;
		}
	}

	// Завантажуємо список щоразу при відкритті.
	$effect(() => {
		if (open) {
			// untrack: залежність лише від `open`, а не від auth/loading тощо
			untrack(() => {
				msg = '';
				void load();
			});
		} else {
			loadGen++; // закриття скасовує очікувані відповіді
		}
	});

	async function kick(s: SessionInfo): Promise<void> {
		if (busy) return;
		const ok = await confirm({
			title: 'Завершити цей сеанс?',
			message: 'З цього пристрою тебе буде виведено — там доведеться увійти заново.',
			confirmText: 'Завершити',
			danger: true
		});
		if (!ok) return;
		busy = s.id;
		msg = '';
		try {
			await api.sessionRevoke(s.id);
			await load(true); // без скелетона — щоб відіграла анімація зникнення
			msg = 'Сеанс завершено';
		} catch (ex) {
			err = friendlyError(ex);
		} finally {
			busy = '';
		}
	}

	async function kickOthers(): Promise<void> {
		if (busy) return;
		const ok = await confirm({
			title: 'Завершити всі інші сеанси?',
			message: 'З усіх інших пристроїв тебе буде виведено — там доведеться увійти заново.',
			confirmText: 'Завершити всі інші',
			danger: true
		});
		if (!ok) return;
		busy = 'others';
		msg = '';
		try {
			const r = await api.sessionsRevokeOthers(auth.refreshToken);
			await load(true);
			msg = r.revoked > 0 ? `Завершено сеансів: ${r.revoked}` : 'Інших сеансів немає';
		} catch (ex) {
			err = friendlyError(ex);
		} finally {
			busy = '';
		}
	}

	/** Коротка людська назва пристрою/браузера з User-Agent. */
	function deviceLabel(ua: string): { name: string; mobile: boolean } {
		const s = ua || '';
		const os = /iphone|ipad/i.test(s) ? 'iOS'
			: /android/i.test(s) ? 'Android'
			: /windows/i.test(s) ? 'Windows'
			: /mac os|macintosh/i.test(s) ? 'macOS'
			: /linux/i.test(s) ? 'Linux' : 'Пристрій';
		const br = /edg\//i.test(s) ? 'Edge'
			: /opr\/|opera/i.test(s) ? 'Opera'
			: /firefox\//i.test(s) ? 'Firefox'
			: /chrome\//i.test(s) ? 'Chrome'
			: /safari\//i.test(s) ? 'Safari' : 'Браузер';
		return { name: `${os} · ${br}`, mobile: /iphone|ipad|android|mobile/i.test(s) };
	}

	function fmtDate(iso: string | null): string {
		if (!iso) return '—';
		const d = new Date(iso);
		if (isNaN(d.getTime())) return '—';
		return d.toLocaleString('uk-UA', {
			day: '2-digit', month: '2-digit', year: '2-digit',
			hour: '2-digit', minute: '2-digit'
		});
	}
</script>

<Dialog bind:open {onclose} size="md" title="Сеанси">
	<div class="body">
		<p class="lead">Пристрої, на яких ти ввійшов у M1 ID.</p>
		{#if msg}<p class="note ok" in:blurFade={{ y: 6 }}><Check size={16} /> {msg}</p>{/if}
		{#if err}<p class="note err" in:blurFade={{ y: 6 }}><AlertTriangle size={16} /> {err}</p>{/if}

		{#if loading}
			<div class="skel">
				<Skeleton height={56} />
				<Skeleton height={56} />
			</div>
		{:else}
			<ul class="sess-list" use:stagger={{ step: 40, y: 10, max: 8 }}>
				{#each sessions as s (s.id)}
					{@const d = deviceLabel(s.user_agent)}
					<li animate:flip={{ duration: 360, easing: cubicOut }} out:sessOut>
						<span class="sicon">
							{#if d.mobile}<Smartphone size={18} />{:else}<Monitor size={18} />{/if}
						</span>
						<span class="sess-info">
							<b>{d.name}{#if s.current}<Badge tone="success" size="sm">ти зараз тут</Badge>{/if}</b>
							<small>вхід {fmtDate(s.created_at)} · активність {fmtDate(s.last_seen_at)}</small>
						</span>
						{#if !s.current}
							<Button variant="secondary" size="sm" icon={LogOut}
								loading={busy === s.id}
								onclick={() => void kick(s)}>Завершити</Button>
						{/if}
					</li>
				{/each}
				{#if sessions.length === 0}<li class="empty">Немає активних сеансів</li>{/if}
			</ul>
		{/if}
	</div>

	{#snippet footer()}
		<div class="actions">
			{#if sessions.length > 1}
				<Button variant="danger" icon={LogOut} loading={busy === 'others'} onclick={kickOthers}>
					Завершити всі інші ({sessions.length - 1})
				</Button>
			{/if}
			<Button variant="ghost" onclick={onclose}>Закрити</Button>
		</div>
	{/snippet}
</Dialog>

<style>
	.body {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.lead {
		margin: 0;
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}
	.skel {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.note {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin: 0;
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-sm);
		font-size: var(--text-sm);
	}
	.note.ok {
		color: var(--color-success);
		background: var(--color-success-soft);
	}
	.note.err {
		color: var(--color-danger);
		background: var(--color-danger-soft);
	}
	.sess-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}
	.sess-list li {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-3);
		background: var(--color-surface-2);
		border-radius: var(--radius-md);
	}
	.sess-list li.empty {
		color: var(--color-text-subtle);
		font-size: var(--text-sm);
	}
	.sicon {
		display: grid;
		flex-shrink: 0;
		color: var(--color-text-subtle);
	}
	.sess-info {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.sess-info b {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-2);
		font-size: var(--text-sm);
		font-weight: var(--weight-semibold);
	}
	.sess-info small {
		font-size: var(--text-xs);
		color: var(--color-text-subtle);
	}
	.actions {
		display: flex;
		justify-content: flex-end;
		flex-wrap: wrap;
		gap: var(--space-2);
	}
	@media (max-width: 640px) {
		.sess-list li {
			flex-wrap: wrap;
		}
		.actions :global(button) {
			flex: 1;
		}
	}
</style>
