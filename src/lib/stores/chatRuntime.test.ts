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

	it('seeds user and assistant graph before socket events arrive', () => {
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

		chatRuntimeStore.applyEvent(
			{
				chat_id: 'chat-a',
				message_id: 'assistant-1',
				data: { type: 'chat:completion', data: { done: false, content: 'partial' } }
			},
			1001
		);

		const merged = chatRuntimeStore.mergeHistory('chat-a', { currentId: null, messages: {} });
		expect(merged.messages['user-1']).toBeTruthy();
		expect(merged.messages['assistant-1'].parentId).toBe('user-1');
		expect(merged.messages['assistant-1'].content).toBe('partial');
	});

	it('seeding does not overwrite newer streaming content when an event arrived first', () => {
		// Event arrives before seedHistory (race) with live content.
		chatRuntimeStore.applyEvent(
			{
				chat_id: 'chat-a',
				message_id: 'assistant-1',
				data: { type: 'chat:completion', data: { done: false, content: 'live tokens' } }
			},
			1000
		);

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
			1001
		);

		const snapshot = chatRuntimeStore.getSnapshot('chat-a');
		expect(snapshot?.messages['assistant-1'].content).toBe('live tokens');
		expect(snapshot?.messages['assistant-1'].parentId).toBe('user-1');
		expect(snapshot?.currentId).toBe('assistant-1');
	});

	it('seeds branched multi-turn history without recomputing childrenIds from object order', () => {
		chatRuntimeStore.seedHistory(
			'chat-a',
			{
				currentId: 'assistant-2',
				// Deliberately out of graph order to prove order independence.
				messages: {
					'assistant-2': {
						id: 'assistant-2',
						role: 'assistant',
						parentId: 'user-2',
						childrenIds: [],
						content: '',
						done: false
					},
					'user-2': {
						id: 'user-2',
						role: 'user',
						content: 'second',
						parentId: 'assistant-1',
						childrenIds: ['assistant-2']
					},
					'assistant-1': {
						id: 'assistant-1',
						role: 'assistant',
						parentId: 'user-1',
						childrenIds: ['user-2'],
						content: 'first answer',
						done: true
					},
					'user-1': {
						id: 'user-1',
						role: 'user',
						content: 'first',
						parentId: null,
						childrenIds: ['assistant-1']
					}
				}
			},
			1000
		);

		const merged = chatRuntimeStore.mergeHistory('chat-a', { currentId: null, messages: {} });
		expect(merged.messages['user-1'].childrenIds).toEqual(['assistant-1']);
		expect(merged.messages['assistant-1'].childrenIds).toEqual(['user-2']);
		expect(merged.messages['user-2'].childrenIds).toEqual(['assistant-2']);
		expect(merged.messages['assistant-1'].parentId).toBe('user-1');
		expect(merged.currentId).toBe('assistant-2');
	});

	it('clears one chat without affecting others', () => {
		chatRuntimeStore.applyEvent(completionEvent('chat-a', 'assistant-1', 'A'), 1000);
		chatRuntimeStore.applyEvent(completionEvent('chat-b', 'assistant-2', 'B'), 1000);

		chatRuntimeStore.clearChat('chat-a');

		expect(chatRuntimeStore.getSnapshot('chat-a')).toBeNull();
		expect(chatRuntimeStore.getSnapshot('chat-b')?.messages['assistant-2'].content).toBe('B');
	});

	it('marks a stream ended on done=true without clearing the projection', () => {
		chatRuntimeStore.applyEvent(
			{
				...completionEvent('chat-a', 'assistant-1', 'final'),
				data: { type: 'chat:completion', data: { done: true, content: 'final' } }
			},
			1000
		);

		const snapshot = chatRuntimeStore.getSnapshot('chat-a');
		expect(snapshot).not.toBeNull();
		expect(snapshot?.messages['assistant-1'].content).toBe('final');
		expect(snapshot?.streamEnded).toBe(true);
		expect(snapshot?.active).toBe(false);
		expect(chatRuntimeStore.isAwaitingDurableFinal('chat-a')).toBe(true);
	});

	it('does not clear the projection or active-awareness immediately on chat:active=false', () => {
		chatRuntimeStore.applyEvent(completionEvent('chat-a', 'assistant-1', 'streaming'), 1000);
		chatRuntimeStore.applyEvent(
			{ chat_id: 'chat-a', data: { type: 'chat:active', data: { active: false } } },
			1001
		);

		const snapshot = chatRuntimeStore.getSnapshot('chat-a');
		expect(snapshot).not.toBeNull();
		expect(snapshot?.messages['assistant-1'].content).toBe('streaming');
		expect(snapshot?.streamEnded).toBe(true);
	});

	it('markDurableFinal clears the chat once the only assistant turn is durable', () => {
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
		chatRuntimeStore.applyEvent(
			{
				...completionEvent('chat-a', 'assistant-1', 'final'),
				data: { type: 'chat:completion', data: { done: true, content: 'final' } }
			},
			1001
		);

		chatRuntimeStore.markDurableFinal('chat-a', 'assistant-1');

		expect(chatRuntimeStore.getSnapshot('chat-a')).toBeNull();
		expect(chatRuntimeStore.isAwaitingDurableFinal('chat-a')).toBe(false);
	});

	it('markDurableFinal does not clear another in-flight message in the same chat', () => {
		chatRuntimeStore.applyEvent(
			{
				...completionEvent('chat-a', 'assistant-1', 'first done'),
				data: { type: 'chat:completion', data: { done: true, content: 'first done' } }
			},
			1000
		);
		chatRuntimeStore.applyEvent(completionEvent('chat-a', 'assistant-2', 'still streaming'), 1001);

		chatRuntimeStore.markDurableFinal('chat-a', 'assistant-1');

		const snapshot = chatRuntimeStore.getSnapshot('chat-a');
		expect(snapshot).not.toBeNull();
		expect(snapshot?.messages['assistant-1']).toBeUndefined();
		expect(snapshot?.messages['assistant-2'].content).toBe('still streaming');
	});

	it('markDurableFinal for a non-matching message id is a no-op', () => {
		chatRuntimeStore.applyEvent(completionEvent('chat-a', 'assistant-1', 'streaming'), 1000);
		chatRuntimeStore.markDurableFinal('chat-a', 'does-not-exist');
		expect(chatRuntimeStore.getSnapshot('chat-a')?.messages['assistant-1'].content).toBe('streaming');
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
