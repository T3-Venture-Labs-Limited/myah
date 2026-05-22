import { describe, it, expect } from 'vitest';
import {
	parseSelectionKey,
	buildSelectionKey,
	resolveCompositeForLegacyBareId
} from './modelSelection';
import type { ParsedSelectionKey } from './modelSelection';

describe('parseSelectionKey', () => {
	it('returns provider and modelId for composite', () => {
		const result: ParsedSelectionKey = parseSelectionKey('nous::anthropic/claude-opus-4.7');
		expect(result).toEqual({
			provider: 'nous',
			modelId: 'anthropic/claude-opus-4.7'
		});
	});

	it('returns null provider for legacy bare id', () => {
		const result: ParsedSelectionKey = parseSelectionKey('anthropic/claude-opus-4.7');
		expect(result).toEqual({
			provider: null,
			modelId: 'anthropic/claude-opus-4.7'
		});
	});

	it('handles model id that contains slashes', () => {
		const result: ParsedSelectionKey = parseSelectionKey(
			'openrouter::google/gemini-3.1-flash-lite-preview'
		);
		expect(result).toEqual({
			provider: 'openrouter',
			modelId: 'google/gemini-3.1-flash-lite-preview'
		});
	});
});

describe('buildSelectionKey', () => {
	it('concatenates with double colon', () => {
		const result = buildSelectionKey('nous', 'anthropic/claude-opus-4.7');
		expect(result).toBe('nous::anthropic/claude-opus-4.7');
	});
});

describe('resolveCompositeForLegacyBareId', () => {
	it('finds the first matching composite when only bare id given', () => {
		const models = [
			{
				id: 'foo',
				selection_key: 'nous::foo',
				tags: [{ name: 'nous' }]
			},
			{
				id: 'foo',
				selection_key: 'openrouter::foo',
				tags: [{ name: 'openrouter' }]
			}
		];
		const result = resolveCompositeForLegacyBareId('foo', models);
		expect(result).toBe('nous::foo');
	});

	it('prefers activeProviderHint when provided', () => {
		const models = [
			{
				id: 'foo',
				selection_key: 'nous::foo',
				tags: [{ name: 'nous' }]
			},
			{
				id: 'foo',
				selection_key: 'openrouter::foo',
				tags: [{ name: 'openrouter' }]
			}
		];
		const result = resolveCompositeForLegacyBareId('foo', models, 'openrouter');
		expect(result).toBe('openrouter::foo');
	});

	it('returns the bare id unchanged when no match', () => {
		const models: Array<{
			id: string;
			selection_key?: string;
			tags?: Array<{ name: string }>;
		}> = [];
		const result = resolveCompositeForLegacyBareId('unknown', models);
		expect(result).toBe('unknown');
	});
});
