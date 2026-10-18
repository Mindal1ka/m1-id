/** Клас пристрою для хмарних розкладок віджетів.
 *
 *  Чому НЕ «який бар зараз намальований»: side/bottom бар — це *наслідок*
 *  CSS media query, а не ознака пристрою. Для вибору розкладки потрібен
 *  незалежний джерело правди: ширина viewport в CSS-пікселях
 *  (matchMedia враховує DPR/зум сам собою) + реактивні listener'и.
 *
 *  Класи:
 *   - phone:   ширина ≤ 600px (телефон; планшет у портреті з вузьким
 *              viewport теж потрапить сюди — і це коректно, бо сітка
 *              в нього тут дійсно «як у телефона»);
 *   - tablet:  601–1180px (планшет; при повороті клас може стрибнути
 *               phone⇄tablet — це ловиться реактивно і показує модалку);
 *   - desktop: > 1180px.
 */

export type DeviceClass = 'phone' | 'tablet' | 'desktop';

export const DEVICE_CLASSES: DeviceClass[] = ['phone', 'tablet', 'desktop'];

const MQ_DESKTOP = '(min-width: 1181px)';
const MQ_TABLET = '(min-width: 601px) and (max-width: 1180px)';

function compute(): DeviceClass {
	if (typeof window === 'undefined') return 'desktop';
	if (window.matchMedia(MQ_DESKTOP).matches) return 'desktop';
	if (window.matchMedia(MQ_TABLET).matches) return 'tablet';
	return 'phone';
}

class DeviceStore {
	/** Поточний клас — оновлюється в рантаймі без перезавантаження. */
	cls = $state<DeviceClass>(
		typeof window === 'undefined' ? 'desktop' : compute()
	);

	/** № запуску класу: зростає щоразу, коли клас змінюється. Перші
	 *  монтування дивляться на value, щоб не «спрацювати» на старті. */
	version = $state(0);

	private started = false;

	/** Слухачі matchMedia — викликати один раз із layout-компонента. */
	start(): void {
		if (this.started || typeof window === 'undefined') return;
		this.started = true;
		const onChange = (): void => {
			const next = compute();
			if (next !== this.cls) {
				this.cls = next;
				this.version += 1;
			}
		};
		// обидві media query: будь-який перехід між класами торкнеться
		// хоча б однієї (межі не перетинаються)
		window.matchMedia(MQ_DESKTOP).addEventListener('change', onChange);
		window.matchMedia(MQ_TABLET).addEventListener('change', onChange);
	}
}

export const device = new DeviceStore();