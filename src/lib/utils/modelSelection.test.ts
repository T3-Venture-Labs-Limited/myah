import { describe, it, expect } from 'vitest';
import {
	parseSelectionKey,
	buildSelectionKey,
	resolveCompositeForLegacyBareId,
	findModelByIdOrSelectionKey,
	selectionMatchesModel,
	resolveInitialSelectedModels
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

// Regression coverage for the production bug where Chat.svelte:1793 (and 6
// sibling sites introduced by PR #209 / commit aa242ac187) used the pattern
// `(m.selection_key ?? m.id) === modelId`. Because apis/index.ts:1018-1022
// `ensureSelectionKey` always sets `m.selection_key` on every model coming
// out of `getModelsWithProviders`, the `?? m.id` fallback is dead code and
// bare ids in `$defaultModel` (legacy data, OSS bootstrap writes, or the
// pre-T3-1031 settings UI) never match — silently producing `undefined` and
// the user-visible toast "Model {{modelId}} not found" on send.
//
// `findModelByIdOrSelectionKey` is the canonical lookup helper that handles
// both formats: composite picks (post-T3-1031 picker output) match directly
// on `selection_key`, while bare ids fall back to `m.id` matching with
// optional provider-hint disambiguation (same rule the picker uses for its
// trigger label resolution via `resolveCompositeForLegacyBareId`).
describe('findModelByIdOrSelectionKey', () => {
	// Models matching the post-ensureSelectionKey shape: every entry has
	// both `id` and `selection_key` populated.
	const models = [
		{ id: 'gpt-5.5', selection_key: 'superdao::gpt-5.5', tags: [{ name: 'superdao' }] },
		{ id: 'gpt-5.5', selection_key: 'openrouter::gpt-5.5', tags: [{ name: 'openrouter' }] },
		{ id: 'claude-opus-4.7', selection_key: 'nous::claude-opus-4.7', tags: [{ name: 'nous' }] }
	];

	it('finds a model by exact composite selection_key', () => {
		const result = findModelByIdOrSelectionKey('nous::claude-opus-4.7', models);
		expect(result?.id).toBe('claude-opus-4.7');
		expect(result?.selection_key).toBe('nous::claude-opus-4.7');
	});

	it('finds a model by bare id when only the legacy id is given (REGRESSION)', () => {
		// This is the production-bug repro: $defaultModel held the bare id
		// 'gpt-5.5', sendMessage's lookup compared it against selection_key
		// only, and the user saw "Model gpt-5.5 not found".
		const result = findModelByIdOrSelectionKey('gpt-5.5', models);
		expect(result).toBeDefined();
		expect(result?.id).toBe('gpt-5.5');
	});

	it('returns the first match for duplicate bare ids without a provider hint', () => {
		// Same behaviour as resolveCompositeForLegacyBareId — picks the
		// first row so picker label and dispatch path agree.
		const result = findModelByIdOrSelectionKey('gpt-5.5', models);
		expect(result?.selection_key).toBe('superdao::gpt-5.5');
	});

	it('uses activeProviderHint to disambiguate duplicate bare ids', () => {
		const result = findModelByIdOrSelectionKey('gpt-5.5', models, 'openrouter');
		expect(result?.selection_key).toBe('openrouter::gpt-5.5');
	});

	it('returns undefined when no model matches', () => {
		const result = findModelByIdOrSelectionKey('nonexistent-model', models);
		expect(result).toBeUndefined();
	});

	it('returns undefined for slash-separated legacy ids (intentional)', () => {
		// `fetch_hermes_default_model` (backend/myah/utils/hermes_web.py:506)
		// emits `${provider}/${model}` — this format is NOT auto-corrected
		// here. The platform-side `user.default_model` migration is the
		// fix for those values; the lookup helper stays strict so the user
		// sees a meaningful "Model not found" rather than silently routing
		// through a wrong provider.
		const result = findModelByIdOrSelectionKey('openai-codex/gpt-5.5', models);
		expect(result).toBeUndefined();
	});

	it('falls back to id matching when selection_key is missing on a model', () => {
		// Some code paths (SettingsModal.svelte:460 `models.set(await getModels())`)
		// populate `$models` without going through `ensureSelectionKey`, so the
		// helper must tolerate `selection_key` being absent.
		const partialModels = [
			{ id: 'mistral-large', tags: [{ name: 'mistral' }] },
			{ id: 'gpt-5.5', selection_key: 'superdao::gpt-5.5', tags: [{ name: 'superdao' }] }
		];
		const result = findModelByIdOrSelectionKey('mistral-large', partialModels);
		expect(result?.id).toBe('mistral-large');
	});
});

describe('selectionMatchesModel', () => {
	const model = {
		id: 'gpt-5.5',
		selection_key: 'openai-codex::gpt-5.5',
		tags: [{ name: 'openai-codex' }]
	};

	it('matches composite picker values against the resolved model row', () => {
		// Regression for chat title generation: Chat.svelte already resolved
		// `openai-codex::gpt-5.5` to this model, but the background-task gate
		// compared the raw selection to `model.id` and omitted title_generation.
		expect(selectionMatchesModel('openai-codex::gpt-5.5', model)).toBe(true);
	});

	it('matches legacy bare id selections', () => {
		expect(selectionMatchesModel('gpt-5.5', model)).toBe(true);
	});

	it('does not match unrelated selections', () => {
		expect(selectionMatchesModel('openrouter::gpt-5.5', model)).toBe(false);
	});
});

describe('resolveInitialSelectedModels', () => {
	const models = [
		{ id: 'gpt-5.4', selection_key: 'copilot::gpt-5.4', tags: [{ name: 'copilot' }] },
		{
			id: 'gpt-5.3-codex-spark',
			selection_key: 'openai-codex::gpt-5.3-codex-spark',
			tags: [{ name: 'openai-codex' }]
		},
		{ id: 'gpt-4o', selection_key: 'openai::gpt-4o', tags: [{ name: 'openai' }] }
	];

	it('prefers current user default provider/model over stale sessionStorage selection', () => {
		expect(
			resolveInitialSelectedModels({
				models,
				defaultModel: { provider: 'openai-codex', model: 'gpt-5.3-codex-spark' },
				sessionSelection: ['copilot::gpt-5.4'],
				adminDefaults: []
			})
		).toEqual(['openai-codex::gpt-5.3-codex-spark']);
	});

	it('preserves persisted existing-chat model selection over current user default', () => {
		expect(
			resolveInitialSelectedModels({
				models,
				defaultModel: { provider: 'openai-codex', model: 'gpt-5.3-codex-spark' },
				persistedChatSelection: ['copilot::gpt-5.4'],
				sessionSelection: null,
				adminDefaults: []
			})
		).toEqual(['copilot::gpt-5.4']);
	});

	it('uses last-used session selection only when there is no user default', () => {
		expect(
			resolveInitialSelectedModels({
				models,
				defaultModel: null,
				sessionSelection: ['copilot::gpt-5.4'],
				adminDefaults: []
			})
		).toEqual(['copilot::gpt-5.4']);
	});

	it('preserves explicit current-page selections even when they differ from default', () => {
		expect(
			resolveInitialSelectedModels({
				models,
				defaultModel: { provider: 'openai-codex', model: 'gpt-5.3-codex-spark' },
				persistedChatSelection: ['copilot::gpt-5.4'],
				explicitSelection: true,
				adminDefaults: []
			})
		).toEqual(['copilot::gpt-5.4']);
	});

	it('only returns firstAvailable when it exists in the model list', () => {
		expect(
			resolveInitialSelectedModels({
				models,
				defaultModel: null,
				sessionSelection: [],
				adminDefaults: [],
				firstAvailable: 'missing::model'
			})
		).toEqual(['']);

		expect(
			resolveInitialSelectedModels({
				models,
				defaultModel: null,
				sessionSelection: [],
				adminDefaults: [],
				firstAvailable: 'openai::gpt-4o'
			})
		).toEqual(['openai::gpt-4o']);
	});
});
