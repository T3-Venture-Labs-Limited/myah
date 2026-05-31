// Unit tests for the tryResumeInflight state machine.
//
// The function itself lives in Chat.svelte (a Svelte component) and cannot be
// imported directly. These tests mirror its logic via a thin, injectable
// re-implementation that accepts the same deps as constructor arguments.
// This gives us precise coverage of the timing paths, terminal states, and
// class-7 / class-9 mitigations without mounting a full Svelte component.
//
// If tryResumeInflight is ever extracted to a standalone module, these tests
// can be replaced with direct imports.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ── Injectable re-implementation ─────────────────────────────────────────────
// Mirrors the real tryResumeInflight in Chat.svelte.  Any change to the state
// machine must be reflected here (and the diff will make it obvious).

interface Deps {
	getActiveRun: (
		token: string,
		chatId: string
	) => Promise<{
		run_id: string | null;
		started_at: number | null;
		message_id: string | null;
	}>;
	getChatLiveState: (
		token: string,
		chatId: string,
		messageId: string
	) => Promise<Record<string, unknown> | null>;
	loadInflightSnapshot: (chatId: string) => Record<string, unknown> | null;
	applyInflightSnapshot: (snapshot: Record<string, unknown>) => void;
	loadChat: () => Promise<void>;
	clearInflightSnapshot: (chatId: string) => void;
	setBanner: (msg: string | null) => void;
	token: string;
	PAINT_THRESHOLD_MS?: number;
	HARD_TIMEOUT_MS?: number;
}

async function tryResumeInflight(chatId: string, deps: Deps): Promise<void> {
	const PAINT_THRESHOLD_MS = deps.PAINT_THRESHOLD_MS ?? 200;
	const HARD_TIMEOUT_MS = deps.HARD_TIMEOUT_MS ?? 30_000;
	let snapshotPainted = false;

	const serverPromise = (async () => {
		try {
			const active = await deps.getActiveRun(deps.token, chatId);
			if (typeof active?.run_id === 'undefined') {
				throw new Error('malformed active_run response');
			}
			if (active.run_id === null) {
				return null; // no active run — DB load wins
			}
			const live = active.message_id
				? await deps.getChatLiveState(deps.token, chatId, active.message_id)
				: null;
			return live ? { ...active, ...live } : null;
		} catch (err) {
			deps.setBanner('Reconnect failed — refresh to retry');
			throw err;
		}
	})();

	const paintTimer = setTimeout(() => {
		const stored = deps.loadInflightSnapshot(chatId);
		if (stored && stored.chat_id === chatId) {
			deps.applyInflightSnapshot(stored);
			deps.setBanner('Reconnecting...');
			snapshotPainted = true;
		}
	}, PAINT_THRESHOLD_MS);

	const hardTimeout = setTimeout(async () => {
		deps.setBanner('Reconnect timed out — falling back to saved state');
		await deps.loadChat();
		deps.setBanner(null);
	}, HARD_TIMEOUT_MS);

	try {
		const serverState = await serverPromise;
		clearTimeout(paintTimer);
		clearTimeout(hardTimeout);
		if (serverState) {
			deps.applyInflightSnapshot(serverState);
			deps.setBanner(null);
		} else if (snapshotPainted) {
			await deps.loadChat();
			deps.clearInflightSnapshot(chatId);
			deps.setBanner(null);
		} else {
			// No active run, no stale snapshot painted — navigateHandler already
			// loaded the DB state, so no second loadChat needed.
			deps.setBanner(null);
		}
	} catch {
		clearTimeout(paintTimer);
		clearTimeout(hardTimeout);
		// Banner already set to terminal state inside serverPromise catch.
	}
}

// ── Test helpers ──────────────────────────────────────────────────────────────

function makeDeps(overrides: Partial<Deps> = {}): Deps & {
	bannerHistory: (string | null)[];
	applyHistory: unknown[];
	loadChatCalls: number;
} {
	const bannerHistory: (string | null)[] = [];
	const applyHistory: unknown[] = [];
	let loadChatCalls = 0;

	return {
		getActiveRun: vi.fn().mockResolvedValue({ run_id: null, started_at: null, message_id: null }),
		getChatLiveState: vi.fn().mockResolvedValue(null),
		loadInflightSnapshot: vi.fn().mockReturnValue(null),
		applyInflightSnapshot: vi.fn((s) => applyHistory.push(s)),
		loadChat: vi.fn(async () => {
			loadChatCalls++;
		}),
		clearInflightSnapshot: vi.fn(),
		setBanner: (msg) => bannerHistory.push(msg),
		token: 'test-token',
		PAINT_THRESHOLD_MS: 200,
		HARD_TIMEOUT_MS: 30_000,
		bannerHistory,
		applyHistory,
		get loadChatCalls() {
			return loadChatCalls;
		},
		...overrides
	} as any;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('tryResumeInflight', () => {
	beforeEach(() => {
		vi.useFakeTimers();
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it('fast path (<200ms): server returns null → banner null, no loadChat', async () => {
		const deps = makeDeps({
			getActiveRun: vi.fn().mockResolvedValue({ run_id: null, started_at: null, message_id: null })
		});

		const p = tryResumeInflight('chat-1', deps);
		await vi.runAllTimersAsync();
		await p;

		// Banner must resolve to null (no active run)
		expect(deps.bannerHistory.at(-1)).toBeNull();
		// No stale snapshot was painted, so loadChat should NOT be called —
		// navigateHandler already loaded DB state before tryResumeInflight ran.
		expect(deps.loadChat).not.toHaveBeenCalled();
		// No snapshot applied
		expect(deps.applyHistory).toHaveLength(0);
	});

	it('fast path (<200ms): server returns live state → applies snapshot, no loadChat', async () => {
		const serverState = {
			run_id: 'run-1',
			message_id: 'msg-1',
			started_at: 1000,
			message_content: 'partial text',
			output: []
		};
		const deps = makeDeps({
			getActiveRun: vi
				.fn()
				.mockResolvedValue({ run_id: 'run-1', started_at: 1000, message_id: 'msg-1' }),
			getChatLiveState: vi.fn().mockResolvedValue(serverState)
		});

		const p = tryResumeInflight('chat-1', deps);
		await vi.runAllTimersAsync();
		await p;

		expect(deps.applyHistory).toHaveLength(1);
		expect((deps.applyHistory[0] as any).message_content).toBe('partial text');
		expect(deps.bannerHistory.at(-1)).toBeNull();
		expect(deps.loadChat).not.toHaveBeenCalled();
	});

	it('fast path (<200ms): active run without message_id returns null instead of failing live_state fetch', async () => {
		const deps = makeDeps({
			getActiveRun: vi.fn().mockResolvedValue({
				run_id: 'run-settling',
				started_at: 1000,
				message_id: null
			}),
			getChatLiveState: vi.fn()
		});

		const p = tryResumeInflight('chat-1', deps);
		await vi.runAllTimersAsync();
		await p;

		expect(deps.getChatLiveState).not.toHaveBeenCalled();
		expect(deps.bannerHistory.at(-1)).toBeNull();
		expect(deps.loadChat).not.toHaveBeenCalled();
	});

	it('slow path (>200ms): snapshot exists → paints stale + Reconnecting...', async () => {
		const stored = { chat_id: 'chat-1', message_id: 'msg-1', message_content: 'stale', output: [] };
		// Slow server — resolves after 500ms (beyond the 200ms paint threshold)
		const deps = makeDeps({
			getActiveRun: vi
				.fn()
				.mockImplementation(
					() =>
						new Promise((resolve) =>
							setTimeout(() => resolve({ run_id: null, started_at: null, message_id: null }), 500)
						)
				),
			loadInflightSnapshot: vi.fn().mockReturnValue(stored),
			PAINT_THRESHOLD_MS: 200
		});

		const p = tryResumeInflight('chat-1', deps);

		// Advance past paint threshold — stale snapshot should be painted
		await vi.advanceTimersByTimeAsync(201);
		expect(deps.bannerHistory).toContain('Reconnecting...');
		expect(deps.applyHistory).toHaveLength(1);
		expect((deps.applyHistory[0] as any).message_content).toBe('stale');

		// Advance past server response — stale snapshot replaced by fresh DB load
		await vi.advanceTimersByTimeAsync(400);
		await p;

		expect(deps.bannerHistory.at(-1)).toBeNull();
		expect(deps.loadChat).toHaveBeenCalledOnce();
		expect(deps.clearInflightSnapshot).toHaveBeenCalledWith('chat-1');
	});

	it('class-7: 5xx response → terminal banner, no retry, no loadChat', async () => {
		const deps = makeDeps({
			getActiveRun: vi.fn().mockRejectedValue(new Error('500 Internal Server Error'))
		});

		const p = tryResumeInflight('chat-1', deps);
		await vi.runAllTimersAsync();
		await p.catch(() => {});

		expect(deps.bannerHistory).toContain('Reconnect failed — refresh to retry');
		// Terminal — must not transition to any other state after the error
		expect(deps.bannerHistory.at(-1)).toBe('Reconnect failed — refresh to retry');
		// No DB load attempted
		expect(deps.loadChat).not.toHaveBeenCalled();
	});

	it('class-7: malformed response (run_id undefined) → terminal banner', async () => {
		const deps = makeDeps({
			// Response missing run_id entirely
			getActiveRun: vi.fn().mockResolvedValue({ started_at: null, message_id: null })
		});

		const p = tryResumeInflight('chat-1', deps);
		await vi.runAllTimersAsync();
		await p.catch(() => {});

		expect(deps.bannerHistory).toContain('Reconnect failed — refresh to retry');
		expect(deps.loadChat).not.toHaveBeenCalled();
	});

	it('class-9: 30s hard timeout → timed-out banner → loadChat → null', async () => {
		// Server hangs — never resolves
		const deps = makeDeps({
			getActiveRun: vi.fn().mockImplementation(() => new Promise(() => {})),
			HARD_TIMEOUT_MS: 30_000
		});

		const p = tryResumeInflight('chat-1', deps);

		// Advance to just before the timeout — no banner yet from hard timeout
		await vi.advanceTimersByTimeAsync(29_999);
		expect(deps.bannerHistory).not.toContain('Reconnect timed out — falling back to saved state');

		// Advance past the 30s timeout and flush microtasks
		await vi.advanceTimersByTimeAsync(2);
		await Promise.resolve(); // flush microtask queue

		expect(deps.bannerHistory).toContain('Reconnect timed out — falling back to saved state');
		expect(deps.loadChat).toHaveBeenCalledOnce();
		// After loadChat the banner is cleared
		expect(deps.bannerHistory.at(-1)).toBeNull();

		// Abort the hanging promise to avoid test leak
		p.catch(() => {});
	});

	it('server responds <200ms → paint timer fires for nothing, no stale snapshot shown', async () => {
		// Server resolves immediately (synchronous mock)
		const deps = makeDeps({
			getActiveRun: vi.fn().mockResolvedValue({ run_id: null, started_at: null, message_id: null }),
			loadInflightSnapshot: vi.fn().mockReturnValue({
				chat_id: 'chat-1',
				message_id: 'msg-1',
				message_content: 'stale',
				output: []
			}),
			PAINT_THRESHOLD_MS: 200
		});

		const p = tryResumeInflight('chat-1', deps);
		// Settle the server promise (microtasks) before advancing past paint threshold
		await Promise.resolve();
		await p;

		// The stale snapshot must NOT have been painted (server was fast)
		expect(deps.bannerHistory).not.toContain('Reconnecting...');
		expect(deps.applyHistory).toHaveLength(0);
	});
});
