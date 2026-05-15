import { describe, it, expect, vi, beforeEach } from 'vitest';
import { scheduleRender, clearPending, flushNow } from './rafScheduler';

// Reset module state between tests via clearPending + flushNow
beforeEach(() => {
	clearPending();
});

describe('scheduleRender + flushNow', () => {
	it('runs a scheduled callback on flushNow', () => {
		const fn = vi.fn();
		scheduleRender('a', fn);
		flushNow();
		expect(fn).toHaveBeenCalledOnce();
	});

	it('only runs the latest fn for a given key within the same frame', () => {
		const fn1 = vi.fn();
		const fn2 = vi.fn();
		const fn3 = vi.fn();
		scheduleRender('a', fn1);
		scheduleRender('a', fn2);
		scheduleRender('a', fn3);
		flushNow();
		expect(fn1).not.toHaveBeenCalled();
		expect(fn2).not.toHaveBeenCalled();
		expect(fn3).toHaveBeenCalledOnce();
	});

	it('runs callbacks for different keys independently', () => {
		const fnA = vi.fn();
		const fnB = vi.fn();
		scheduleRender('a', fnA);
		scheduleRender('b', fnB);
		flushNow();
		expect(fnA).toHaveBeenCalledOnce();
		expect(fnB).toHaveBeenCalledOnce();
	});

	it('does not run any callback when there is nothing pending', () => {
		// Should not throw; noop
		expect(() => flushNow()).not.toThrow();
	});

	it('runs callbacks in independent frames after flushing', () => {
		const fn1 = vi.fn();
		const fn2 = vi.fn();
		scheduleRender('a', fn1);
		flushNow();
		scheduleRender('a', fn2);
		flushNow();
		expect(fn1).toHaveBeenCalledOnce();
		expect(fn2).toHaveBeenCalledOnce();
	});

	it('clears all pending state after flush so next scheduleRender starts fresh', () => {
		const fn = vi.fn();
		scheduleRender('a', fn);
		flushNow();
		// After flush, pending map is empty — a second flushNow must not re-run fn
		flushNow();
		expect(fn).toHaveBeenCalledTimes(1);
	});
});

describe('clearPending', () => {
	it('cancels a specific key so its fn never runs', () => {
		const fn = vi.fn();
		scheduleRender('a', fn);
		clearPending('a');
		flushNow();
		expect(fn).not.toHaveBeenCalled();
	});

	it('does not cancel other keys when a specific key is cleared', () => {
		const fnA = vi.fn();
		const fnB = vi.fn();
		scheduleRender('a', fnA);
		scheduleRender('b', fnB);
		clearPending('a');
		flushNow();
		expect(fnA).not.toHaveBeenCalled();
		expect(fnB).toHaveBeenCalledOnce();
	});

	it('cancels all pending callbacks when called with no key', () => {
		const fnA = vi.fn();
		const fnB = vi.fn();
		scheduleRender('a', fnA);
		scheduleRender('b', fnB);
		clearPending();
		flushNow();
		expect(fnA).not.toHaveBeenCalled();
		expect(fnB).not.toHaveBeenCalled();
	});

	it('is safe to call clearPending for a key that was never scheduled', () => {
		expect(() => clearPending('nonexistent')).not.toThrow();
	});

	it('is safe to call clearPending() with no args when nothing is pending', () => {
		expect(() => clearPending()).not.toThrow();
	});
});

describe('overwrite semantics with mixed keys', () => {
	it('overwrites only the matching key, leaving others intact', () => {
		const fnA1 = vi.fn();
		const fnA2 = vi.fn();
		const fnB = vi.fn();
		scheduleRender('a', fnA1);
		scheduleRender('b', fnB);
		scheduleRender('a', fnA2); // overwrite 'a'
		flushNow();
		expect(fnA1).not.toHaveBeenCalled();
		expect(fnA2).toHaveBeenCalledOnce();
		expect(fnB).toHaveBeenCalledOnce();
	});
});
