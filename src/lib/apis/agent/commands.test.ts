import { describe, it, expect, vi, beforeEach } from 'vitest';
import { getAgentCommands } from './commands';

describe('getAgentCommands', () => {
	beforeEach(() => {
		vi.restoreAllMocks();
	});

	it('returns parsed .commands array on success', async () => {
		const mockCommands = [
			{
				name: 'help',
				category: 'info',
				description: 'Show help',
				aliases: ['h'],
				args: '',
				bypass: false,
				source: 'builtin'
			},
			{
				name: 'new',
				category: 'session',
				description: 'Start a new session',
				aliases: ['n', 'chat'],
				args: '[title]',
				bypass: false,
				source: 'builtin'
			}
		];

		const mockResponse = {
			commands: mockCommands
		};

		global.fetch = vi.fn().mockResolvedValue({
			ok: true,
			json: () => Promise.resolve(mockResponse)
		}) as any;

		const result = await getAgentCommands('test-token');

		expect(result).toEqual(mockCommands);
		expect(global.fetch).toHaveBeenCalledWith(
			'/api/v1/agent/commands',
			expect.objectContaining({
				method: 'GET',
				headers: {
					'Content-Type': 'application/json',
					Authorization: 'Bearer test-token'
				}
			})
		);
	});

	it('throws error on non-OK response', async () => {
		const errorBody = { detail: 'Unauthorized' };
		global.fetch = vi.fn().mockResolvedValue({
			ok: false,
			json: () => Promise.resolve(errorBody)
		}) as any;

		await expect(getAgentCommands('bad-token')).rejects.toEqual(errorBody);
	});

	it('throws error when fetch throws', async () => {
		const networkError = new Error('Network error');
		global.fetch = vi.fn().mockRejectedValue(networkError) as any;

		await expect(getAgentCommands('test-token')).rejects.toThrow('Network error');
	});
});
