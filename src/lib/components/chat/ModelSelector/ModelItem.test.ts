import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/svelte';
import { writable } from 'svelte/store';

vi.mock('$lib/stores', () => ({
	mobile: writable(false),
	settings: writable({}),
	user: writable({ role: 'user' }),
	defaultModel: writable('')
}));

vi.mock('$lib/constants', () => ({
	MYAH_API_BASE_URL: '/api/v1',
	MYAH_BASE_URL: ''
}));

vi.mock('svelte-sonner', () => ({
	toast: { success: vi.fn(), error: vi.fn() }
}));

vi.mock('$lib/utils', () => ({
	copyToClipboard: vi.fn(),
	sanitizeResponseContent: (s: string) => s
}));

import ModelItem from './ModelItem.svelte';

const i18n = writable({
	t: (k: string, vars?: Record<string, unknown>) => {
		if (!vars) return k;
		return Object.entries(vars).reduce(
			(acc, [k2, v]) => acc.replace(`{{${k2}}}`, String(v)),
			k
		);
	}
});

const mount = (item: Record<string, unknown>) =>
	render(ModelItem, {
		props: { item, value: '', index: 0, selectedModelIdx: -1 },
		context: new Map([['i18n', i18n]])
	});

// ── Profile image now uses provider logo from registry ───────────────────────

describe('ModelItem — profile image uses aggregator OR model-family logo', () => {
	it('uses Nous logo (aggregator) for any model routed via Nous', () => {
		const { container } = mount({
			value: 'anthropic/claude-opus-4.7',
			label: 'Claude Opus',
			model: { id: 'anthropic/claude-opus-4.7', tags: [{ name: 'nous' }] }
		});
		const img = container.querySelector('img');
		expect(img).not.toBeNull();
		expect(img!.getAttribute('src')).toBe('/providers/nous.png');
	});

	it('uses OpenRouter logo (aggregator) for any model routed via OpenRouter', () => {
		const { container } = mount({
			value: 'anthropic/claude-opus-4.7',
			label: 'Claude Opus',
			model: { id: 'anthropic/claude-opus-4.7', tags: [{ name: 'openrouter' }] }
		});
		const img = container.querySelector('img');
		expect(img!.getAttribute('src')).toBe('/providers/openrouter.png');
	});

	it('uses Anthropic SVG for anthropic/* models routed via Anthropic-direct (non-aggregator)', () => {
		const { container } = mount({
			value: 'anthropic/claude-opus-4.7',
			label: 'Claude Opus',
			model: { id: 'anthropic/claude-opus-4.7', tags: [{ name: 'anthropic' }] }
		});
		const img = container.querySelector('img');
		expect(img!.getAttribute('src')).toBe('/providers/anthropic.svg');
	});

	it('uses the OpenAI SVG for openai/* models routed via copilot (non-aggregator, prefix wins)', () => {
		const { container } = mount({
			value: 'openai/gpt-5.5',
			label: 'GPT-5.5',
			model: { id: 'openai/gpt-5.5', tags: [{ name: 'copilot' }] }
		});
		const img = container.querySelector('img');
		expect(img!.getAttribute('src')).toBe('/providers/openai.svg');
	});

	it('falls back to the routing-provider logo when the model id has no slash prefix', () => {
		const { container } = mount({
			value: 'gpt-5.4',
			label: 'GPT-5.4',
			model: { id: 'gpt-5.4', tags: [{ name: 'openrouter' }] }
		});
		const img = container.querySelector('img');
		expect(img!.getAttribute('src')).toBe('/providers/openrouter.png');
	});

	it('falls back to the Myah favicon when the model has no provider tag and no recognized prefix', () => {
		const { container } = mount({
			value: 'gpt-5.4',
			label: 'GPT-5.4',
			model: { id: 'gpt-5.4' }
		});
		const img = container.querySelector('img');
		expect(img!.getAttribute('src')).toBe('/favicon.png');
	});

	it('falls back to the Myah favicon for an unknown provider id with unknown prefix', () => {
		const { container } = mount({
			value: 'foo/bar-1',
			label: 'foo/bar-1',
			model: { id: 'foo/bar-1', tags: [{ name: 'totally-fake-xyz' }] }
		});
		const img = container.querySelector('img');
		expect(img!.getAttribute('src')).toBe('/favicon.png');
	});

	it('wraps the logo in a white squircle (rounded-lg, light + dark consistent)', () => {
		const { container } = mount({
			value: 'gpt-5.4',
			label: 'GPT-5.4',
			model: { id: 'gpt-5.4', tags: [{ name: 'openrouter' }] }
		});
		const img = container.querySelector('img');
		const wrapper = img!.parentElement!;
		expect(wrapper.className).toContain('rounded-lg');
		expect(wrapper.className).toContain('bg-white');
		expect(wrapper.className).not.toMatch(/dark:bg-(?!white\b)/);
	});

	it('uses eager loading + async decoding for low-latency first paint', () => {
		const { container } = mount({
			value: 'gpt-5.4',
			label: 'GPT-5.4',
			model: { id: 'gpt-5.4', tags: [{ name: 'openrouter' }] }
		});
		const img = container.querySelector('img')!;
		expect(img.getAttribute('loading')).toBe('eager');
		expect(img.getAttribute('decoding')).toBe('async');
	});
});

// ── No chip/provider text is rendered alongside the model name ───────────────

describe('ModelItem — no provider chip beside the model name', () => {
	it('does not render curated provider displayName as a chip beside the model name', () => {
		const { container } = mount({
			value: 'gpt-5.4',
			label: 'GPT-5.4',
			model: { id: 'gpt-5.4', tags: [{ name: 'openrouter' }] }
		});
		expect(container.textContent ?? '').not.toContain('OpenRouter');
		expect(container.textContent ?? '').not.toContain('— openrouter');
	});

	it('only the model label is rendered as visible text alongside the profile image', () => {
		const { container } = mount({
			value: 'claude-opus',
			label: 'Claude Opus',
			model: { id: 'claude-opus', tags: [{ name: 'anthropic' }] }
		});
		expect(container.textContent).toContain('Claude Opus');
		expect(container.textContent).not.toContain('Anthropic');
	});
});
