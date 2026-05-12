import { derived, writable } from 'svelte/store';
import type { CatalogEntry, ProviderStatusRow } from '$lib/apis/providers';
import { getCatalog as apiGetCatalog, getStatus as apiGetStatus } from '$lib/apis/providers';

export interface ProviderStatus {
	providerId: string;
	keyLastFour: string;
	isValid: boolean;
	reconnectNeeded: boolean;
	reconnectReason: string | null;
}

// null = unhydrated; [] = hydrated-empty
export const catalog = writable<Record<string, CatalogEntry> | null>(null);
export const providerStatusV2 = writable<ProviderStatus[] | null>(null);

export const connectedValidProvidersV2 = derived(
	providerStatusV2,
	($s) => ($s ?? []).filter((p) => p.isValid).map((p) => p.providerId)
);

export const reconnectNeeded = derived(
	providerStatusV2,
	($s) => ($s ?? []).filter((p) => p.reconnectNeeded)
);

const CATALOG_CACHE_KEY = 'myah.providerCatalog.v1';
const CATALOG_TTL_MS = 60 * 60 * 1000; // 1 hour

export async function refreshCatalog(token: string): Promise<Record<string, CatalogEntry>> {
	// Warm from localStorage cache first
	try {
		const raw = localStorage.getItem(CATALOG_CACHE_KEY);
		if (raw) {
			const { value, fetchedAt } = JSON.parse(raw);
			if (Date.now() - fetchedAt < CATALOG_TTL_MS) {
				catalog.set(value);
			}
		}
	} catch {
		// ignore
	}

	const fresh = await apiGetCatalog(token);
	catalog.set(fresh);
	try {
		localStorage.setItem(
			CATALOG_CACHE_KEY,
			JSON.stringify({ value: fresh, fetchedAt: Date.now() })
		);
	} catch {
		// ignore
	}
	return fresh;
}

export async function refreshProviderStatus(token: string): Promise<ProviderStatus[]> {
	const rows: ProviderStatusRow[] = await apiGetStatus(token);
	const mapped: ProviderStatus[] = rows.map((r) => ({
		providerId: r.provider_id,
		keyLastFour: r.key_last_four ?? '',
		isValid: r.is_valid,
		reconnectNeeded: r.reconnect_needed,
		reconnectReason: r.reconnect_reason ?? null
	}));
	providerStatusV2.set(mapped);
	return mapped;
}
