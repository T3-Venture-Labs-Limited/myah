import { describe, expect, it } from 'vitest';
import type { ActiveRun } from '$lib/apis/chats';
import { activeChatIdSetFromRuns, applyActiveChatEvent } from './activeRuns';

describe('active run helpers', () => {
	it('builds a replacement set from valid active runs', () => {
		const runs = [
			{ chat_id: 'chat-1', run_id: 'run-1', started_at: 1, message_id: 'msg-1' },
			{ chat_id: '', run_id: 'run-empty', started_at: 2, message_id: 'msg-empty' },
			{ chat_id: 'chat-2', run_id: null, started_at: null, message_id: null },
			null
		] as unknown as ActiveRun[];

		expect(activeChatIdSetFromRuns(runs)).toEqual(new Set(['chat-1']));
	});

	it('replacement hydration drops stale IDs not present in backend snapshot', () => {
		const before = new Set(['stale-chat']);
		const hydrated = activeChatIdSetFromRuns([
			{ chat_id: 'chat-1', run_id: 'run-1', started_at: 1, message_id: 'msg-1' }
		]);

		expect(before).toEqual(new Set(['stale-chat']));
		expect(hydrated).toEqual(new Set(['chat-1']));
	});

	it('applies socket active true/false events after hydration', () => {
		const hydrated = new Set(['chat-1', 'chat-2']);

		expect(applyActiveChatEvent(hydrated, 'chat-2', false)).toEqual(new Set(['chat-1']));
		expect(applyActiveChatEvent(hydrated, 'chat-3', true)).toEqual(
			new Set(['chat-1', 'chat-2', 'chat-3'])
		);
	});
});
