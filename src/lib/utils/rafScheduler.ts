// Each animation frame is a window — many voices calling at once,
// but only one will speak. The latest always wins.

type PendingMap = Map<string, () => void>;

const pending: PendingMap = new Map();
let frameId: number | ReturnType<typeof setTimeout> | null = null;

function flush() {
	frameId = null;
	const callbacks = [...pending.values()];
	pending.clear();
	for (const fn of callbacks) {
		fn();
	}
}

function requestFrame() {
	if (frameId !== null) return;
	if (typeof requestAnimationFrame !== 'undefined') {
		frameId = requestAnimationFrame(flush);
	} else {
		frameId = setTimeout(flush, 0);
	}
}

/**
 * Schedule `fn` to run on the next animation frame, keyed by `key`.
 * If called multiple times with the same `key` before the frame fires,
 * only the latest `fn` runs.
 */
export function scheduleRender(key: string, fn: () => void): void {
	pending.set(key, fn);
	requestFrame();
}

/**
 * Cancel pending callback(s). If `key` is provided, cancels only that key.
 * If omitted, cancels all pending callbacks and the scheduled frame.
 */
export function clearPending(key?: string): void {
	if (key !== undefined) {
		pending.delete(key);
	} else {
		pending.clear();
		if (frameId !== null) {
			if (typeof cancelAnimationFrame !== 'undefined') {
				cancelAnimationFrame(frameId as number);
			} else {
				clearTimeout(frameId as ReturnType<typeof setTimeout>);
			}
			frameId = null;
		}
	}
}

/**
 * Run all pending callbacks synchronously. Useful in tests to avoid
 * needing to mock requestAnimationFrame timers.
 */
export function flushNow(): void {
	if (frameId !== null) {
		if (typeof cancelAnimationFrame !== 'undefined') {
			cancelAnimationFrame(frameId as number);
		} else {
			clearTimeout(frameId as ReturnType<typeof setTimeout>);
		}
		frameId = null;
	}
	flush();
}
