import { beforeEach, describe, expect, it, vi } from 'vitest';

import { _resetGetModelsWithProvidersInFlight, getModelsWithProviders } from './index';

const countCalls = (
	fetchMock: { mock: { calls: unknown[][] } },
	urlFragment: string
): number => fetchMock.mock.calls.filter((c) => String(c[0] ?? '').includes(urlFragment)).length;

const makeFetchMock = (overrides: Partial<Record<string, unknown>> = {}) =>
	vi.fn(async (url: string | URL) => {
		const u = String(url);
		if (u.includes('/api/v1/providers/models')) {
			return {
				ok: true,
				json: () => Promise.resolve(overrides.unified ?? [{ id: 'provider-a' }])
			} as Response;
		}
		if (u.includes('/api/models')) {
			return {
				ok: true,
				json: () => Promise.resolve(overrides.base ?? { data: [{ id: 'base-a' }] })
			} as Response;
		}
		return { ok: true, json: () => Promise.resolve({ data: [] }) } as Response;
	});

describe('getModelsWithProviders — request coalescing', () => {
	beforeEach(() => {
		vi.restoreAllMocks();
		_resetGetModelsWithProvidersInFlight();
	});

	it('coalesces 5 concurrent calls (same connections) into 1 underlying fetch pair', async () => {
		const fetchMock = makeFetchMock();
		global.fetch = fetchMock as unknown as typeof fetch;

		const results = await Promise.all([
			getModelsWithProviders('tok', null),
			getModelsWithProviders('tok', null),
			getModelsWithProviders('tok', null),
			getModelsWithProviders('tok', null),
			getModelsWithProviders('tok', null)
		]);

		expect(countCalls(fetchMock, '/api/models')).toBe(1);
		expect(countCalls(fetchMock, '/api/v1/providers/models')).toBe(1);
		expect(results.every((r) => r.length === results[0].length)).toBe(true);
	});

	it('sequential calls (after await) trigger separate fetches — no stale cache', async () => {
		const fetchMock = makeFetchMock();
		global.fetch = fetchMock as unknown as typeof fetch;

		await getModelsWithProviders('tok', null);
		await getModelsWithProviders('tok', null);

		expect(countCalls(fetchMock, '/api/models')).toBe(2);
		expect(countCalls(fetchMock, '/api/v1/providers/models')).toBe(2);
	});

	it('rejects all concurrent callers when underlying fetch rejects, then in-flight clears for retry', async () => {
		const fetchMock = vi
			.fn()
			.mockResolvedValueOnce({ ok: false, json: () => Promise.resolve({ detail: 'boom' }) } as Response)
			.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve([]) } as Response)
			.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ data: [{ id: 'recovered' }] }) } as Response)
			.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve([]) } as Response);
		global.fetch = fetchMock as unknown as typeof fetch;

		const results = await Promise.allSettled([
			getModelsWithProviders('tok', null),
			getModelsWithProviders('tok', null)
		]);
		expect(results.every((r) => r.status === 'rejected')).toBe(true);

		const retry = await getModelsWithProviders('tok', null);
		expect(retry).toBeDefined();
		expect(fetchMock).toHaveBeenCalledTimes(4);
	});

	it('does NOT coalesce calls with different connections', async () => {
		const fetchMock = makeFetchMock();
		global.fetch = fetchMock as unknown as typeof fetch;

		const connsA = null;
		const connsB = {
			OPENAI_API_BASE_URLS: [],
			OPENAI_API_KEYS: [],
			OPENAI_API_CONFIGS: {}
		};

		await Promise.all([
			getModelsWithProviders('tok', connsA),
			getModelsWithProviders('tok', connsB as unknown as object)
		]);

		expect(countCalls(fetchMock, '/api/models')).toBe(2);
	});

	it('coalesces by structural equality of connections (same shape, different reference)', async () => {
		const fetchMock = makeFetchMock();
		global.fetch = fetchMock as unknown as typeof fetch;

		const a = {
			OPENAI_API_BASE_URLS: [],
			OPENAI_API_KEYS: [],
			OPENAI_API_CONFIGS: {}
		};
		const b = {
			OPENAI_API_BASE_URLS: [],
			OPENAI_API_KEYS: [],
			OPENAI_API_CONFIGS: {}
		};

		await Promise.all([
			getModelsWithProviders('tok', a as unknown as object),
			getModelsWithProviders('tok', b as unknown as object)
		]);

		expect(countCalls(fetchMock, '/api/models')).toBe(1);
	});
});
