/**
 * Welcome.svelte — OSS first-run welcome screen (Workstream C Task C.3).
 *
 * Shown when:
 *   - The OSS probe reports `first_run: true`, AND
 *   - hermes_reachable: true (otherwise HermesDownError shows)
 *
 * Click Continue -> the parent layout calls markFirstRunComplete() and
 * routes to the chat list. This component is dumb — it doesn't fetch
 * anything itself; it just renders the probe data + emits onContinue.
 *
 * Spec ref: §8 "Welcome screen"
 */

import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import Welcome from './Welcome.svelte';

const baseProbe = {
	hermes_reachable: true,
	hermes_url: 'http://host.docker.internal:8642',
	plugin_installed: true,
	plugin_version: '1.1.0',
	providers_configured: [],
	first_run: true
};

/** i18n context stub — production app sets this via getContext('i18n'). */
const i18nContext = writable({
	t: (key: string, vars?: Record<string, unknown>) => {
		if (!vars) return key;
		return Object.entries(vars).reduce(
			(acc, [k, v]) => acc.replace(`{{${k}}}`, String(v)),
			key
		);
	}
});

function renderWelcome(props: Record<string, unknown>) {
	return render(Welcome, {
		props,
		context: new Map([['i18n', i18nContext]])
	});
}

describe('Welcome.svelte', () => {
	it('renders the welcome heading', () => {
		const { getByText } = renderWelcome({ probe: baseProbe, onContinue: () => {} });
		expect(getByText(/Welcome to Myah/i)).toBeTruthy();
	});

	it('shows the hermes URL the probe returned', () => {
		const { getByText } = renderWelcome({ probe: baseProbe, onContinue: () => {} });
		expect(getByText(/http:\/\/host\.docker\.internal:8642/)).toBeTruthy();
	});

	it('shows a connected-checkmark cue when hermes_reachable is true', () => {
		const { container } = renderWelcome({ probe: baseProbe, onContinue: () => {} });
		const html = container.innerHTML;
		expect(html.includes('✓') || /connected/i.test(html)).toBe(true);
	});

	it('renders a Continue button', () => {
		const { getByRole } = renderWelcome({ probe: baseProbe, onContinue: () => {} });
		const button = getByRole('button', { name: /continue/i });
		expect(button).toBeTruthy();
	});

	it('calls onContinue when the Continue button is clicked', async () => {
		const onContinue = vi.fn();
		const { getByRole } = renderWelcome({ probe: baseProbe, onContinue });
		await fireEvent.click(getByRole('button', { name: /continue/i }));
		expect(onContinue).toHaveBeenCalledTimes(1);
	});

	it('shows the provider name when providers_configured is non-empty (F3 fix)', () => {
		// VM-testing F3: if the user's hermes already has a provider
		// wired up, the welcome screen acknowledges it via the second ✓ row.
		const { container } = renderWelcome({
			probe: { ...baseProbe, providers_configured: ['openrouter'] },
			onContinue: () => {}
		});
		expect(container.innerHTML).toMatch(/openrouter/i);
	});

	it('does NOT show the provider acknowledgement when providers_configured is empty', () => {
		const { container } = renderWelcome({ probe: baseProbe, onContinue: () => {} });
		// "Provider configured" heading only appears when there's a configured provider.
		expect(container.innerHTML).not.toMatch(/Provider configured/);
	});
});
