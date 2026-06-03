// Scenario-level tests for T3-1096 stream continuity. These model the
// route-hop and refresh flows at the store/projection seam without mounting a
// Svelte component. They lock the residual bug class before Tasks 3 and 4.
//
// IMPORTANT (per plan audit): these use the normalized Socket.IO event shape
// the browser actually receives (chat_id / message_id / data.type /
// data.data), NOT raw Hermes SSE fixtures.

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import { chatRuntimeStore } from '../stores/chatRuntime';
import { getProjectedChatHistory } from './chatRuntimeProjection';

const completion = (
	chatId: string,
	messageId: string,
	data: Record<string, unknown>
) => ({
	chat_id: chatId,
	message_id: messageId,
	data: { type: 'chat:completion', data }
});

beforeEach(() => {
	chatRuntimeStore.reset();
});

describe('stream continuation — route hop', () => {
	it('renders the seeded user + assistant graph and live partial before DB load resolves', () => {
		// 1. Chat A starts with a seeded user/assistant graph (Task 3 capability).
		chatRuntimeStore.seedHistory(
			'chat-a',
			{
				currentId: 'assistant-1',
				messages: {
					'user-1': {
						id: 'user-1',
						role: 'user',
						content: 'write slowly',
						childrenIds: ['assistant-1']
					},
					'assistant-1': {
						id: 'assistant-1',
						role: 'assistant',
						parentId: 'user-1',
						childrenIds: [],
						content: '',
						done: false
					}
				}
			},
			1000
		);

		// 2. Root layout ingests streaming events while Chat A is unmounted.
		chatRuntimeStore.applyEvent(
			completion('chat-a', 'assistant-1', {
				done: false,
				content: 'partial answer',
				output: [{ id: 'msg_1', type: 'message', status: 'in_progress' }]
			}),
			1001
		);

		// 3. User navigates back; DB load is still pending so history is empty.
		const projected = getProjectedChatHistory(
			{ currentId: null, messages: {} },
			chatRuntimeStore.getSnapshot('chat-a'),
			1002,
			{ chatId: 'chat-a', isolateToChat: true }
		);

		// 4. Render model has the user message, the assistant partial, and output.
		expect(projected.messages['user-1']).toBeTruthy();
		expect(projected.messages['user-1'].childrenIds).toEqual(['assistant-1']);
		expect(projected.messages['assistant-1'].parentId).toBe('user-1');
		expect(projected.messages['assistant-1'].content).toBe('partial answer');
		expect(projected.messages['assistant-1'].output).toHaveLength(1);
		expect(projected.currentId).toBe('assistant-1');
	});

	it('keeps the projection visible after the final event until durable final is acknowledged', () => {
		chatRuntimeStore.seedHistory(
			'chat-a',
			{
				currentId: 'assistant-1',
				messages: {
					'user-1': { id: 'user-1', role: 'user', content: 'q', childrenIds: ['assistant-1'] },
					'assistant-1': {
						id: 'assistant-1',
						role: 'assistant',
						parentId: 'user-1',
						childrenIds: [],
						content: '',
						done: false
					}
				}
			},
			1000
		);

		// 5. Final event arrives before DB persistence.
		chatRuntimeStore.applyEvent(
			completion('chat-a', 'assistant-1', { done: true, content: 'final answer' }),
			1001
		);

		// 6. Projection still shows the final content (not cleared just because done).
		const afterFinal = getProjectedChatHistory(
			{ currentId: null, messages: {} },
			chatRuntimeStore.getSnapshot('chat-a'),
			1002,
			{ chatId: 'chat-a', isolateToChat: true }
		);
		expect(afterFinal.messages['assistant-1'].content).toBe('final answer');

		// 7/8. Durable final acknowledgement (DB settled) clears runtime state.
		chatRuntimeStore.markDurableFinal('chat-a', 'assistant-1');
		expect(chatRuntimeStore.getSnapshot('chat-a')).toBeNull();
	});
});

describe('stream continuation — refresh', () => {
	it('can paint active partial output from a server live snapshot even if DB load is slow', () => {
		// Browser refreshed: runtime store is empty (simulated by reset()).
		expect(chatRuntimeStore.getSnapshot('chat-a')).toBeNull();

		// /active_run + /live_state return active partial state. We apply it via the
		// runtime store the same way the resume flow will.
		chatRuntimeStore.seedHistory(
			'chat-a',
			{
				currentId: 'assistant-1',
				messages: {
					'user-1': { id: 'user-1', role: 'user', content: 'q', childrenIds: ['assistant-1'] },
					'assistant-1': {
						id: 'assistant-1',
						role: 'assistant',
						parentId: 'user-1',
						childrenIds: [],
						content: '',
						done: false
					}
				}
			},
			2000
		);
		chatRuntimeStore.applyEvent(
			completion('chat-a', 'assistant-1', {
				done: false,
				content: 'streaming after refresh',
				output: [{ id: 'msg_1', type: 'message', status: 'in_progress' }]
			}),
			2001
		);

		const projected = getProjectedChatHistory(
			{ currentId: null, messages: {} },
			chatRuntimeStore.getSnapshot('chat-a'),
			2002,
			{ chatId: 'chat-a', isolateToChat: true }
		);

		expect(projected.messages['assistant-1'].content).toBe('streaming after refresh');
		expect(get(chatRuntimeStore).chats['chat-a'].active).toBe(true);
	});
});
