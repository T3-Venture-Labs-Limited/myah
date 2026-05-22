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
