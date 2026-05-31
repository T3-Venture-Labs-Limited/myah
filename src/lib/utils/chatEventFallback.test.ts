import { describe, expect, it, vi } from 'vitest';
import { applyDurableFinalMessageEvent } from './chatEventFallback';

describe('applyDurableFinalMessageEvent', () => {
	it('applies durable final fallback content to the active chat message', () => {
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
				data: {
					type: 'chat:completion',
					data: {
						content: 'final answer',
						done: true,
						message_id: 'msg-1',
						chat_id: 'chat-1'
					}
				}
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
				data: {
					type: 'chat:completion',
					data: {
						content: 'wrong',
						done: true,
						message_id: 'msg-1',
						chat_id: 'other-chat'
					}
				}
			},
			'chat-1',
			chat
		);

		expect(applied).toBe(false);
		expect(chat.history.messages['msg-1'].content).toBe('');
		expect(chat.history.messages['msg-1'].done).toBe(false);
	});

	it('clears stale output-only renderer state when durable final fallback content arrives', () => {
		const chat = {
			history: {
				currentId: 'msg-1',
				messages: {
					'msg-1': {
						id: 'msg-1',
						role: 'assistant',
						content: '',
						done: false,
						output: [
							{ type: 'reasoning', id: 'rs_1', summary: [], encrypted_content: '' },
							{
								type: 'function_call',
								id: 'fc_1',
								name: 'search_files',
								call_id: 'call_1',
								arguments: '{}',
								status: 'completed'
							}
						]
					}
				}
			}
		};

		const applied = applyDurableFinalMessageEvent(
			{
				chat_id: 'chat-1',
				message_id: 'msg-1',
				data: {
					type: 'chat:completion',
					data: {
						content: 'final answer',
						done: true,
						message_id: 'msg-1',
						chat_id: 'chat-1'
					}
				}
			},
			'chat-1',
			chat
		);

		expect(applied).toBe(true);
		expect(chat.history.messages['msg-1'].content).toBe('final answer');
		expect(chat.history.messages['msg-1'].done).toBe(true);
		expect(chat.history.messages['msg-1'].output).toBeUndefined();
	});

	it('preserves authoritative output when durable final fallback includes output', () => {
		const authoritativeOutput = [
			{
				type: 'message',
				id: 'msg-output',
				role: 'assistant',
				content: [{ type: 'output_text', text: 'final answer' }],
				status: 'completed'
			}
		];
		const chat = {
			history: {
				messages: {
					'msg-1': { id: 'msg-1', role: 'assistant', content: '', done: false, output: [] }
				}
			}
		};

		applyDurableFinalMessageEvent(
			{
				chat_id: 'chat-1',
				message_id: 'msg-1',
				data: {
					type: 'chat:completion',
					data: {
						content: 'final answer',
						done: true,
						message_id: 'msg-1',
						chat_id: 'chat-1',
						output: authoritativeOutput
					}
				}
			},
			'chat-1',
			chat
		);

		expect(chat.history.messages['msg-1'].output).toEqual(authoritativeOutput);
	});

	it('ignores ordinary completion events that do not carry durable fallback markers', () => {
		const staleOutput = [
			{ type: 'function_call', id: 'fc_1', name: 'search_files', call_id: 'call_1', arguments: '{}' }
		];
		const chat = {
			history: {
				messages: {
					'msg-1': {
						id: 'msg-1',
						role: 'assistant',
						content: '',
						done: false,
						output: staleOutput
					}
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

		expect(applied).toBe(false);
		expect(chat.history.messages['msg-1'].content).toBe('');
		expect(chat.history.messages['msg-1'].done).toBe(false);
		expect(chat.history.messages['msg-1'].output).toBe(staleOutput);
	});

	it('clears inflight snapshot once for applied durable final fallback events', () => {
		const clearInflightSnapshot = vi.fn();
		const chat = {
			history: {
				messages: {
					'msg-1': { id: 'msg-1', role: 'assistant', content: '', done: false }
				}
			}
		};

		const applied = applyDurableFinalMessageEvent(
			{
				chat_id: 'chat-1',
				message_id: 'msg-1',
				data: {
					type: 'chat:completion',
					data: {
						content: 'final answer',
						done: true,
						message_id: 'msg-1',
						chat_id: 'chat-1'
					}
				}
			},
			'chat-1',
			chat,
			{ clearInflightSnapshot }
		);

		expect(applied).toBe(true);
		expect(clearInflightSnapshot).toHaveBeenCalledOnce();
		expect(clearInflightSnapshot).toHaveBeenCalledWith('chat-1');
	});

	it('does not clear inflight snapshot for local durable final fallback events', () => {
		const clearInflightSnapshot = vi.fn();
		const chat = {
			history: {
				messages: {
					'msg-1': { id: 'msg-1', role: 'assistant', content: '', done: false }
				}
			}
		};

		const applied = applyDurableFinalMessageEvent(
			{
				chat_id: 'local:chat-1',
				message_id: 'msg-1',
				data: {
					type: 'chat:completion',
					data: {
						content: 'final answer',
						done: true,
						message_id: 'msg-1',
						chat_id: 'local:chat-1'
					}
				}
			},
			'local:chat-1',
			chat,
			{ clearInflightSnapshot }
		);

		expect(applied).toBe(true);
		expect(clearInflightSnapshot).not.toHaveBeenCalled();
	});
});
