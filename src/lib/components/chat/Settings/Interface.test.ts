import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { writable } from 'svelte/store';

import Interface from './Interface.svelte';
import { config, settings, user } from '$lib/stores';

vi.mock('$lib/apis/users', () => ({
	updateUserInfo: vi.fn().mockResolvedValue({})
}));
vi.mock('$lib/utils', () => ({
	getUserPosition: vi.fn().mockResolvedValue({ latitude: 0, longitude: 0 })
}));
vi.mock('svelte-sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const i18nStore = writable({ t: (key: string) => key });

const renderInterface = (saveSettings = vi.fn()) =>
	render(Interface, {
		props: { saveSettings },
		context: new Map([['i18n', i18nStore]])
	});

describe('Settings Interface panel', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		user.set({ id: 'u1', role: 'admin' } as any);
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		config.set({ default_models: '', features: {} } as any);
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		settings.set({ title: { auto: true }, autoTags: true, params: {} } as any);
		Object.defineProperty(window, 'localStorage', {
			value: { token: 'test-token', getItem: vi.fn(), setItem: vi.fn(), removeItem: vi.fn() },
			configurable: true
		});
	});

	it('exposes a chat title generation toggle in Settings > Interface', async () => {
		renderInterface();

		expect(await screen.findByText('Chat Title Auto-Generation')).toBeInTheDocument();
	});

	it('persists title.auto when the chat title generation toggle changes', async () => {
		const saveSettings = vi.fn();
		renderInterface(saveSettings);

		await screen.findByText('Chat Title Auto-Generation');
		const label = document.getElementById('chat-title-generation-label');
		expect(label).not.toBeNull();
		const toggle = document.querySelector('[aria-labelledby="chat-title-generation-label"]');
		expect(toggle).not.toBeNull();

		await fireEvent.click(toggle as Element);

		await waitFor(() => {
			expect(saveSettings).toHaveBeenCalledWith({ title: { auto: false } });
		});
	});
});
