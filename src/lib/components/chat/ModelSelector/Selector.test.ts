import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockFetch = vi.fn();
global.fetch = mockFetch;

describe('setChatSessionModel API (T3-932)', () => {
	beforeEach(() => {
		mockFetch.mockReset();
		// Default: successful 200 response
		mockFetch.mockResolvedValue({
			ok: true,
			json: async () => ({
				model: 'anthropic/claude-opus-4.6',
				provider: 'anthropic',
				provider_label: 'Anthropic',
				warning: null
			})
		});
	});

	it('calls the correct endpoint with PUT method and correct body', async () => {
		const { setChatSessionModel } = await import('$lib/apis/agent');

		await setChatSessionModel('test-token', 'chat-abc-123', 'anthropic/claude-opus-4.6');

		expect(mockFetch).toHaveBeenCalledOnce();
		const [url, opts] = mockFetch.mock.calls[0];
		expect(url).toContain('/api/v1/agent/sessions/chat-abc-123/model');
		expect(opts.method).toBe('PUT');
		expect(opts.headers['Authorization']).toBe('Bearer test-token');
		const body = JSON.parse(opts.body);
		expect(body.model).toBe('anthropic/claude-opus-4.6');
	});

	it('returns the model and provider from the response', async () => {
		const { setChatSessionModel } = await import('$lib/apis/agent');

		const result = await setChatSessionModel('tok', 'chat-abc', 'anthropic/claude-opus-4.6');

		expect(result).toEqual({
			model: 'anthropic/claude-opus-4.6',
			provider: 'anthropic',
			provider_label: 'Anthropic',
			warning: null
		});
	});

	it('throws on non-ok response', async () => {
		mockFetch.mockResolvedValueOnce({
			ok: false,
			json: async () => ({ detail: 'Model not found' })
		});
		const { setChatSessionModel } = await import('$lib/apis/agent');

		await expect(setChatSessionModel('tok', 'chat-abc', 'bad/model')).rejects.toEqual(
			'Model not found'
		);
	});

	it('includes optional provider in body when supplied', async () => {
		const { setChatSessionModel } = await import('$lib/apis/agent');

		await setChatSessionModel('tok', 'chat-xyz', 'openai/gpt-4o', 'openai');

		const [, opts] = mockFetch.mock.calls[0];
		const body = JSON.parse(opts.body);
		expect(body.model).toBe('openai/gpt-4o');
		expect(body.provider).toBe('openai');
	});

	it('omits provider from body when not supplied', async () => {
		const { setChatSessionModel } = await import('$lib/apis/agent');

		await setChatSessionModel('tok', 'chat-xyz', 'anthropic/claude-opus-4.6');

		const [, opts] = mockFetch.mock.calls[0];
		const body = JSON.parse(opts.body);
		expect(body).not.toHaveProperty('provider');
	});
});

describe('Selector on-pick guard logic (T3-932)', () => {
	it('does not call setChatSessionModel when model is "myah"', async () => {
		const mockSetChatSessionModel = vi.fn();

		// Mirrors the guard in Selector.svelte onClick
		const onPick = async (chatId: string, value: string) => {
			if (chatId && value && value !== 'myah') {
				await mockSetChatSessionModel('tok', chatId, value);
			}
		};

		await onPick('chat-abc', 'myah');
		expect(mockSetChatSessionModel).not.toHaveBeenCalled();
	});

	it('does not call setChatSessionModel when chatId is empty', async () => {
		const mockSetChatSessionModel = vi.fn();

		const onPick = async (chatId: string, value: string) => {
			if (chatId && value && value !== 'myah') {
				await mockSetChatSessionModel('tok', chatId, value);
			}
		};

		await onPick('', 'anthropic/claude-opus-4.6');
		expect(mockSetChatSessionModel).not.toHaveBeenCalled();
	});

	it('does not call setChatSessionModel when value is empty', async () => {
		const mockSetChatSessionModel = vi.fn();

		const onPick = async (chatId: string, value: string) => {
			if (chatId && value && value !== 'myah') {
				await mockSetChatSessionModel('tok', chatId, value);
			}
		};

		await onPick('chat-abc', '');
		expect(mockSetChatSessionModel).not.toHaveBeenCalled();
	});

	it('calls setChatSessionModel for a real provider model', async () => {
		const mockSetChatSessionModel = vi
			.fn()
			.mockResolvedValue({ model: 'anthropic/claude-opus-4.6' });

		const onPick = async (chatId: string, value: string) => {
			if (chatId && value && value !== 'myah') {
				await mockSetChatSessionModel('tok', chatId, value);
			}
		};

		await onPick('chat-abc', 'anthropic/claude-opus-4.6');
		expect(mockSetChatSessionModel).toHaveBeenCalledWith(
			'tok',
			'chat-abc',
			'anthropic/claude-opus-4.6'
		);
	});

	it('calls setChatSessionModel exactly once per pick', async () => {
		const mockSetChatSessionModel = vi.fn().mockResolvedValue({});

		const onPick = async (chatId: string, value: string) => {
			if (chatId && value && value !== 'myah') {
				await mockSetChatSessionModel('tok', chatId, value);
			}
		};

		await onPick('chat-abc', 'openai/gpt-4o');
		expect(mockSetChatSessionModel).toHaveBeenCalledOnce();
	});
});
