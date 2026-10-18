import { api, type FileItem } from '$lib/api/client';
import { auth } from '$lib/stores/auth.svelte';
import { friendlyError } from '$lib/errors';

/**
 * Спільний стор файлів користувача: вкладка «Файли», вибір файла в
 * нотатку й чипи `file:<token>` у тексті нотаток читають один список.
 * Файли належать користувачу M1 ID (не акаунту MyStat). При зміні
 * користувача стор скидається сам.
 */
class FilesStore {
	items = $state<FileItem[]>([]);
	loaded = $state(false);
	loading = $state(false);
	error = $state('');
	private owner: number | null = null;

	/** token → файл (лише власні: чужих у списку просто немає). */
	map = $derived(new Map(this.items.map((f) => [f.token, f])));

	private checkOwner(): void {
		const id = auth.user?.id ?? null;
		if (this.owner !== id) {
			this.owner = id;
			this.items = [];
			this.loaded = false;
			this.error = '';
		}
	}

	async load(force = false): Promise<void> {
		this.checkOwner();
		if (this.loading || (this.loaded && !force)) return;
		this.loading = true;
		try {
			this.items = (await api.filesList()).items;
			this.loaded = true;
			this.error = '';
		} catch (e) {
			this.error = friendlyError(e);
		} finally {
			this.loading = false;
		}
	}

	upsert(f: FileItem): void {
		const i = this.items.findIndex((x) => x.token === f.token);
		if (i >= 0) this.items[i] = f;
		else this.items.unshift(f);
	}

	remove(token: string): void {
		this.items = this.items.filter((f) => f.token !== token);
	}
}

export const filesStore = new FilesStore();
