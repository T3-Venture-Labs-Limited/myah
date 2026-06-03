import { describe, expect, it, vi } from 'vitest';
import { resolveInflightServerState } from './resolveInflightServerState';

describe('resolveInflightServerState', () => {
	it('uses active run message id while a run is active', async () => {
		const getActiveRun = vi.fn().mockResolvedValue({
			run_id: 'run-1',
			started_at: 1000,
			message_id: 'assistant-active'
		});
		const getChatLiveState = vi.fn().mockResolvedValue({
			chat_id: 'chat-a',
			message_id: 'assistant-active',
			message_content: 'partial',
			output: [],
			status: 'streaming'
		});

		const result = await resolveInflightServerState({
			token: 'token',
			chatId: 'chat-a',
			getActiveRun,
			getChatLiveState,
			knownAssistantMessageId: () => 'assistant-fallback'
		});

		expect(getChatLiveState).toHaveBeenCalledWith('token', 'chat-a', 'assistant-active');
		expect(result).toMatchObject({ run_id: 'run-1', message_id: 'assistant-active' });
	});

	it('falls back to known assistant message id when active_run is gone', async () => {
		const getActiveRun = vi.fn().mockResolvedValue({
			run_id: null,
			started_at: null,
			message_id: null
		});
		const getChatLiveState = vi.fn().mockResolvedValue({
			chat_id: 'chat-a',
			message_id: 'assistant-final',
			message_content: 'final from db fallback',
			output: [{ type: 'text', content: 'final from db fallback' }],
			status: 'settled',
			done: true,
			source: 'db'
		});

		const result = await resolveInflightServerState({
			token: 'token',
			chatId: 'chat-a',
			getActiveRun,
			getChatLiveState,
			knownAssistantMessageId: () => 'assistant-final'
		});

		expect(getChatLiveState).toHaveBeenCalledWith('token', 'chat-a', 'assistant-final');
		expect(result).toMatchObject({
			run_id: null,
			message_id: 'assistant-final',
			message_content: 'final from db fallback',
			status: 'settled',
			source: 'db'
		});
	});

	it('does not guess a message id when an active run has not reported one yet', async () => {
		const getActiveRun = vi.fn().mockResolvedValue({
			run_id: 'run-settling',
			started_at: 1000,
			message_id: null
		});
		const getChatLiveState = vi.fn();

		const result = await resolveInflightServerState({
			token: 'token',
			chatId: 'chat-a',
			getActiveRun,
			getChatLiveState,
			knownAssistantMessageId: () => 'assistant-final'
		});

		expect(result).toBeNull();
		expect(getChatLiveState).not.toHaveBeenCalled();
	});

	it('drops late server responses after stale-chat guard trips', async () => {
		const getActiveRun = vi.fn().mockResolvedValue({
			run_id: null,
			started_at: null,
			message_id: null
		});
		const getChatLiveState = vi.fn();

		const result = await resolveInflightServerState({
			token: 'token',
			chatId: 'chat-a',
			getActiveRun,
			getChatLiveState,
			knownAssistantMessageId: () => 'assistant-final',
			isStale: () => true
		});

		expect(result).toBeNull();
		expect(getChatLiveState).not.toHaveBeenCalled();
	});
});
