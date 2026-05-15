import { describe, it, expect, vi, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import type { Process } from '$lib/apis/processes';

// We test the side-effect logic embedded in SchedulePopover.svelte by
// re-implementing it inline below.  @testing-library/svelte isn't installed
// in this repo (see SkillLoadInline.test.ts comment), so the contract here
// is: this test must stay in lockstep with the helpers inside the component.
// If the component implementation drifts, update both.

import { processMap } from '$lib/stores/tasks';

// ── Pure helpers extracted from SchedulePopover.svelte ──────────────

function toastErrorMessage(err: unknown, fallback: string): string {
	if (typeof err === 'string' && err.trim()) return err;
	if (err && typeof err === 'object') {
		const e = err as { detail?: string; message?: string };
		if (typeof e.detail === 'string' && e.detail.trim()) return e.detail;
		if (typeof e.message === 'string' && e.message.trim()) return e.message;
	}
	return fallback;
}

function syncProcessMap(updated: Process) {
	processMap.update((m) => {
		const next = new Map(m);
		next.set(updated.id, updated);
		if (updated.chat_id) {
			next.set(updated.chat_id, updated);
		}
		for (const [k, v] of m.entries()) {
			if (v.id === updated.id) next.set(k, updated);
		}
		return next;
	});
}

const baseProcess = (overrides: Partial<Process> = {}): Process =>
	({
		id: 'job-1',
		name: 'test-job',
		prompt: 'hi',
		schedule: { kind: 'interval', minutes: 1, display: 'every 1m' },
		schedule_display: 'every 1m',
		repeat: { times: null, completed: 0 },
		enabled: true,
		state: 'scheduled',
		paused_at: null,
		paused_reason: null,
		created_at: new Date().toISOString(),
		next_run_at: null,
		last_run_at: null,
		last_status: null,
		last_error: null,
		last_delivery_error: null,
		deliver: 'origin',
		origin: { platform: 'myah', chat_id: 'chat-1', chat_name: null, thread_id: null },
		chat_id: 'chat-1',
		...overrides
	}) as unknown as Process;

// ── Tests ───────────────────────────────────────────────────────────

describe('SchedulePopover.toastErrorMessage', () => {
	it('extracts ``detail`` from FastAPI-shaped errors', () => {
		expect(toastErrorMessage({ detail: 'Invalid job ID' }, 'fallback')).toBe('Invalid job ID');
	});

	it('extracts ``message`` from generic Error-shaped objects', () => {
		expect(toastErrorMessage({ message: 'Network error' }, 'fallback')).toBe('Network error');
	});

	it('returns a non-empty string error verbatim', () => {
		expect(toastErrorMessage('boom', 'fallback')).toBe('boom');
	});

	it('falls back when the error has no useful field', () => {
		expect(toastErrorMessage({}, 'Failed to pause schedule')).toBe('Failed to pause schedule');
		expect(toastErrorMessage(null, 'Failed')).toBe('Failed');
		expect(toastErrorMessage(undefined, 'Failed')).toBe('Failed');
	});

	it('falls back on whitespace-only detail', () => {
		expect(toastErrorMessage({ detail: '   ' }, 'Default')).toBe('Default');
	});

	it('prefers detail over message when both are present', () => {
		expect(toastErrorMessage({ detail: 'first', message: 'second' }, 'fb')).toBe('first');
	});
});

describe('SchedulePopover.syncProcessMap', () => {
	beforeEach(() => {
		processMap.set(new Map());
	});

	it('writes the updated process under its id and chat_id keys', () => {
		const updated = baseProcess({ enabled: false, state: 'paused' });
		syncProcessMap(updated);

		const map = get(processMap);
		expect(map.get('job-1')).toMatchObject({ enabled: false, state: 'paused' });
		expect(map.get('chat-1')).toMatchObject({ enabled: false, state: 'paused' });
	});

	it('replaces every existing key that pointed at the same process', () => {
		// Mirror what TaskList.svelte does: write the same process under
		// three keys (process id, chat_id, title-matched chat id).
		const initial = baseProcess({ enabled: true, state: 'scheduled' });
		processMap.update((m) => {
			const n = new Map(m);
			n.set('job-1', initial);
			n.set('chat-1', initial);
			n.set('legacy-process-chat-id', initial);
			return n;
		});

		const updated = baseProcess({ enabled: false, state: 'paused' });
		syncProcessMap(updated);

		const map = get(processMap);
		expect(map.get('job-1')?.state).toBe('paused');
		expect(map.get('chat-1')?.state).toBe('paused');
		expect(map.get('legacy-process-chat-id')?.state).toBe('paused');
	});

	it('does not touch entries belonging to other processes', () => {
		const other = baseProcess({ id: 'other-job', chat_id: 'other-chat' });
		processMap.update((m) => {
			const n = new Map(m);
			n.set('other-job', other);
			n.set('other-chat', other);
			return n;
		});

		syncProcessMap(baseProcess({ enabled: false, state: 'paused' }));

		const map = get(processMap);
		expect(map.get('other-job')).toBe(other);
		expect(map.get('other-chat')).toBe(other);
		expect(map.get('job-1')?.state).toBe('paused');
	});

	it('handles processes with no chat_id without crashing', () => {
		const orphan = baseProcess({ id: 'orphan', chat_id: undefined as any });
		expect(() => syncProcessMap(orphan)).not.toThrow();
		const map = get(processMap);
		expect(map.get('orphan')?.id).toBe('orphan');
	});
});
