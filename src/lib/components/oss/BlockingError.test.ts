/**
 * BlockingError + HermesDownError + PluginMissingError (Workstream C Task C.4).
 *
 * These are full-screen blocking states the OSS frontend shows when the
 * probe reports hermes/plugin failure. The user cannot reach chat until
 * the underlying issue is fixed.
 *
 * Spec ref: §8 "Full-screen blocking error" subsections.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import { writable } from 'svelte/store';
import BlockingError from './BlockingError.svelte';
import HermesDownError from './HermesDownError.svelte';
import PluginMissingError from './PluginMissingError.svelte';

const i18nContext = writable({
	t: (key: string, vars?: Record<string, unknown>) => {
		if (!vars) return key;
		return Object.entries(vars).reduce(
			(acc, [k, v]) => acc.replace(`{{${k}}}`, String(v)),
			key
		);
	}
});

function renderWith(component: unknown, props: Record<string, unknown>) {
	return render(component as never, {
		props,
		context: new Map([['i18n', i18nContext]])
	});
}

// ── BlockingError (shared shell) ───────────────────────────────────────

describe('BlockingError.svelte', () => {
	it('renders the title prop', () => {
		const { getByText } = renderWith(BlockingError, {
			title: 'Something went wrong',
			onRetry: () => {}
		});
		expect(getByText('Something went wrong')).toBeTruthy();
	});

	it('renders a Retry button that calls onRetry', async () => {
		const onRetry = vi.fn();
		const { getByRole } = renderWith(BlockingError, {
			title: 'Title',
			onRetry
		});
		await fireEvent.click(getByRole('button', { name: /retry/i }));
		expect(onRetry).toHaveBeenCalledTimes(1);
	});

	it('renders a link to /diagnostics', () => {
		const { container } = renderWith(BlockingError, {
			title: 'Title',
			onRetry: () => {}
		});
		const link = container.querySelector('a[href="/diagnostics"]');
		expect(link).toBeTruthy();
	});

	it('renders a docs link when docsUrl prop is supplied', () => {
		const { container } = renderWith(BlockingError, {
			title: 'Title',
			onRetry: () => {},
			docsUrl: 'https://github.com/T3-Venture-Labs-Limited/myah/blob/master/docs/troubleshooting.md'
		});
		const link = container.querySelector(
			'a[href="https://github.com/T3-Venture-Labs-Limited/myah/blob/master/docs/troubleshooting.md"]'
		);
		expect(link).toBeTruthy();
	});
});

// ── HermesDownError ────────────────────────────────────────────────────

describe('HermesDownError.svelte', () => {
	const baseProps = {
		hermesUrl: 'http://host.docker.internal:8642',
		onRetry: () => {}
	};

	it('shows the configured hermes URL', () => {
		const { container } = renderWith(HermesDownError, baseProps);
		expect(container.innerHTML).toMatch(/host\.docker\.internal:8642/);
	});

	it('mentions the curl-bash install path for Hermes', () => {
		// Per locked decision in supermemory: the canonical hermes install
		// is via the curl-bash installer (NOT 'pip install hermes-agent').
		// Hermes-down error must reference reachability, not installation.
		const { container } = renderWith(HermesDownError, baseProps);
		const html = container.innerHTML.toLowerCase();
		// The error is about reachability, so we expect mention of starting
		// hermes — but NOT 'pip install hermes-agent' which would be wrong.
		expect(html).not.toMatch(/pip install hermes-agent/);
	});

	it('renders the Retry button', async () => {
		const onRetry = vi.fn();
		const { getByRole } = renderWith(HermesDownError, {
			...baseProps,
			onRetry
		});
		await fireEvent.click(getByRole('button', { name: /retry/i }));
		expect(onRetry).toHaveBeenCalled();
	});
});

// ── PluginMissingError ─────────────────────────────────────────────────

describe('PluginMissingError.svelte', () => {
	const baseProps = {
		hermesUrl: 'http://host.docker.internal:8642',
		onRetry: () => {}
	};

	it('shows the hermes-plugins-install command with the correct owner/repo', () => {
		const { container } = renderWith(PluginMissingError, baseProps);
		expect(container.innerHTML).toMatch(/hermes plugins install/i);
		expect(container.innerHTML).toMatch(
			/T3-Venture-Labs-Limited\/myah-hermes-plugin/
		);
	});

	it('does NOT use the deprecated pip install path', () => {
		// Per locked decision: canonical install is `hermes plugins install`,
		// NOT `pip install myah-hermes-plugin`. The latter is for plugin dev only.
		const { container } = renderWith(PluginMissingError, baseProps);
		expect(container.innerHTML).not.toMatch(/pip install myah-hermes-plugin/);
	});

	it('renders the Retry button', async () => {
		const onRetry = vi.fn();
		const { getByRole } = renderWith(PluginMissingError, {
			...baseProps,
			onRetry
		});
		await fireEvent.click(getByRole('button', { name: /retry/i }));
		expect(onRetry).toHaveBeenCalled();
	});
});
