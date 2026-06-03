import { describe, expect, it } from 'vitest';
import { computeHermesOutputDone } from './hermesOutputDone';

describe('computeHermesOutputDone', () => {
	it('treats explicitly done messages as terminal', () => {
		expect(
			computeHermesOutputDone({
				message: { id: 'assistant-1', role: 'assistant', done: true },
				history: { currentId: 'assistant-1' }
			})
		).toBe(true);
	});

	it('keeps the current assistant message live when it is still not done', () => {
		expect(
			computeHermesOutputDone({
				message: { id: 'assistant-current', role: 'assistant', done: false },
				history: { currentId: 'assistant-current' }
			})
		).toBe(false);
	});

	it('treats non-current assistant messages as terminal even when persisted with done=false', () => {
		expect(
			computeHermesOutputDone({
				message: { id: 'assistant-stale', role: 'assistant', done: false },
				history: { currentId: 'assistant-current' }
			})
		).toBe(true);
	});

	it('forces terminal rendering when fade streaming is disabled', () => {
		expect(
			computeHermesOutputDone({
				message: { id: 'assistant-current', role: 'assistant', done: false },
				history: { currentId: 'assistant-current' },
				chatFadeStreamingText: false
			})
		).toBe(true);
	});
});
