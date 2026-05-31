import { describe, expect, it, vi } from 'vitest';
import { resumeChatAfterCriticalLoad } from './chatNavigationResume';

function deferred<T = void>() {
	let resolve!: (value: T | PromiseLike<T>) => void;
	let reject!: (reason?: unknown) => void;
	const promise = new Promise<T>((res, rej) => {
		resolve = res;
		reject = rej;
	});
	return { promise, resolve, reject };
}

describe('resumeChatAfterCriticalLoad', () => {
	it('unblocks rendering and resumes an inflight persisted chat before deferred metadata finishes', async () => {
		const metadata = deferred<void>();
		const calls: string[] = [];

		const promise = resumeChatAfterCriticalLoad({
			chatId: 'chat-1',
			loadCriticalChat: vi.fn(async () => {
				calls.push('critical');
				return true;
			}),
			setLoading: vi.fn((loading) => calls.push(`loading:${loading}`)),
			afterCriticalRender: vi.fn(async () => {
				calls.push('rendered');
			}),
			resumeInflight: vi.fn((chatId) => calls.push(`resume:${chatId}`)),
			loadDeferredMetadata: vi.fn(async () => {
				calls.push('metadata:start');
				await metadata.promise;
				calls.push('metadata:done');
			})
		});

		await vi.waitFor(() => {
			expect(calls).toContain('metadata:start');
		});

		expect(calls).toEqual([
			'critical',
			'rendered',
			'loading:false',
			'resume:chat-1',
			'metadata:start'
		]);

		metadata.resolve();
		expect(await promise).toBe(true);
		expect(calls.at(-1)).toBe('metadata:done');
	});

	it('does not start inflight resume for local temporary chats', async () => {
		const resumeInflight = vi.fn();

		await resumeChatAfterCriticalLoad({
			chatId: 'local:chat-1',
			loadCriticalChat: vi.fn().mockResolvedValue(true),
			setLoading: vi.fn(),
			resumeInflight
		});

		expect(resumeInflight).not.toHaveBeenCalled();
	});

	it('returns false and keeps loading ownership with caller when critical chat load fails', async () => {
		const setLoading = vi.fn();
		const resumeInflight = vi.fn();
		const loadDeferredMetadata = vi.fn();

		const loaded = await resumeChatAfterCriticalLoad({
			chatId: 'chat-1',
			loadCriticalChat: vi.fn().mockResolvedValue(null),
			setLoading,
			resumeInflight,
			loadDeferredMetadata
		});

		expect(loaded).toBe(false);
		expect(setLoading).not.toHaveBeenCalled();
		expect(resumeInflight).not.toHaveBeenCalled();
		expect(loadDeferredMetadata).not.toHaveBeenCalled();
	});
});
