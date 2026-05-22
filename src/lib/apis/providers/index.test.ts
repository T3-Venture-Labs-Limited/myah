import { describe, it, expect, vi, beforeEach } from 'vitest';
import { getModelsUnified } from './index';

function jsonResponse(status: number, body: unknown = {}) {
	return {
		status,
		ok: status >= 200 && status < 300,
		json: () => Promise.resolve(body)
	};
}

describe('getModelsUnified', () => {
	beforeEach(() => {
		vi.restoreAllMocks();
	});

	it('preserves duplicate model ids', async () => {
		const mockModels = [
			{
				id: 'anthropic/claude-opus-4.7',
				name: 'Claude Opus 4.7',
				tags: [{ name: 'nous' }]
			},
			{
				id: 'openai/gpt-4o',
				name: 'GPT-4o',
				tags: [{ name: 'openrouter' }]
			},
			{
				id: 'anthropic/claude-opus-4.7',
				name: 'Claude Opus 4.7 (OpenRouter)',
				tags: [{ name: 'openrouter' }]
			},
			{
				id: 'anthropic/claude-sonnet-4.6',
				name: 'Claude Sonnet 4.6',
				tags: [{ name: 'nous' }]
			}
		];

		global.fetch = vi.fn().mockResolvedValue(jsonResponse(200, mockModels));

		const result = await getModelsUnified('test-token');

		expect(result.length).toBe(4);
		const opusEntries = result.filter((m) => m.id === 'anthropic/claude-opus-4.7');
		expect(opusEntries.length).toBe(2);
	});

	it('ensures every model has a unique selection_key', async () => {
		const mockModels = [
			{
				id: 'anthropic/claude-opus-4.7',
				name: 'Claude Opus 4.7',
				tags: [{ name: 'nous' }]
			},
			{
				id: 'openai/gpt-4o',
				name: 'GPT-4o',
				tags: [{ name: 'openrouter' }]
			},
			{
				id: 'anthropic/claude-opus-4.7',
				name: 'Claude Opus 4.7 (OpenRouter)',
				tags: [{ name: 'openrouter' }]
			},
			{
				id: 'anthropic/claude-sonnet-4.6',
				name: 'Claude Sonnet 4.6',
				tags: [{ name: 'nous' }]
			}
		];

		global.fetch = vi.fn().mockResolvedValue(jsonResponse(200, mockModels));

		const result = await getModelsUnified('test-token');

		expect(
			result.every((m) => typeof m.selection_key === 'string' && m.selection_key.length > 0)
		).toBe(true);
		expect(new Set(result.map((m) => m.selection_key)).size).toBe(result.length);
	});

	it('selection_key uses provider::model format', async () => {
		const mockModels = [
			{
				id: 'anthropic/claude-opus-4.7',
				name: 'Claude Opus 4.7',
				tags: [{ name: 'nous' }]
			},
			{
				id: 'anthropic/claude-opus-4.7',
				name: 'Claude Opus 4.7 (OpenRouter)',
				tags: [{ name: 'openrouter' }]
			}
		];

		global.fetch = vi.fn().mockResolvedValue(jsonResponse(200, mockModels));

		const result = await getModelsUnified('test-token');

		const nousEntry = result.find((m) => m.tags[0].name === 'nous');
		const openrouterEntry = result.find((m) => m.tags[0].name === 'openrouter');

		expect(nousEntry?.selection_key).toBe('nous::anthropic/claude-opus-4.7');
		expect(openrouterEntry?.selection_key).toBe('openrouter::anthropic/claude-opus-4.7');
	});
});
