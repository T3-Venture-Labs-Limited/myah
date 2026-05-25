export interface ParsedSelectionKey {
	provider: string | null;
	modelId: string;
}

export function parseSelectionKey(key: string): ParsedSelectionKey {
	const sep = key.indexOf('::');
	if (sep === -1) {
		return { provider: null, modelId: key };
	}
	return {
		provider: key.slice(0, sep),
		modelId: key.slice(sep + 2)
	};
}

export function buildSelectionKey(providerId: string, modelId: string): string {
	return `${providerId}::${modelId}`;
}

interface ModelLike {
	id: string;
	selection_key?: string;
	tags?: Array<{ name: string }>;
}

export function resolveCompositeForLegacyBareId(
	bareId: string,
	models: ModelLike[],
	activeProviderHint?: string
): string {
	const matches = models.filter((m) => m.id === bareId);
	if (matches.length === 0) {
		return bareId;
	}

	if (activeProviderHint) {
		const preferred = matches.find((m) => {
			const key = m.selection_key ?? _buildKeyFromTags(m.tags);
			return parseSelectionKey(key).provider === activeProviderHint;
		});
		if (preferred) {
			return preferred.selection_key ?? _buildKeyFromTags(preferred.tags);
		}
	}

	const first = matches[0];
	return first.selection_key ?? _buildKeyFromTags(first.tags);
}

function _buildKeyFromTags(tags?: Array<{ name: string }>): string {
	const provider = tags?.[0]?.name ?? '';
	return provider;
}

/**
 * Lookup helper for `$models` lists whose entries may carry a composite
 * `selection_key` ({@link buildSelectionKey}) and/or a bare `id`.
 *
 * Matches composite keys first (the common case after `getModelsWithProviders`
 * runs `ensureSelectionKey` over every model), then falls back to bare `id`
 * matching. Use this in place of inline `$models.find/filter` expressions
 * that compare against a single field — the inline `(m.selection_key ?? m.id)`
 * pattern silently fails bare-id lookups once `selection_key` is always set,
 * which surfaces in production as the user-visible "Model {{modelId}} not
 * found" toast at Chat.svelte:1796 on the first send of any chat whose
 * `selectedModels[0]` was hydrated from a legacy bare-id `default_model`.
 *
 * When multiple rows share the same bare `id`, `activeProviderHint` lets
 * callers prefer a specific provider — mirroring the disambiguation rule
 * in {@link resolveCompositeForLegacyBareId} so the picker label and the
 * dispatch path agree on which row wins.
 */
export function findModelByIdOrSelectionKey<T extends ModelLike>(
	modelId: string,
	models: T[],
	activeProviderHint?: string
): T | undefined {
	if (!modelId) return undefined;

	// Composite picks emitted by the ModelSelector dropdown match here.
	const direct = models.find((m) => m.selection_key === modelId);
	if (direct) return direct;

	// Bare-id fallback for legacy values that survive in $defaultModel or
	// hydrated chat state (pre-T3-1031 settings UI, OSS bootstrap writes,
	// inherited Open WebUI defaults).
	const idMatches = models.filter((m) => m.id === modelId);
	if (idMatches.length === 0) return undefined;
	if (idMatches.length === 1) return idMatches[0];

	if (activeProviderHint) {
		const preferred = idMatches.find((m) => m.tags?.[0]?.name === activeProviderHint);
		if (preferred) return preferred;
	}
	return idMatches[0];
}
