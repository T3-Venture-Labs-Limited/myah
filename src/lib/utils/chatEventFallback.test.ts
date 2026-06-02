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
					data: { content: 'final answer', done: true, chat_id: 'chat-1', message_id: 'msg-1' }
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
					data: { content: 'wrong', done: true, chat_id: 'other-chat', message_id: 'msg-1' }
				}
			},
			'chat-1',
			chat
		);

		expect(applied).toBe(false);
		expect(chat.history.messages['msg-1'].content).toBe('');
		expect(chat.history.messages['msg-1'].done).toBe(false);
	});

	it('removes stale structured output when durable final event has text but no output', () => {
		const chat = {
			history: {
				currentId: 'msg-1',
				messages: {
					'msg-1': {
						id: 'msg-1',
						role: 'assistant',
						content: '',
						done: false,
						output: [{ type: 'function_call', name: 'terminal' }]
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
					data: { content: 'final answer', done: true, chat_id: 'chat-1', message_id: 'msg-1' }
				}
			},
			'chat-1',
			chat
		);

		expect(applied).toBe(true);
		expect(chat.history.messages['msg-1'].content).toBe('final answer');
		expect(chat.history.messages['msg-1'].done).toBe(true);
		expect('output' in chat.history.messages['msg-1']).toBe(false);
	});

	it('preserves authoritative structured output when durable final event includes output', () => {
		const authoritativeOutput = [{ type: 'message', content: 'final answer' }];
		const chat = {
			history: {
				currentId: 'msg-1',
				messages: {
					'msg-1': {
						id: 'msg-1',
						role: 'assistant',
						content: '',
						done: false,
						output: [{ type: 'function_call', name: 'terminal' }]
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
						chat_id: 'chat-1',
						message_id: 'msg-1',
						output: authoritativeOutput
					}
				}
			},
			'chat-1',
			chat
		);

		expect(applied).toBe(true);
		expect(chat.history.messages['msg-1'].output).toBe(authoritativeOutput);
	});

	it('ignores durable-looking events when inner markers disagree with outer ids', () => {
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
						content: 'wrong',
						done: true,
						chat_id: 'chat-1',
						message_id: 'other-message'
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

	it('ignores ordinary done content events without inner durable fallback markers', () => {
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
				data: { type: 'chat:completion', data: { content: 'ordinary final', done: true } }
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
			{
				type: 'function_call',
				id: 'fc_1',
				name: 'search_files',
				call_id: 'call_1',
				arguments: '{}'
			}
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

	it('applies durable final content to current empty assistant placeholder when event message is missing locally', () => {
		const chat = {
			history: {
				currentId: 'local-placeholder',
				messages: {
					'local-placeholder': {
						id: 'local-placeholder',
						parentId: 'user-1',
						role: 'assistant',
						content: '',
						done: false,
						output: [{ type: 'function_call', name: 'search_files' }]
					}
				}
			}
		};

		const applied = applyDurableFinalMessageEvent(
			{
				chat_id: 'chat-1',
				message_id: 'persisted-final',
				data: {
					type: 'chat:completion',
					data: {
						content: 'final answer',
						done: true,
						message_id: 'persisted-final',
						chat_id: 'chat-1',
						parent_id: 'user-1'
					}
				}
			},
			'chat-1',
			chat
		);

		expect(applied).toBe(true);
		expect(chat.history.messages['local-placeholder'].content).toBe('final answer');
		expect(chat.history.messages['local-placeholder'].done).toBe(true);
		expect(chat.history.messages['local-placeholder'].output).toBeUndefined();
	});

	it('does not apply missing-message durable final content to a placeholder for a different parent', () => {
		const chat = {
			history: {
				currentId: 'local-placeholder',
				messages: {
					'local-placeholder': {
						id: 'local-placeholder',
						parentId: 'user-1',
						role: 'assistant',
						content: '',
						done: false,
						output: [{ type: 'function_call', name: 'search_files' }]
					}
				}
			}
		};

		const applied = applyDurableFinalMessageEvent(
			{
				chat_id: 'chat-1',
				message_id: 'persisted-final',
				data: {
					type: 'chat:completion',
					data: {
						content: 'wrong final answer',
						done: true,
						message_id: 'persisted-final',
						chat_id: 'chat-1',
						parent_id: 'other-user-message'
					}
				}
			},
			'chat-1',
			chat
		);

		expect(applied).toBe(false);
		expect(chat.history.messages['local-placeholder'].content).toBe('');
		expect(chat.history.messages['local-placeholder'].done).toBe(false);
		expect(chat.history.messages['local-placeholder'].output).toEqual([
			{ type: 'function_call', name: 'search_files' }
		]);
	});

	it('returns false when durable final event targets a missing local message without a safe placeholder', () => {
		const chat = {
			history: {
				messages: {}
			}
		};

		const applied = applyDurableFinalMessageEvent(
			{
				chat_id: 'chat-1',
				message_id: 'missing-msg',
				data: {
					type: 'chat:completion',
					data: {
						content: 'final answer',
						done: true,
						message_id: 'missing-msg',
						chat_id: 'chat-1'
					}
				}
			},
			'chat-1',
			chat
		);

		expect(applied).toBe(false);
		expect(chat.history.messages).toEqual({});
	});

	it('copies durable final error payloads onto the reconciled message', () => {
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
						chat_id: 'chat-1',
						error: { content: 'fallback warning' }
					}
				}
			},
			'chat-1',
			chat
		);

		expect(applied).toBe(true);
		expect(chat.history.messages['msg-1'].error).toEqual({ content: 'fallback warning' });
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
