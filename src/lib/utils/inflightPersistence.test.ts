import { describe, it, expect, beforeEach, vi } from 'vitest';
import type { InflightSnapshot } from '../types';
import {
	saveInflightSnapshot,
	loadInflightSnapshot,
	clearInflightSnapshot,
	pruneStaleSnapshots,
	markInflightDurableFinal
} from './inflightPersistence';

// ---------------------------------------------------------------------------
// Minimal localStorage stub — vitest's default environment (node) does not
// provide a DOM. We implement just enough of the Storage interface to cover
// the APIs used by inflightPersistence.ts.
// ---------------------------------------------------------------------------
function makeLocalStorageStub() {
	const store: Map<string, string> = new Map();
	return {
		get length() {
			return store.size;
		},
		key(index: number): string | null {
			return [...store.keys()][index] ?? null;
		},
		getItem(key: string): string | null {
			return store.has(key) ? store.get(key)! : null;
		},
		setItem(key: string, value: string): void {
			store.set(key, value);
		},
		removeItem(key: string): void {
			store.delete(key);
		},
		clear(): void {
			store.clear();
		}
	};
}

const KEY_PREFIX = 'myah-inflight-state:';

function makeSnapshot(overrides: Partial<InflightSnapshot> = {}): InflightSnapshot {
	return {
		run_id: 'run-1',
		chat_id: 'chat-abc',
		message_id: 'msg-1',
		started_at: Date.now(),
		updated_at: Date.now(),
		message_content: 'hello',
		reasoning_content: '',
		output: [],
		status: 'streaming',
		...overrides
	};
}

let stub = makeLocalStorageStub();

beforeEach(() => {
	stub = makeLocalStorageStub();
	vi.stubGlobal('localStorage', stub);
});

describe('inflightPersistence', () => {
	it('save/load round-trip preserves snapshot content', () => {
		const snapshot = makeSnapshot({
			message_content: 'round-trip test',
			output: [
				{
					id: 'tool-1',
					type: 'function_call',
					call_id: 'call-1',
					name: 'demo_tool',
					arguments: '{}',
					status: 'in_progress'
				}
			]
		});
		saveInflightSnapshot(snapshot);
		const loaded = loadInflightSnapshot(snapshot.chat_id);

		expect(loaded).not.toBeNull();
		expect(loaded!.run_id).toBe(snapshot.run_id);
		expect(loaded!.chat_id).toBe(snapshot.chat_id);
		expect(loaded!.message_id).toBe(snapshot.message_id);
		expect(loaded!.message_content).toBe('round-trip test');
		expect(loaded!.output).toEqual(snapshot.output);
		expect(loaded!.status).toBe('streaming');
	});

	it('saveInflightSnapshot stamps updated_at with current time', () => {
		const before = Date.now();
		const snapshot = makeSnapshot({ updated_at: 0 });
		saveInflightSnapshot(snapshot);
		const after = Date.now();

		const loaded = loadInflightSnapshot(snapshot.chat_id);
		expect(loaded!.updated_at).toBeGreaterThanOrEqual(before);
		expect(loaded!.updated_at).toBeLessThanOrEqual(after);
	});

	it('quota-exceeded error is swallowed silently', () => {
		vi.stubGlobal('localStorage', {
			...stub,
			setItem() {
				throw new DOMException('QuotaExceededError', 'QuotaExceededError');
			}
		});
		expect(() => saveInflightSnapshot(makeSnapshot())).not.toThrow();
	});

	it('drops oversized output before storage while preserving message content', () => {
		const oversizedOutput: NonNullable<InflightSnapshot['output']> = [
			{
				id: 'huge-tool',
				type: 'function_call_output',
				call_id: 'call-huge',
				status: 'completed',
				output: [{ type: 'input_text', text: 'x'.repeat(250_000) }]
			}
		];
		const snapshot = makeSnapshot({
			message_content: 'partial answer',
			output: oversizedOutput
		});

		saveInflightSnapshot(snapshot);

		const loaded = loadInflightSnapshot(snapshot.chat_id);
		expect(loaded!.message_content).toBe('partial answer');
		expect(loaded!.output).toEqual([]);
	});

	it('loadInflightSnapshot returns null for absent key', () => {
		expect(loadInflightSnapshot('no-such-chat')).toBeNull();
	});

	it('loadInflightSnapshot returns null for malformed JSON', () => {
		stub.setItem(`${KEY_PREFIX}chat-bad`, 'not-json');
		expect(loadInflightSnapshot('chat-bad')).toBeNull();
	});

	it('clearInflightSnapshot removes the entry', () => {
		const snapshot = makeSnapshot({ chat_id: 'chat-to-clear' });
		saveInflightSnapshot(snapshot);
		clearInflightSnapshot('chat-to-clear');
		expect(loadInflightSnapshot('chat-to-clear')).toBeNull();
	});

	it('pruneStaleSnapshots removes stale entries and keeps fresh ones', () => {
		const now = Date.now();
		const staleChat = 'chat-stale';
		const freshChat = 'chat-fresh';

		// Write directly so we control updated_at precisely
		const stale = makeSnapshot({ chat_id: staleChat, updated_at: now - 700_000 });
		stub.setItem(`${KEY_PREFIX}${staleChat}`, JSON.stringify(stale));

		const fresh = makeSnapshot({ chat_id: freshChat, updated_at: now - 60_000 });
		stub.setItem(`${KEY_PREFIX}${freshChat}`, JSON.stringify(fresh));

		pruneStaleSnapshots();

		expect(loadInflightSnapshot(staleChat)).toBeNull();
		expect(loadInflightSnapshot(freshChat)).not.toBeNull();
	});

	it('pruneStaleSnapshots removes malformed entries', () => {
		stub.setItem(`${KEY_PREFIX}chat-broken`, 'not-json');

		pruneStaleSnapshots();

		expect(stub.getItem(`${KEY_PREFIX}chat-broken`)).toBeNull();
	});

	describe('durable-final aware cleanup', () => {
		it('markInflightDurableFinal clears a matching settled snapshot', () => {
			saveInflightSnapshot(
				makeSnapshot({ chat_id: 'chat-x', message_id: 'msg-x', status: 'settled' })
			);
			expect(markInflightDurableFinal('chat-x', 'msg-x')).toBe(true);
			expect(loadInflightSnapshot('chat-x')).toBeNull();
		});

		it('markInflightDurableFinal does not clear a different in-flight message snapshot', () => {
			// A newer in-flight message already replaced the snapshot for this chat.
			saveInflightSnapshot(
				makeSnapshot({ chat_id: 'chat-x', message_id: 'msg-new', status: 'streaming' })
			);
			// A late durable-final ack for the OLD message must not wipe it.
			expect(markInflightDurableFinal('chat-x', 'msg-old')).toBe(false);
			expect(loadInflightSnapshot('chat-x')?.message_id).toBe('msg-new');
		});

		it('a settled snapshot survives past the old fixed 10s window — only durable final clears it', () => {
			vi.useFakeTimers();
			try {
				saveInflightSnapshot(
					makeSnapshot({ chat_id: 'chat-x', message_id: 'msg-x', status: 'settled' })
				);

				// The old behaviour cleared after a fixed 10s; that must no longer happen.
				vi.advanceTimersByTime(11_000);
				expect(loadInflightSnapshot('chat-x')).not.toBeNull();

				// Durable final acknowledgement is what clears it.
				markInflightDurableFinal('chat-x', 'msg-x');
				expect(loadInflightSnapshot('chat-x')).toBeNull();
			} finally {
				vi.useRealTimers();
			}
		});

		it('a never-confirmed snapshot (e.g. failed DB save) is only removed by the stale TTL', () => {
			vi.useFakeTimers();
			try {
				// updated_at far enough in the past that it is already stale.
				const now = Date.now();
				const snap = makeSnapshot({
					chat_id: 'chat-x',
					message_id: 'msg-x',
					status: 'settled',
					updated_at: now - 700_000
				});
				stub.setItem(`${KEY_PREFIX}chat-x`, JSON.stringify(snap));

				// No durable final ack happened (DB save failed). It is not cleared
				// eagerly, only when the stale TTL prune runs.
				expect(loadInflightSnapshot('chat-x')).not.toBeNull();
				pruneStaleSnapshots();
				expect(loadInflightSnapshot('chat-x')).toBeNull();
			} finally {
				vi.useRealTimers();
			}
		});
	});
});
