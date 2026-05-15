import { describe, it, expect } from 'vitest'
import type { CatalogEntry } from '$lib/apis/providers'
import { modelsForTask, hasVision, hasLongContext } from './aux-capabilities'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeEntry(
	id: string,
	models: CatalogEntry['curated_models']
): CatalogEntry {
	return {
		id,
		display_name: id,
		description: '',
		auth_type: 'api_key',
		env_var: null,
		inference_base_url: '',
		default_model: '',
		curated_models: models,
		v1_visible: true,
		write_type: 'env_var',
	}
}

const visionModel = {
	id: 'gpt-4o',
	name: 'GPT-4o',
	capabilities: { supports_vision: true },
}

const textModel = {
	id: 'gpt-4o-mini',
	name: 'GPT-4o Mini',
	capabilities: { supports_vision: false },
}

const noCapModel = {
	id: 'llama-3',
	name: 'Llama 3',
}

// ---------------------------------------------------------------------------
// modelsForTask
// ---------------------------------------------------------------------------

describe('modelsForTask', () => {
	it('test_modelsForTask_no_entry_returns_empty', () => {
		const catalog: CatalogEntry[] = [makeEntry('openai', [visionModel])]
		expect(modelsForTask('unknown-provider', 'vision', catalog)).toEqual([])
	})

	it('test_modelsForTask_vision_filters_to_vision_capable', () => {
		const catalog = [makeEntry('openai', [visionModel, textModel, noCapModel])]
		const result = modelsForTask('openai', 'vision', catalog)
		expect(result).toHaveLength(1)
		expect(result[0].id).toBe('gpt-4o')
	})

	it('test_modelsForTask_non_vision_returns_all_models', () => {
		const catalog = [makeEntry('openai', [visionModel, textModel])]
		const result = modelsForTask('openai', 'compression', catalog)
		expect(result).toHaveLength(2)
	})

	it('test_modelsForTask_missing_capabilities_non_vision_returns_model', () => {
		const catalog = [makeEntry('openai', [noCapModel])]
		const result = modelsForTask('openai', 'title_generation', catalog)
		expect(result).toHaveLength(1)
		expect(result[0].id).toBe('llama-3')
	})

	it('test_modelsForTask_missing_capabilities_vision_returns_empty', () => {
		const catalog = [makeEntry('openai', [noCapModel])]
		const result = modelsForTask('openai', 'vision', catalog)
		expect(result).toHaveLength(0)
	})

	it('test_modelsForTask_old_string_shape_normalized', () => {
		const catalog = [makeEntry('openai', ['some-text-model'])]
		const result = modelsForTask('openai', 'session_search', catalog)
		expect(result).toHaveLength(1)
		expect(result[0].id).toBe('some-text-model')
	})
})

// ---------------------------------------------------------------------------
// hasVision
// ---------------------------------------------------------------------------

describe('hasVision', () => {
	it('test_hasVision_true_when_supports_vision_true', () => {
		expect(hasVision({ supports_vision: true })).toBe(true)
	})

	it('test_hasVision_false_when_undefined_caps', () => {
		expect(hasVision(undefined)).toBe(false)
	})
})

// ---------------------------------------------------------------------------
// hasLongContext
// ---------------------------------------------------------------------------

describe('hasLongContext', () => {
	it('test_hasLongContext_true_when_context_window_at_min', () => {
		expect(hasLongContext({ context_window: 32000 }, 32000)).toBe(true)
	})

	it('test_hasLongContext_false_when_below_min', () => {
		expect(hasLongContext({ context_window: 16000 }, 32000)).toBe(false)
	})
})
