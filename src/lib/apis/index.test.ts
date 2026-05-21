import { describe, it, expect, vi, beforeEach } from 'vitest';
import { getModelsWithProviders } from './index';

type ModelEntry = {
	id: string;
	name?: string;
	selection_key?: string;
	tags?: Array<{ name: string }>;
};

function jsonResponse(body: unknown) {
	return {
		ok: true,
		status: 200,
		json: () => Promise.resolve(body)
	};
}

describe('getModelsWithProviders preservation + selection_key', () => {
	beforeEach(() => {
		vi.restoreAllMocks();
	});

	it('preserves duplicates within providerModels list', async () => {
		const duplicateId = 'anthropic/claude-opus-4.7';
		const providerModels = [
			{ id: duplicateId, name: 'Claude Opus 4.7 (Nous)', tags: [{ name: 'nous' }] },
			{ id: duplicateId, name: 'Claude Opus 4.7 (OpenRouter)', tags: [{ name: 'openrouter' }] }
		];
		const baseModels: unknown[] = [];

		global.fetch = vi.fn((url: string) => {
			if (url.includes('/providers/models')) {
				return Promise.resolve(jsonResponse(providerModels));
			}
			if (url.includes('/api/models')) {
				return Promise.resolve(jsonResponse({ data: baseModels }));
			}
			return Promise.reject(new Error(`Unexpected URL: ${url}`));
		}) as unknown as typeof fetch;

		const result = await getModelsWithProviders('test-token');

		expect(result.length).toBe(2);
		expect(
			result.every(
				(m: ModelEntry) => typeof m.selection_key === 'string' && m.selection_key.length > 0
			)
		).toBe(true);
	});

	it('ensures every model has a unique selection_key', async () => {
		const duplicateId = 'anthropic/claude-opus-4.7';
		const providerModels = [
			{ id: duplicateId, name: 'Claude Opus 4.7 (Nous)', tags: [{ name: 'nous' }] },
			{ id: duplicateId, name: 'Claude Opus 4.7 (OpenRouter)', tags: [{ name: 'openrouter' }] }
		];
		const baseModels: unknown[] = [];

		global.fetch = vi.fn((url: string) => {
			if (url.includes('/providers/models')) {
				return Promise.resolve(jsonResponse(providerModels));
			}
			if (url.includes('/api/models')) {
				return Promise.resolve(jsonResponse({ data: baseModels }));
			}
			return Promise.reject(new Error(`Unexpected URL: ${url}`));
		}) as unknown as typeof fetch;

		const result = await getModelsWithProviders('test-token');

		expect(
			result.every(
				(m: ModelEntry) => typeof m.selection_key === 'string' && m.selection_key.length > 0
			)
		).toBe(true);

		const keys = result.map((m: ModelEntry) => m.selection_key);
		expect(new Set(keys).size).toBe(keys.length);
	});
});
