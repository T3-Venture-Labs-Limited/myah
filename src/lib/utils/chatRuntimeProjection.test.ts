import { describe, expect, it } from 'vitest';
import {
	applyChatRuntimeEvent,
	emptyChatRuntimeState,
	getProjectedChatHistory,
	normalizeChatRuntimeEvent,
	reconcileLoadedHistoryWithRuntime,
	type ChatRuntimeState
} from './chatRuntimeProjection';

const completionEvent = (overrides: Record<string, unknown> = {}) => ({
	chat_id: 'chat-a',
	message_id: 'assistant-1',
	event_id: 'evt-1',
	data: {
		type: 'chat:completion',
		data: {
			done: false,
			content: 'Hello',
			output: [
				{
					id: 'msg_1',
					type: 'message',
					role: 'assistant',
					content: [{ type: 'output_text', text: 'Hello' }],
					status: 'in_progress'
				}
			]
		}
	},
	...overrides
});

describe('chatRuntimeProjection', () => {
	it('normalizes real nested chat completion socket events', () => {
		expect(normalizeChatRuntimeEvent(completionEvent())).toEqual({
			chatId: 'chat-a',
			messageId: 'assistant-1',
			type: 'chat:completion',
			payload: completionEvent().data.data,
			eventId: 'evt-1'
		});
	});

	it('ignores unsupported, malformed, and local chat completion events', () => {
		expect(normalizeChatRuntimeEvent({ data: { type: 'chat:title', data: {} } })).toBeNull();
		expect(normalizeChatRuntimeEvent(completionEvent({ chat_id: '' }))).toBeNull();
		expect(normalizeChatRuntimeEvent(completionEvent({ chat_id: 'local:chat-a' }))).toBeNull();
		expect(normalizeChatRuntimeEvent(completionEvent({ message_id: '' }))).toBeNull();
	});

	it('normalizes chat active events without requiring message_id', () => {
		expect(
			normalizeChatRuntimeEvent({
				chat_id: 'chat-a',
				data: { type: 'chat:active', data: { active: true } }
			})
		).toEqual({
			chatId: 'chat-a',
			type: 'chat:active',
			payload: { active: true }
		});
	});

	it('creates a per-chat projection from a streaming chat completion event', () => {
		const next = applyChatRuntimeEvent(emptyChatRuntimeState(), completionEvent(), 1000);

		expect(next.chats['chat-a'].messages['assistant-1'].content).toBe('Hello');
		expect(next.chats['chat-a'].messages['assistant-1'].output).toHaveLength(1);
		expect(next.chats['chat-a'].messages['assistant-1'].done).toBe(false);
		expect(next.chats['chat-a'].active).toBe(true);
		expect(next.chats['chat-a'].lastEventId).toBe('evt-1');
	});

	it('preserves rich output while replacing later authoritative content for non-active chats', () => {
		let state: ChatRuntimeState = emptyChatRuntimeState();
		state = applyChatRuntimeEvent(state, completionEvent(), 1000);
		state = applyChatRuntimeEvent(
			state,
			completionEvent({
				event_id: 'evt-2',
				data: {
					type: 'chat:completion',
					data: {
						done: false,
						content: 'Thinking done',
						output: [
							{
								id: 'rsn_1',
								type: 'reasoning',
								status: 'completed',
								summary: [{ type: 'summary_text', text: 'Thinking' }]
							},
							{
								id: 'call_1',
								type: 'function_call',
								name: 'terminal',
								call_id: 'call_1',
								status: 'in_progress',
								arguments: '{}'
							}
						]
					}
				}
			}),
			2000
		);

		expect(state.chats['chat-a'].messages['assistant-1'].content).toBe('Thinking done');
		expect(state.chats['chat-a'].messages['assistant-1'].output?.map((item) => item.type)).toEqual([
			'reasoning',
			'function_call'
		]);
	});

	it('marks a chat inactive on done true but keeps final output projection', () => {
		const next = applyChatRuntimeEvent(
			emptyChatRuntimeState(),
			completionEvent({
				data: {
					type: 'chat:completion',
					data: {
						done: true,
						content: 'Final',
						output: [
							{
								id: 'msg_1',
								type: 'message',
								role: 'assistant',
								content: [{ type: 'output_text', text: 'Final' }],
								status: 'completed'
							}
						]
					}
				}
			})
		);

		expect(next.chats['chat-a'].active).toBe(false);
		expect(next.chats['chat-a'].messages['assistant-1'].done).toBe(true);
		expect(next.chats['chat-a'].messages['assistant-1'].output).toHaveLength(1);
	});

	it('updates active state from chat active events', () => {
		const next = applyChatRuntimeEvent(emptyChatRuntimeState(), {
			chat_id: 'chat-a',
			data: { type: 'chat:active', data: { active: true } }
		});

		expect(next.chats['chat-a'].active).toBe(true);
		expect(next.chats['chat-a'].currentId).toBeNull();
	});

	it('overlays runtime fields onto an existing DB message shell without erasing graph metadata', () => {
		const state = applyChatRuntimeEvent(emptyChatRuntimeState(), completionEvent(), 1000);
		const projected = getProjectedChatHistory(
			{
				currentId: 'assistant-1',
				messages: {
					'user-1': { id: 'user-1', role: 'user', content: 'Hi', childrenIds: ['assistant-1'] },
					'assistant-1': {
						id: 'assistant-1',
						role: 'assistant',
						content: '',
						parentId: 'user-1',
						childrenIds: [],
						model: 'old-model',
						timestamp: 123,
						done: false
					}
				}
			},
			state.chats['chat-a'],
			2000
		);

		expect(projected.messages['assistant-1']).toMatchObject({
			content: 'Hello',
			parentId: 'user-1',
			childrenIds: [],
			model: 'old-model',
			timestamp: 123
		});
		expect(projected.messages['assistant-1'].output).toHaveLength(1);
	});

	it('creates a graph-safe minimal assistant shell when DB history is missing the streamed message', () => {
		const state = applyChatRuntimeEvent(emptyChatRuntimeState(), completionEvent(), 1000);
		const projected = getProjectedChatHistory(
			{
				currentId: 'user-1',
				messages: {
					'user-1': { id: 'user-1', role: 'user', content: 'Hi', childrenIds: [] }
				}
			},
			state.chats['chat-a'],
			2000
		);

		expect(projected.currentId).toBe('assistant-1');
		expect(projected.messages['assistant-1']).toMatchObject({
			id: 'assistant-1',
			role: 'assistant',
			parentId: 'user-1',
			childrenIds: [],
			content: 'Hello',
			timestamp: 2000
		});
		expect(projected.messages['user-1'].childrenIds).toEqual(['assistant-1']);
	});

	it('fast projection for a different chat does not retain previous chat history', () => {
		const state = applyChatRuntimeEvent(
			emptyChatRuntimeState(),
			completionEvent({
				chat_id: 'chat-b',
				message_id: 'assistant-b',
				data: {
					type: 'chat:completion',
					data: {
						done: false,
						content: 'Live answer for chat B',
						output: [
							{
								id: 'msg_b',
								type: 'message',
								role: 'assistant',
								content: [{ type: 'output_text', text: 'Live answer for chat B' }],
								status: 'in_progress'
							}
						]
					}
				}
			}),
			1000
		);

		const projected = getProjectedChatHistory(
			{
				currentId: 'assistant-a',
				chatId: 'chat-a',
				messages: {
					'user-a': {
						id: 'user-a',
						role: 'user',
						content: 'Question from chat A',
						childrenIds: ['assistant-a']
					},
					'assistant-a': {
						id: 'assistant-a',
						role: 'assistant',
						content: 'Answer from chat A',
						parentId: 'user-a',
						childrenIds: []
					}
				}
			},
			state.chats['chat-b'],
			2000,
			{ chatId: 'chat-b', isolateToChat: true }
		);

		expect(projected.messages['user-a']).toBeUndefined();
		expect(projected.messages['assistant-a']).toBeUndefined();
		expect(projected.currentId).toBe('assistant-b');
		expect(projected.messages['assistant-b']).toMatchObject({
			id: 'assistant-b',
			role: 'assistant',
			content: 'Live answer for chat B'
		});
	});

	it('reconciles loaded DB history with newer runtime projection after DB load completes', () => {
		const state = applyChatRuntimeEvent(emptyChatRuntimeState(), completionEvent(), 1000);
		const reconciled = reconcileLoadedHistoryWithRuntime(
			{
				currentId: 'assistant-1',
				messages: {
					'user-1': { id: 'user-1', role: 'user', content: 'Hi', childrenIds: ['assistant-1'] },
					'assistant-1': {
						id: 'assistant-1',
						role: 'assistant',
						content: 'stale-db-content',
						parentId: 'user-1',
						childrenIds: [],
						done: false
					}
				}
			},
			state.chats['chat-a'],
			2000
		);

		expect(reconciled.messages['assistant-1'].content).toBe('Hello');
		expect(reconciled.messages['assistant-1'].parentId).toBe('user-1');
	});
});
