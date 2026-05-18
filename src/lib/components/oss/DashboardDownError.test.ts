/**
 * DashboardDownError.svelte — OSS blocking error when the host-side
 * hermes dashboard process isn't bound to its expected port.
 *
 * Rendered when the OSS probe reports:
 *   hermes_reachable: true (gateway is alive)
 *   plugin_installed: true (Myah plugin is loaded)
 *   dashboard_running: false (dashboard listener absent)
 *
 * Companion of HermesDownError (gateway-down) and PluginMissingError.
 */

import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import { tick } from 'svelte';
import { writable } from 'svelte/store';
import DashboardDownError from './DashboardDownError.svelte';

const baseProbe = {
	hermes_reachable: true,
	hermes_url: 'http://host.docker.internal:8642',
	plugin_installed: true,
	plugin_version: '0.1.0',
	providers_configured: [],
	first_run: false,
	dashboard_running: false,
	dashboard_url: 'http://host.docker.internal:9119'
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

function renderComponent(props: Record<string, unknown>) {
	return render(DashboardDownError, {
		props,
		context: new Map([['i18n', i18nContext]])
	});
}

describe('DashboardDownError', () => {
	it('renders the dashboard URL the platform expected', () => {
		const { getByText } = renderComponent({ probe: baseProbe, onRetry: () => undefined });
		expect(getByText('http://host.docker.internal:9119')).toBeTruthy();
	});

	it('shows the exact command to start the dashboard', () => {
		const { getByText } = renderComponent({ probe: baseProbe, onRetry: () => undefined });
		// Full command including the security flags so users don't get a
		// false-positive "dashboard running but I still can't reach it".
		expect(
			getByText(/hermes dashboard --no-open --insecure --host 0\.0\.0\.0/)
		).toBeTruthy();
	});

	it('calls onRetry when the Try again button is clicked', async () => {
		let calls = 0;
		const { getByRole } = renderComponent({
			probe: baseProbe,
			onRetry: () => {
				calls += 1;
			}
		});
		const btn = getByRole('button', { name: /try again/i });
		btn.click();
		expect(calls).toBe(1);
	});

	it('forwards click to onRetry every time (multiple retries supported)', async () => {
		// Regression guard for the parent-side "Try again does nothing"
		// bug: the dumb component must not swallow subsequent clicks even
		// if the same handler is wired across re-renders. The parent
		// (+layout.svelte) is responsible for actually re-evaluating the
		// state machine after the click — that path is covered by the
		// $state runes conversion documented in:
		// docs/gotchas/2026-05-17-oss-try-again-no-refresh.md
		let calls = 0;
		const { getByRole } = renderComponent({
			probe: baseProbe,
			onRetry: () => {
				calls += 1;
			}
		});
		const btn = getByRole('button', { name: /try again/i });
		await fireEvent.click(btn);
		await fireEvent.click(btn);
		await fireEvent.click(btn);
		expect(calls).toBe(3);
	});

	it('re-renders dashboard_url when probe prop is replaced', async () => {
		// Regression guard for prop-driven reactivity. The component is
		// dumb — every render must reflect the latest `probe.dashboard_url`
		// without caching the initial value. This mirrors how the parent
		// would behave once the $state runes conversion in +layout.svelte
		// causes a new probe object to flow down on retry.
		const { rerender, getByText, queryByText } = render(DashboardDownError, {
			props: { probe: baseProbe, onRetry: () => undefined },
			context: new Map([['i18n', i18nContext]])
		});
		expect(getByText('http://host.docker.internal:9119')).toBeTruthy();

		const updatedProbe = {
			...baseProbe,
			dashboard_url: 'http://host.docker.internal:9999'
		};
		await rerender({ probe: updatedProbe, onRetry: () => undefined });
		await tick();

		expect(queryByText('http://host.docker.internal:9119')).toBeNull();
		expect(getByText('http://host.docker.internal:9999')).toBeTruthy();
	});
});
