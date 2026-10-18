<script lang="ts">
	// Головна ("/"): той самий лендінг, що й /landing, але для
	// авторизованих користувачів — з автологіном в останній акаунт.
	// Сама розмітка лендінгу живе в $lib/components/Landing.svelte
	// (одна копія на два маршрути).
	import Landing from '$lib/components/Landing.svelte';
	import { goto } from '$app/navigation';
	import { api } from '$lib/api/client';
	import { auth } from '$lib/stores/auth.svelte';

	$effect(() => {
		if (!auth.restored || !auth.isAuthed) return;
		void (async () => {
			const last = Number(localStorage.getItem('m1id.lastAccount')) || null;
			if (last) {
				goto(`/app?account=${last}`, { replaceState: true });
				return;
			}
			try {
				const list = await api.accountsList();
				if (list.length) goto(`/app?account=${list[0].id}`, { replaceState: true });
			} catch {
				/* бек недоступний — лишаємо лендінг */
			}
		})();
	});
</script>

<Landing />