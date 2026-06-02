import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, cleanup } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import { artifactPaneOpen, temporaryChatEnabled, user } from '$lib/stores';
import Harness from './__test__/NavbarHarness.svelte';

vi.mock('@sentry/sveltekit', () => ({
	init: vi.fn(),
	handleErrorWithSentry: (handler: unknown) => handler,
	replayIntegration: vi.fn(),
	browserTracingIntegration: vi.fn(),
	feedbackIntegration: vi.fn(),
	captureException: vi.fn(),
	captureMessage: vi.fn(),
	setUser: vi.fn(),
	setTag: vi.fn(),
	withScope: vi.fn((fn) => fn({ setTag: vi.fn(), setContext: vi.fn() }))
}));

vi.mock('$app/navigation', () => ({
	goto: vi.fn()
}));

vi.mock('$app/stores', () => ({
	page: writable({ url: new URL('http://localhost/') })
}));

vi.mock('../chat/ModelSelector.svelte', async () => {
	const Stub = (await import('./__test__/ModelSelectorStub.svelte')).default;
	return { default: Stub };
});

vi.mock('../common/Tooltip.svelte', async () => {
	const Stub = (await import('./__test__/TooltipStub.svelte')).default;
	return { default: Stub };
});

describe('Navbar files button', () => {
	afterEach(() => {
		cleanup();
		artifactPaneOpen.set(false);
		temporaryChatEnabled.set(false);
		user.set(undefined);
	});

	it('shows the Files toggle before a chat has its first message', async () => {
		user.set({
			id: 'u',
			email: 'e2e@test.local',
			name: 'E2E Test User',
			profile_image_url: '',
			role: 'user',
			permissions: { chat: { temporary: true } }
		} as any);
		artifactPaneOpen.set(false);
		temporaryChatEnabled.set(false);

		render(Harness, { props: { chat: null, history: { currentId: null }, selectedModels: [] } });

		expect(screen.getByTestId('chat-files-button')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Files' })).toHaveAttribute('aria-pressed', 'false');
	});
});
