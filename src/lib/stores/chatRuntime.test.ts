import { beforeEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import { chatRuntimeStore } from './chatRuntime';

const completionEvent = (chatId = 'chat-a', messageId = 'assistant-1', content = 'Hello') => ({
	chat_id: chatId,
	message_id: messageId,
	data: {
		type: 'chat:completion',
		data: {
			done: false,
			content,
			output: [{ id: `${messageId}-output`, type: 'message', status: 'in_progress' }]
		}
	}
});

describe('chatRuntimeStore', () => {
	beforeEach(() => {
		chatRuntimeStore.reset();
	});

	it('applies real nested socket events into store state', () => {
		chatRuntimeStore.applyEvent(completionEvent(), 1000);

		expect(get(chatRuntimeStore).chats['chat-a'].messages['assistant-1'].content).toBe('Hello');
		expect(chatRuntimeStore.getSnapshot('chat-a')?.active).toBe(true);
	});

	it('merges runtime projection onto DB history with graph-safe helpers', () => {
		chatRuntimeStore.applyEvent(completionEvent(), 1000);

		const merged = chatRuntimeStore.mergeHistory(
			'chat-a',
			{
				currentId: 'assistant-1',
				messages: {
					'user-1': { id: 'user-1', role: 'user', childrenIds: ['assistant-1'] },
					'assistant-1': {
						id: 'assistant-1',
						role: 'assistant',
						parentId: 'user-1',
						childrenIds: [],
						content: ''
					}
				}
			},
			2000
		);

		expect(merged.messages['assistant-1'].content).toBe('Hello');
		expect(merged.messages['assistant-1'].parentId).toBe('user-1');
	});

	it('clears one chat without affecting others', () => {
		chatRuntimeStore.applyEvent(completionEvent('chat-a', 'assistant-1', 'A'), 1000);
		chatRuntimeStore.applyEvent(completionEvent('chat-b', 'assistant-2', 'B'), 1000);

		chatRuntimeStore.clearChat('chat-a');

		expect(chatRuntimeStore.getSnapshot('chat-a')).toBeNull();
		expect(chatRuntimeStore.getSnapshot('chat-b')?.messages['assistant-2'].content).toBe('B');
	});

	it('prunes old inactive chats while keeping active chats', () => {
		chatRuntimeStore.applyEvent(
			{
				...completionEvent('old-chat', 'assistant-1', 'old'),
				data: { type: 'chat:completion', data: { done: true, content: 'old' } }
			},
			1000
		);
		chatRuntimeStore.applyEvent(completionEvent('active-chat', 'assistant-2', 'active'), 1000);

		chatRuntimeStore.prune({ maxAgeMs: 100, maxChats: 25, now: 2000 });

		expect(chatRuntimeStore.getSnapshot('old-chat')).toBeNull();
		expect(chatRuntimeStore.getSnapshot('active-chat')).not.toBeNull();
	});

	it('limits retained chats to the newest maxChats entries', () => {
		chatRuntimeStore.applyEvent(
			{
				...completionEvent('chat-1', 'assistant-1', 'one'),
				data: { type: 'chat:completion', data: { done: true, content: 'one' } }
			},
			1000
		);
		chatRuntimeStore.applyEvent(
			{
				...completionEvent('chat-2', 'assistant-2', 'two'),
				data: { type: 'chat:completion', data: { done: true, content: 'two' } }
			},
			2000
		);

		chatRuntimeStore.prune({ maxAgeMs: 10_000, maxChats: 1, now: 3000 });

		expect(chatRuntimeStore.getSnapshot('chat-1')).toBeNull();
		expect(chatRuntimeStore.getSnapshot('chat-2')).not.toBeNull();
	});
});
