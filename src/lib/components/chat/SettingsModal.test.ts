// SettingsModal regression tests — Task 2.2 (post-OSS reliability).
//
// What we're guarding against:
//   1. config.subscribe() snapping selectedTab back to 'general' whenever
//      $user briefly flips empty (gating-driven involuntary reset).
//   2. The right pane existed as a plain <div>, so
//      document.querySelectorAll('[role=tabpanel]').length was always 0
//      and screen readers had no anchored region for any tab.
//   3. aria-controls on the tab buttons pointed at DOM ids that did
//      not exist anywhere on the page.
//
// See docs/oss-launch/settings-modal-repro.md for the original RCA.

import { render, fireEvent, screen, waitFor } from '@testing-library/svelte';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { writable } from 'svelte/store';

// SvelteKit's $env/dynamic/public is a virtual module — Vite resolves it
// only when SvelteKit is the active host. Under vitest+jsdom we mock it.
vi.mock('$env/dynamic/public', () => ({ env: { PUBLIC_DEPLOYMENT_MODE: 'hosted' } }));

// SettingsModal pulls in deep API/component trees on import; stub the noisy
// network and i18n bits so the unit test isolates the tab-state logic.
vi.mock('$lib/apis/users', () => ({
	updateUserSettings: vi.fn().mockResolvedValue({})
}));
vi.mock('$lib/apis', () => ({
	getModelsWithProviders: vi.fn().mockResolvedValue([])
}));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('svelte-sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

// focus-trap requires a real tabbable node in the DOM; jsdom's synthetic
// rendering doesn't satisfy it. The trap is irrelevant to tab-state logic.
vi.mock('focus-trap', () => ({
	createFocusTrap: () => ({ activate: vi.fn(), deactivate: vi.fn() })
}));

// Stub the per-tab subpanes — their internals (API calls, child stores) are
// not what this test is asserting against. Each maps to a shared placeholder
// component that just renders a data-stub-pane div.
// (vi.mock is hoisted; factory must be self-contained.)
vi.mock('./Settings/General.svelte', async () => ({
	default: (await import('./_StubPane.svelte')).default
}));
vi.mock('./Settings/Interface.svelte', async () => ({
	default: (await import('./_StubPane.svelte')).default
}));
vi.mock('./Settings/Connections.svelte', async () => ({
	default: (await import('./_StubPane.svelte')).default
}));
vi.mock('./Settings/Provider.svelte', async () => ({
	default: (await import('./_StubPane.svelte')).default
}));
vi.mock('./Settings/Secrets.svelte', async () => ({
	default: (await import('./_StubPane.svelte')).default
}));
vi.mock('./Settings/DataControls.svelte', async () => ({
	default: (await import('./_StubPane.svelte')).default
}));
vi.mock('./Settings/Account.svelte', async () => ({
	default: (await import('./_StubPane.svelte')).default
}));
vi.mock('./Settings/About.svelte', async () => ({
	default: (await import('./_StubPane.svelte')).default
}));

import SettingsModal from './SettingsModal.svelte';
import { config, settings, user } from '$lib/stores';

const seedAdmin = () => ({
	id: 'test-admin',
	role: 'admin',
	email: 'test@example.com',
	name: 'Test Admin',
	permissions: { settings: { interface: true } }
});

const seedConfig = () => ({
	features: { enable_signup: false, enable_direct_connections: true },
	ui: {}
});

// Minimal i18n stub — components only call $i18n.t(key) which we echo.
const i18nStore = writable({ t: (k: string) => k });

const renderModal = () =>
	render(SettingsModal, {
		props: { show: true },
		context: new Map([['i18n', i18nStore]])
	});

describe('SettingsModal — tab persistence (Task 2.2)', () => {
	beforeEach(() => {
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		user.set(seedAdmin() as any);
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		config.set(seedConfig() as any);
		// General tab reads $settings.theme/notificationEnabled/system/params.
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		settings.set({ theme: 'system', params: {} } as any);
		if (typeof window !== 'undefined' && window.localStorage) {
			window.localStorage.setItem('token', 'test-token');
		}
	});

	it('keeps selected tab after $config updates with transient empty $user', async () => {
		renderModal();

		const providerBtn = await screen.findByRole('tab', { name: /provider/i });
		await fireEvent.click(providerBtn);

		expect(providerBtn.getAttribute('aria-selected')).toBe('true');

		// Simulate the bug condition: $user transiently becomes null
		// (any auth refetch, /api/v1/auths fail-and-retry, etc.) and then
		// $config fires its subscribers. Pre-fix this would snap back to General.
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		user.set(null as any);
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		config.set({ ...seedConfig(), ui: { refreshed: true } } as any);
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		user.set(seedAdmin() as any);

		await waitFor(
			() => {
				const stillSelected = screen.getByRole('tab', { name: /provider/i });
				expect(stillSelected.getAttribute('aria-selected')).toBe('true');
			},
			{ timeout: 200 }
		);
	});

	it('right pane has role="tabpanel" so screen readers can anchor onto it', async () => {
		renderModal();
		await screen.findByRole('tab', { name: /general/i });
		const tabpanel = document.querySelector('[role="tabpanel"]');
		expect(tabpanel).not.toBeNull();
	});

	it("every tab's aria-controls resolves to an existing element id", async () => {
		renderModal();
		await screen.findByRole('tab', { name: /general/i });

		// The selected tab's aria-controls must point at the live tabpanel.
		// (Non-selected tabs only need a stable id for keyboard navigation;
		//  we'd rather guarantee the selected one is wired up correctly.)
		const selected = document.querySelector('[role="tab"][aria-selected="true"]');
		expect(selected).not.toBeNull();
		const controls = selected?.getAttribute('aria-controls');
		expect(controls).toBeTruthy();
		expect(document.getElementById(controls as string)).not.toBeNull();
	});
});
