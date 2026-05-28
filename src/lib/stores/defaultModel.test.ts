import { describe, it, expect } from 'vitest';
import { get } from 'svelte/store';
import { defaultModel } from './index';
import type { DefaultModelChoice } from './index';

// Mirrors Hermes upstream's canonical {provider, model} shape — see
// docs/superpowers/specs/2026-05-24-default-model-canonical-format-design.md
describe('defaultModel store', () => {
	it('accepts a DefaultModelChoice object', () => {
		const choice: DefaultModelChoice = { provider: 'openai', model: 'gpt-4o-mini' };
		defaultModel.set(choice);
		expect(get(defaultModel)).toEqual(choice);
	});

	it('accepts null to clear', () => {
		defaultModel.set(null);
		expect(get(defaultModel)).toBeNull();
	});
});
