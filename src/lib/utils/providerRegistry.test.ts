/**
 * Tests for the provider registry — single source of truth for provider
 * display metadata (display name, logo URL, accent color).
 *
 * TDD red phase: this file is committed BEFORE providerRegistry.ts exists.
 * Run `npx vitest run src/lib/utils/providerRegistry.test.ts` and confirm
 * every test fails with a module-not-found error. Then implement the module.
 */

import { describe, it, expect } from 'vitest';
import {
	PROVIDER_REGISTRY,
	getProviderMeta,
	getProviderMetaOrFallback,
	resolveLogoProvider,
	MYAH_FALLBACK_LOGO
} from './providerRegistry';

// The full set of provider IDs the live Hermes catalog can emit, per
// T3-1050 spec § Scope. Update if upstream adds/removes providers.
const KNOWN_IDS = [
	'nous',
	'openrouter',
	'openai',
	'openai-codex',
	'anthropic',
	'google',
	'xai',
	'zai',
	'copilot',
	'xiaomi',
	'moonshotai',
	'kimi-coding',
	'qwen',
	'deepseek',
	'tencent',
	'stepfun',
	'minimax'
];

// ── getProviderMeta — known providers ────────────────────────────────────────

describe('getProviderMeta — known providers', () => {
	it('returns OpenRouter meta for "openrouter"', () => {
		const m = getProviderMeta('openrouter');
		expect(m).toBeDefined();
		expect(m!.displayName).toBe('OpenRouter');
		expect(m!.logoUrl).toMatch(/^\/providers\/.+\.(svg|png|webp|avif)$/);
	});

	it('returns Anthropic meta for "anthropic"', () => {
		const m = getProviderMeta('anthropic');
		expect(m).toBeDefined();
		expect(m!.displayName).toBe('Anthropic');
		expect(m!.logoUrl).toBe('/providers/anthropic.svg');
	});

	it('returns OpenAI meta for "openai"', () => {
		const m = getProviderMeta('openai');
		expect(m).toBeDefined();
		expect(m!.displayName).toBe('OpenAI');
		expect(m!.logoUrl).toBe('/providers/openai.svg');
	});
});

// ── getProviderMeta — unknown providers ──────────────────────────────────────

describe('getProviderMeta — unknown providers', () => {
	it('returns undefined for an unknown id', () => {
		expect(getProviderMeta('totally-fake-xyz')).toBeUndefined();
	});

	it('returns undefined for empty string', () => {
		expect(getProviderMeta('')).toBeUndefined();
	});
});

// ── getProviderMetaOrFallback — always returns a ProviderMeta ────────────────

describe('getProviderMetaOrFallback — always returns a ProviderMeta', () => {
	it('returns curated meta for a known id', () => {
		expect(getProviderMetaOrFallback('openrouter').displayName).toBe('OpenRouter');
	});

	it('returns title-cased displayName for unknown ids with hyphens', () => {
		expect(getProviderMetaOrFallback('totally-fake-xyz').displayName).toBe('Totally Fake Xyz');
	});

	it('returns title-cased displayName for unknown ids with underscores', () => {
		expect(getProviderMetaOrFallback('snake_case_id').displayName).toBe('Snake Case Id');
	});

	it('returns the Myah fallback logo for unknown ids', () => {
		expect(getProviderMetaOrFallback('totally-fake-xyz').logoUrl).toBe(MYAH_FALLBACK_LOGO);
		expect(MYAH_FALLBACK_LOGO).toBe('/favicon.png');
	});

	it('returns a deterministic accentColor for the same input', () => {
		const a = getProviderMetaOrFallback('totally-fake-xyz').accentColor;
		const b = getProviderMetaOrFallback('totally-fake-xyz').accentColor;
		expect(a).toBe(b);
		expect(a).toMatch(/^#[0-9A-Fa-f]{6}$/);
	});

	it('returns different accentColors for inputs likely to hash to different buckets', () => {
		// Not a guarantee for ALL inputs (12 buckets ⇒ collisions exist), but two
		// short distinct strings should almost always differ. If this becomes
		// flaky, replace with a "produces a color from the palette" check.
		const a = getProviderMetaOrFallback('aaa').accentColor;
		const b = getProviderMetaOrFallback('zzz').accentColor;
		expect(a).not.toBe(b);
	});
});

// ── PROVIDER_REGISTRY — completeness ─────────────────────────────────────────

describe('PROVIDER_REGISTRY completeness', () => {
	it.each(KNOWN_IDS)('contains an entry for "%s"', (id) => {
		expect(PROVIDER_REGISTRY[id]).toBeDefined();
	});

	it('every entry has a non-empty displayName', () => {
		for (const [id, meta] of Object.entries(PROVIDER_REGISTRY)) {
			expect(meta.displayName.length, `${id}.displayName`).toBeGreaterThan(0);
		}
	});

	it('every entry has a valid logoUrl (curated provider asset OR Myah fallback)', () => {
		const VALID = /^(\/providers\/.+\.(svg|png|webp|avif)|\/favicon\.png)$/;
		for (const [id, meta] of Object.entries(PROVIDER_REGISTRY)) {
			expect(meta.logoUrl, `${id}.logoUrl`).toMatch(VALID);
		}
	});

	it('no entry has displayName === key (curation must be applied)', () => {
		for (const [id, meta] of Object.entries(PROVIDER_REGISTRY)) {
			expect(meta.displayName, `${id} should be curated`).not.toBe(id);
		}
	});
});

// ── Shared logos (user-specified by T3-1050) ─────────────────────────────────

describe('PROVIDER_REGISTRY — shared logos', () => {
	it('openai-codex shares openai\'s logo (OpenAI Codex uses the OpenAI brand)', () => {
		expect(PROVIDER_REGISTRY['openai-codex'].logoUrl).toBe(PROVIDER_REGISTRY['openai'].logoUrl);
	});

	it('moonshotai and kimi-coding have DISTINCT committed logos (they are separate brands)', () => {
		expect(PROVIDER_REGISTRY['kimi-coding'].logoUrl).not.toBe(
			PROVIDER_REGISTRY['moonshotai'].logoUrl
		);
		expect(PROVIDER_REGISTRY['kimi-coding'].logoUrl).toBe('/providers/kimi-coding.png');
		expect(PROVIDER_REGISTRY['moonshotai'].logoUrl).toBe('/providers/moonshotai.png');
	});

	it('opencode-go and opencode-zen share the same logo asset', () => {
		expect(PROVIDER_REGISTRY['opencode-go'].logoUrl).toBe('/providers/opencode.png');
		expect(PROVIDER_REGISTRY['opencode-zen'].logoUrl).toBe('/providers/opencode.png');
	});

	it('newly added providers have their own committed logo assets', () => {
		expect(PROVIDER_REGISTRY['arcee'].logoUrl).toBe('/providers/arcee.png');
		expect(PROVIDER_REGISTRY['huggingface'].logoUrl).toBe('/providers/huggingface.png');
		expect(PROVIDER_REGISTRY['kilocode'].logoUrl).toBe('/providers/kilocode.png');
		expect(PROVIDER_REGISTRY['ai-gateway'].logoUrl).toBe('/providers/ai-gateway.png');
	});
});

// ── All providers now have a committed brand asset ───────────────────────────

describe('PROVIDER_REGISTRY — every provider has a curated logo path', () => {
	it('every entry either has a /providers/ asset OR the Myah fallback (no broken paths)', () => {
		const VALID = /^(\/providers\/.+\.(svg|png|webp|avif)|\/favicon\.png)$/;
		for (const [id, meta] of Object.entries(PROVIDER_REGISTRY)) {
			expect(meta.logoUrl, `${id}.logoUrl`).toMatch(VALID);
		}
	});

	it('stepfun has its own committed logo', () => {
		expect(PROVIDER_REGISTRY['stepfun'].logoUrl).toBe('/providers/stepfun.png');
	});

	it('nous and openrouter are marked as aggregators', () => {
		expect(PROVIDER_REGISTRY['nous'].isAggregator).toBe(true);
		expect(PROVIDER_REGISTRY['openrouter'].isAggregator).toBe(true);
	});

	it('single-family providers are NOT marked as aggregators', () => {
		expect(PROVIDER_REGISTRY['anthropic'].isAggregator).toBeFalsy();
		expect(PROVIDER_REGISTRY['xai'].isAggregator).toBeFalsy();
		expect(PROVIDER_REGISTRY['copilot'].isAggregator).toBeFalsy();
	});

	it('opencode-go and opencode-zen are registered', () => {
		expect(PROVIDER_REGISTRY['opencode-go']).toBeDefined();
		expect(PROVIDER_REGISTRY['opencode-zen']).toBeDefined();
	});
});

// ── resolveLogoProvider: model-family inference ──────────────────────────────

describe('resolveLogoProvider — aggregator routing wins (Nous, OpenRouter, etc.)', () => {
	it('Nous-routed models show Nous logo regardless of model family', () => {
		expect(resolveLogoProvider('anthropic/claude-opus-4.7', 'nous')).toBe('nous');
		expect(resolveLogoProvider('openai/gpt-5.5', 'nous')).toBe('nous');
		expect(resolveLogoProvider('moonshotai/kimi-k2.6', 'nous')).toBe('nous');
	});

	it('OpenRouter-routed models show OpenRouter logo regardless of model family', () => {
		expect(resolveLogoProvider('anthropic/claude-opus-4.7', 'openrouter')).toBe('openrouter');
		expect(resolveLogoProvider('qwen/qwen3.6-plus', 'openrouter')).toBe('openrouter');
	});

	it('huggingface and ai-gateway are also aggregators', () => {
		expect(resolveLogoProvider('anthropic/claude-opus', 'huggingface')).toBe('huggingface');
		expect(resolveLogoProvider('openai/gpt-5.5', 'ai-gateway')).toBe('ai-gateway');
	});

	it('opencode-go, opencode-zen, and kilocode are aggregators (logo wins over model family)', () => {
		expect(resolveLogoProvider('anthropic/claude-opus-4.7', 'opencode-go')).toBe('opencode-go');
		expect(resolveLogoProvider('openai/gpt-5.5', 'opencode-zen')).toBe('opencode-zen');
		expect(resolveLogoProvider('qwen/qwen3-coder', 'kilocode')).toBe('kilocode');
	});

	it('arcee is NOT an aggregator (single-family router)', () => {
		expect(PROVIDER_REGISTRY['arcee'].isAggregator).toBeFalsy();
	});
});

describe('resolveLogoProvider — model-family prefix wins for single-family routers', () => {
	it('anthropic/* via Anthropic-direct resolves to anthropic', () => {
		expect(resolveLogoProvider('anthropic/claude-opus-4.7', 'anthropic')).toBe('anthropic');
	});

	it('openai/* via openai-direct (or copilot) resolves to openai', () => {
		expect(resolveLogoProvider('openai/gpt-5.5', 'openai')).toBe('openai');
		expect(resolveLogoProvider('openai/gpt-5.5', 'copilot')).toBe('openai');
	});

	it('moonshotai/* via kimi-coding resolves to moonshotai', () => {
		expect(resolveLogoProvider('moonshotai/kimi-k2.6', 'kimi-coding')).toBe('moonshotai');
	});

	it('qwen/* via alibaba resolves to qwen', () => {
		expect(resolveLogoProvider('qwen/qwen3.6-plus', 'alibaba')).toBe('qwen');
	});

	it('falls back to routing-provider tag when the prefix is unknown', () => {
		expect(resolveLogoProvider('unknown-vendor/some-model', 'copilot')).toBe('copilot');
	});

	it('falls back to routing-provider tag when the id has no slash prefix', () => {
		expect(resolveLogoProvider('gpt-5.4-codex', 'openai-codex')).toBe('openai-codex');
		expect(resolveLogoProvider('gpt-5.4', 'copilot')).toBe('copilot');
	});

	it('returns the routing tag when model id is empty', () => {
		expect(resolveLogoProvider('', 'nous')).toBe('nous');
		expect(resolveLogoProvider(undefined, 'openrouter')).toBe('openrouter');
	});

	it('returns empty string when both inputs are absent', () => {
		expect(resolveLogoProvider(undefined, undefined)).toBe('');
	});
});
