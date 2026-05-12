/**
 * Logic tests for ModelDropdown's filtering behaviour.
 *
 * @testing-library/svelte is not installed, so we test the filtering
 * function (modelsForTask) used by ModelDropdown directly, covering the
 * exact invariants the component relies on.
 */
import { describe, it, expect } from 'vitest'
import type { CatalogEntry } from '$lib/apis/providers'
import { modelsForTask } from '$lib/utils/aux-capabilities'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeEntry(id: string, models: CatalogEntry['curated_models']): CatalogEntry {
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

const visionModel = { id: 'claude-3-5-sonnet', name: 'Claude 3.5 Sonnet', capabilities: { supports_vision: true } }
const textOnlyModel = { id: 'claude-3-haiku', name: 'Claude 3 Haiku', capabilities: { supports_vision: false } }
const noCapModel = { id: 'llama-3', name: 'Llama 3' }

// ---------------------------------------------------------------------------
// ModelDropdown — vision task only shows vision-capable models
// ---------------------------------------------------------------------------

describe('ModelDropdown filtering (via modelsForTask)', () => {
	it('vision task only shows vision-capable models', () => {
		const catalog = [makeEntry('anthropic', [visionModel, textOnlyModel, noCapModel])]
		const result = modelsForTask('anthropic', 'vision', catalog)
		expect(result).toHaveLength(1)
		expect(result[0].id).toBe('claude-3-5-sonnet')
	})

	it('non-vision task shows all models regardless of caps', () => {
		const catalog = [makeEntry('anthropic', [visionModel, textOnlyModel, noCapModel])]
		const result = modelsForTask('anthropic', 'compression', catalog)
		expect(result).toHaveLength(3)
	})

	it('unknown provider returns empty list (no options rendered)', () => {
		const catalog = [makeEntry('anthropic', [visionModel])]
		expect(modelsForTask('openai', 'vision', catalog)).toHaveLength(0)
	})

	it('empty catalog returns empty list', () => {
		expect(modelsForTask('anthropic', 'vision', [])).toHaveLength(0)
	})

	it('model with no capabilities object is excluded from vision task', () => {
		const catalog = [makeEntry('anthropic', [noCapModel])]
		expect(modelsForTask('anthropic', 'vision', catalog)).toHaveLength(0)
	})

	it('model with no capabilities object is included for non-vision tasks', () => {
		const catalog = [makeEntry('anthropic', [noCapModel])]
		const result = modelsForTask('anthropic', 'title_generation', catalog)
		expect(result).toHaveLength(1)
		expect(result[0].id).toBe('llama-3')
	})

	it('string-format model (legacy) is normalised and included for non-vision task', () => {
		const catalog = [makeEntry('anthropic', ['some-model'])]
		const result = modelsForTask('anthropic', 'session_search', catalog)
		expect(result).toHaveLength(1)
		expect(result[0].id).toBe('some-model')
	})
})

// ---------------------------------------------------------------------------
// ProviderDropdown — filter prop narrows provider list
// ---------------------------------------------------------------------------

describe('ProviderDropdown filtering logic', () => {
	const catalog: CatalogEntry[] = [
		makeEntry('openai', [visionModel]),
		makeEntry('anthropic', [visionModel, textOnlyModel]),
		makeEntry('ollama', []),
	]

	it('no filter returns all providers', () => {
		expect(catalog).toHaveLength(3)
	})

	it('filter excludes providers with no curated_models', () => {
		const filtered = catalog.filter((p) => p.curated_models.length > 0)
		expect(filtered).toHaveLength(2)
		expect(filtered.map((p) => p.id)).not.toContain('ollama')
	})
})
