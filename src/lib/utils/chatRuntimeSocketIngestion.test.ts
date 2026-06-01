import { describe, expect, it, vi } from 'vitest';
import { ingestChatRuntimeSocketEvent } from './chatRuntimeSocketIngestion';

const completionEvent = {
	chat_id: 'chat-a',
	message_id: 'assistant-1',
	data: { type: 'chat:completion', data: { content: 'Hello', done: false } }
};

describe('ingestChatRuntimeSocketEvent', () => {
	it('applies runtime projection and persists snapshots for completion events', () => {
		const applyEvent = vi.fn();
		const persistInflightSnapshotFromEvent = vi.fn();

		ingestChatRuntimeSocketEvent(completionEvent, { applyEvent, persistInflightSnapshotFromEvent });

		expect(applyEvent).toHaveBeenCalledWith(completionEvent);
		expect(persistInflightSnapshotFromEvent).toHaveBeenCalledWith(completionEvent);
	});

	it('applies runtime projection for chat active events without snapshot persistence', () => {
		const applyEvent = vi.fn();
		const persistInflightSnapshotFromEvent = vi.fn();
		const event = { chat_id: 'chat-a', data: { type: 'chat:active', data: { active: true } } };

		ingestChatRuntimeSocketEvent(event, { applyEvent, persistInflightSnapshotFromEvent });

		expect(applyEvent).toHaveBeenCalledWith(event);
		expect(persistInflightSnapshotFromEvent).not.toHaveBeenCalled();
	});

	it('ignores events without chat_id or with local chat ids', () => {
		const applyEvent = vi.fn();
		const persistInflightSnapshotFromEvent = vi.fn();

		ingestChatRuntimeSocketEvent(
			{ ...completionEvent, chat_id: '' },
			{ applyEvent, persistInflightSnapshotFromEvent }
		);
		ingestChatRuntimeSocketEvent(
			{ ...completionEvent, chat_id: 'local:chat-a' },
			{ applyEvent, persistInflightSnapshotFromEvent }
		);

		expect(applyEvent).not.toHaveBeenCalled();
		expect(persistInflightSnapshotFromEvent).not.toHaveBeenCalled();
	});
});
