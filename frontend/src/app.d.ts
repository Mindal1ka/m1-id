// See https://svelte.dev/docs/kit/types#app.d.ts
// for information about these interfaces
declare global {
	namespace App {
		// interface Error {}
		// interface Locals {}
		// interface PageData {}
		// interface PageState {}
		// interface Platform {}
	}
	// Штамп збірки (define у vite.config.ts): рандомні числа на кожен
	// білд. Вшитий у бандл → клієнт сам знає свою версію.
	var __BUILD_STAMP__: string;
}

export {};
