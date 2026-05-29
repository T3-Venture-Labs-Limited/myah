import { describe, expect, it } from 'vitest';
import { applyDurableFinalMessageEvent } from './chatEventFallback';

describe('applyDurableFinalMessageEvent', () => {
	it('applies final fallback content to the active chat message', () => {
		const chat = {
			history: {
				currentId: 'msg-1',
				messages: {
					'msg-1': { id: 'msg-1', role: 'assistant', content: '', done: false }
				}
			}
		};

		const applied = applyDurableFinalMessageEvent(
			{
				chat_id: 'chat-1',
				message_id: 'msg-1',
				data: { type: 'chat:completion', data: { content: 'final answer', done: true } }
			},
			'chat-1',
			chat
		);

		expect(applied).toBe(true);
		expect(chat.history.messages['msg-1'].content).toBe('final answer');
		expect(chat.history.messages['msg-1'].done).toBe(true);
	});

	it('ignores events for other chats', () => {
		const chat = {
			history: {
				messages: {
					'msg-1': { id: 'msg-1', role: 'assistant', content: '', done: false }
				}
			}
		};

		const applied = applyDurableFinalMessageEvent(
			{
				chat_id: 'other-chat',
				message_id: 'msg-1',
				data: { type: 'chat:completion', data: { content: 'wrong', done: true } }
			},
			'chat-1',
			chat
		);

		expect(applied).toBe(false);
		expect(chat.history.messages['msg-1'].content).toBe('');
		expect(chat.history.messages['msg-1'].done).toBe(false);
	});
});
