/**
 * Single source of truth for provider display metadata across the application.
 *
 * Every chip, badge, and dropdown that renders a provider name or logo
 * resolves through getProviderMeta / getProviderMetaOrFallback — never
 * through ad-hoc string formatting of the raw provider ID.
 *
 * Mirrors the pattern in ./fileTypeRegistry.ts.
 *
 * Implements T3-1050. Spec: docs/superpowers/specs/2026-05-21-provider-logos-registry-design.md
 */

export interface ProviderMeta {
	displayName: string;
	logoUrl: string;
	accentColor?: string;
	/**
	 * True when this provider is a routing aggregator that serves models from
	 * many different model families (e.g. Nous routes to Anthropic, OpenAI,
	 * Moonshot, etc.; OpenRouter does the same). When the user clicks the
	 * aggregator's tab, every row should wear the aggregator's logo — NOT the
	 * underlying model-family logo — so the routing identity is unambiguous.
	 *
	 * For non-aggregator providers (single-family routers like Anthropic
	 * direct, Copilot, xAI, etc.), the logo follows the model family inferred
	 * from the model id's slash-prefix, falling back to the routing tag.
	 */
	isAggregator?: boolean;
}

// The Myah brand logo — used as fallback for providers without a committed
// asset (matches the image-error fallback pattern already used across the
// app at ModelItem.svelte:86, Models.svelte:90, etc.).
export const MYAH_FALLBACK_LOGO = '/favicon.png';

// Fixed 12-color palette for fallback accent colors. Deterministic via hash —
// same provider id always picks the same color, so unknown providers stay
// visually stable across renders.
const FALLBACK_PALETTE = [
	'#6366F1',
	'#8B5CF6',
	'#EC4899',
	'#F43F5E',
	'#F97316',
	'#EAB308',
	'#84CC16',
	'#22C55E',
	'#10B981',
	'#06B6D4',
	'#0EA5E9',
	'#3B82F6'
];

// `openai-codex` deliberately shares its asset with `openai` per user
// instruction (OpenAI Codex uses the OpenAI brand). All other providers
// have their own committed asset.
export const PROVIDER_REGISTRY: Record<string, ProviderMeta> = {
	nous: {
		displayName: 'Nous',
		logoUrl: '/providers/nous.png',
		accentColor: '#7C3AED',
		isAggregator: true
	},
	openrouter: {
		displayName: 'OpenRouter',
		logoUrl: '/providers/openrouter.png',
		accentColor: '#570EC1',
		isAggregator: true
	},
	'ai-gateway': {
		displayName: 'Vercel AI Gateway',
		logoUrl: '/providers/ai-gateway.png',
		accentColor: '#000000',
		isAggregator: true
	},
	huggingface: {
		displayName: 'Hugging Face',
		logoUrl: '/providers/huggingface.png',
		accentColor: '#FFD21E',
		isAggregator: true
	},
	openai: { displayName: 'OpenAI', logoUrl: '/providers/openai.svg', accentColor: '#10A37F' },
	'openai-codex': {
		displayName: 'OpenAI Codex',
		logoUrl: '/providers/openai.svg',
		accentColor: '#10A37F'
	},
	anthropic: {
		displayName: 'Anthropic',
		logoUrl: '/providers/anthropic.svg',
		accentColor: '#D97706'
	},
	google: { displayName: 'Google', logoUrl: '/providers/google.svg', accentColor: '#4285F4' },
	gemini: { displayName: 'Google AI Studio', logoUrl: '/providers/google.svg', accentColor: '#4285F4' },
	xai: { displayName: 'xAI', logoUrl: '/providers/xai.png', accentColor: '#000000' },
	zai: { displayName: 'Z.AI', logoUrl: '/providers/zai.png', accentColor: '#0EA5E9' },
	copilot: {
		displayName: 'GitHub Copilot',
		logoUrl: '/providers/copilot.png',
		accentColor: '#24292F'
	},
	'copilot-acp': {
		displayName: 'GitHub Copilot ACP',
		logoUrl: '/providers/copilot.png',
		accentColor: '#24292F'
	},
	xiaomi: { displayName: 'Xiaomi', logoUrl: '/providers/xiaomi.png', accentColor: '#FF6700' },
	moonshotai: {
		displayName: 'Moonshot AI',
		logoUrl: '/providers/moonshotai.png',
		accentColor: '#1E40AF'
	},
	'kimi-coding': {
		displayName: 'Kimi Coding',
		logoUrl: '/providers/kimi-coding.png',
		accentColor: '#FF6B35'
	},
	'kimi-coding-cn': {
		displayName: 'Kimi (China)',
		logoUrl: '/providers/kimi-coding.png',
		accentColor: '#FF6B35'
	},
	qwen: { displayName: 'Qwen', logoUrl: '/providers/qwen.png', accentColor: '#615CED' },
	'qwen-oauth': {
		displayName: 'Qwen (Portal)',
		logoUrl: '/providers/qwen.png',
		accentColor: '#615CED'
	},
	alibaba: { displayName: 'Qwen Cloud', logoUrl: '/providers/qwen.png', accentColor: '#615CED' },
	deepseek: {
		displayName: 'DeepSeek',
		logoUrl: '/providers/deepseek.png',
		accentColor: '#4D6BFE'
	},
	tencent: { displayName: 'Tencent', logoUrl: '/providers/tencent.png', accentColor: '#0052D9' },
	stepfun: { displayName: 'StepFun', logoUrl: '/providers/stepfun.png', accentColor: '#7C3AED' },
	minimax: { displayName: 'MiniMax', logoUrl: '/providers/minimax.png', accentColor: '#F59E0B' },
	'minimax-cn': {
		displayName: 'MiniMax (China)',
		logoUrl: '/providers/minimax.png',
		accentColor: '#F59E0B'
	},
	'opencode-go': {
		displayName: 'OpenCode Go',
		logoUrl: '/providers/opencode.png',
		accentColor: '#10B981',
		isAggregator: true
	},
	'opencode-zen': {
		displayName: 'OpenCode Zen',
		logoUrl: '/providers/opencode.png',
		accentColor: '#0EA5E9',
		isAggregator: true
	},
	arcee: {
		displayName: 'Arcee AI',
		logoUrl: '/providers/arcee.png',
		accentColor: '#3B82F6'
	},
	kilocode: {
		displayName: 'Kilo Code',
		logoUrl: '/providers/kilocode.png',
		accentColor: '#22C55E',
		isAggregator: true
	}
};

export function getProviderMeta(providerId: string): ProviderMeta | undefined {
	if (!providerId) return undefined;
	return PROVIDER_REGISTRY[providerId];
}

function titleCase(id: string): string {
	return id.replace(/[-_]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function hashIndex(id: string, modulo: number): number {
	let sum = 0;
	for (let i = 0; i < id.length; i++) sum += id.charCodeAt(i);
	return sum % modulo;
}

export function getProviderMetaOrFallback(providerId: string): ProviderMeta {
	const known = getProviderMeta(providerId);
	if (known) return known;
	return {
		displayName: titleCase(providerId),
		logoUrl: MYAH_FALLBACK_LOGO,
		accentColor: FALLBACK_PALETTE[hashIndex(providerId, FALLBACK_PALETTE.length)]
	};
}

/**
 * Pick the right logo provider for a model row.
 *
 * Two-tier strategy:
 *
 * 1. If the routing provider is an aggregator (Nous, OpenRouter, Vercel AI
 *    Gateway, Hugging Face), the LOGO represents the aggregator — not the
 *    underlying model family. Inside the "Nous" tab the user must see Nous
 *    logos on every row, and inside the All tab the Nous variant of
 *    `anthropic/claude-opus-4.7` must be distinguishable from the OpenRouter
 *    variant of the same model id.
 *
 * 2. Otherwise (single-family routers like Anthropic direct, Copilot, xAI,
 *    etc.), the logo represents the MODEL FAMILY inferred from the model id's
 *    slash-prefix (`anthropic/…` → Anthropic, `openai/…` → OpenAI, …) and
 *    falls back to the routing tag when there's no prefix or it's unknown.
 *
 * The tab filter always uses the routing-provider tag, so it stays
 * orthogonal to which logo is shown.
 */
export function resolveLogoProvider(
	modelId: string | undefined,
	routingProviderTag: string | undefined
): string {
	if (routingProviderTag && PROVIDER_REGISTRY[routingProviderTag]?.isAggregator) {
		return routingProviderTag;
	}
	if (modelId) {
		const slashIdx = modelId.indexOf('/');
		if (slashIdx > 0) {
			const prefix = modelId.slice(0, slashIdx).toLowerCase();
			if (PROVIDER_REGISTRY[prefix]) return prefix;
		}
	}
	return routingProviderTag ?? '';
}
