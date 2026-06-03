import { render, screen, waitFor, fireEvent } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$env/dynamic/public', () => ({ env: { PUBLIC_DEPLOYMENT_MODE: 'oss' } }));

import ModelSelector from './ModelSelector.svelte';
import ModelSelectorParentSyncHarness from './ModelSelectorParentSyncHarness.svelte';
import { models, settings, mobile, chatId } from '$lib/stores';
import { providerStatusV2 } from '$lib/stores/providers';

const i18nStore = writable({
	t: (key: string, vars?: Record<string, unknown>) => {
		if (!vars) return key;
		return Object.entries(vars).reduce(
			(text, [name, value]) => text.replace(`{{${name}}}`, String(value)),
			key
		);
	}
});

const testModels = [
	{
		id: 'deepseek/deepseek-v4-flash',
		name: 'OpenRouter Flash',
		selection_key: 'openrouter::deepseek/deepseek-v4-flash',
		tags: [{ name: 'openrouter' }],
		info: { meta: {} },
		connection_type: 'external'
	},
	{
		id: 'claude-sonnet-4',
		name: 'Anthropic Sonnet',
		selection_key: 'anthropic::claude-sonnet-4',
		tags: [{ name: 'anthropic' }],
		info: { meta: {} },
		connection_type: 'external'
	}
];

const renderSelector = (selectedModels: string[]) =>
	render(ModelSelector, {
		props: { selectedModels },
		context: new Map([['i18n', i18nStore]])
	});

const renderParentHarness = () =>
	render(ModelSelectorParentSyncHarness, {
		props: {
			initialSelectedModels: ['openrouter::deepseek/deepseek-v4-flash'],
			nextSelectedModels: ['anthropic::claude-sonnet-4']
		},
		context: new Map([['i18n', i18nStore]])
	});

describe('ModelSelector parent selectedModels synchronization', () => {
	beforeEach(() => {
		models.set(testModels as never);
		settings.set({} as never);
		mobile.set(false);
		chatId.set('');
		providerStatusV2.set([]);
	});

	it('updates the displayed model when the parent changes selectedModels after mount', async () => {
		const { rerender } = renderSelector(['openrouter::deepseek/deepseek-v4-flash']);

		expect(screen.getByRole('button', { name: 'Selected model: OpenRouter Flash' })).toBeTruthy();

		await rerender({ selectedModels: ['anthropic::claude-sonnet-4'] });

		await waitFor(() => {
			expect(screen.getByRole('button', { name: 'Selected model: Anthropic Sonnet' })).toBeTruthy();
		});
		expect(screen.queryByRole('button', { name: 'Selected model: OpenRouter Flash' })).toBeNull();
	});

	it('reflects a bound parent state restore after the child has mounted', async () => {
		renderParentHarness();

		expect(screen.getByTestId('bound-selection').textContent).toBe(
			'openrouter::deepseek/deepseek-v4-flash'
		);
		expect(screen.getByRole('button', { name: 'Selected model: OpenRouter Flash' })).toBeTruthy();

		await fireEvent.click(screen.getByRole('button', { name: 'restore model selection' }));

		await waitFor(() => {
			expect(screen.getByTestId('bound-selection').textContent).toBe('anthropic::claude-sonnet-4');
			expect(screen.getByRole('button', { name: 'Selected model: Anthropic Sonnet' })).toBeTruthy();
		});
		expect(screen.queryByRole('button', { name: 'Selected model: OpenRouter Flash' })).toBeNull();
	});
});
