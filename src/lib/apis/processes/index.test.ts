/**
 * processes API client — OSS-mode resilience tests.
 *
 * Workstream D Task D.4 (PR #146) made every non-webhook
 * /api/v1/processes/ route return HTTP 501 in OSS mode. That meant
 * ``getProcesses()`` — called from ``TaskList.svelte`` inside a
 * ``Promise.all([getChatList, getProcesses])`` — would throw and
 * reject the whole Promise.all, leaving the sidebar empty even
 * though chats themselves load fine.
 *
 * Fix: treat 501 as "feature unavailable in this deployment" and
 * return an empty array silently. Chats still load, processes just
 * don't appear in the sidebar (matches the locked spec — OSS has no
 * processes UI surface).
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { getProcesses } from './index';

function jsonResponse(status: number, body: unknown = {}) {
	return {
		status,
		ok: status >= 200 && status < 300,
		json: () => Promise.resolve(body)
	};
}

describe('getProcesses — OSS 501 resilience', () => {
	beforeEach(() => {
		vi.restoreAllMocks();
	});

	it('returns an empty array when the endpoint responds 501', async () => {
		// FastAPI 501 body shape — ``{ "detail": "..." }``.
		global.fetch = vi.fn().mockResolvedValue(
			jsonResponse(501, {
				detail:
					'The processes / cron-history UI requires the hosted version of Myah. ' +
					'Manage your cron jobs via `hermes cron list/add/run` on your host, ' +
					'or sign up at https://app.myah.dev for the full UI.'
			})
		) as any;

		const result = await getProcesses('test-token');

		expect(result).toEqual([]);
		expect(global.fetch).toHaveBeenCalledTimes(1);
	});

	it('does NOT retry on 501 — it is a deliberate "not implemented", not a transient failure', async () => {
		const fetchMock = vi.fn().mockResolvedValue(jsonResponse(501, { detail: 'oss' }));
		global.fetch = fetchMock as any;

		await getProcesses('test-token');

		// 501 short-circuits — no 503-style retry loop.
		expect(fetchMock).toHaveBeenCalledTimes(1);
	});

	it('does NOT log a console.error for the 501 path', async () => {
		// 501 is expected behavior in OSS, not a real error worth
		// surfacing. The console.error path is reserved for actual
		// failures (network, 4xx auth, 5xx that's not 503/501).
		const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

		global.fetch = vi.fn().mockResolvedValue(
			jsonResponse(501, { detail: 'oss' })
		) as any;

		await getProcesses('test-token');

		expect(consoleErrorSpy).not.toHaveBeenCalled();
	});

	it('returns the parsed array on a normal 200 success', async () => {
		const sample = [
			{ id: 'job1', name: 'daily summary', schedule: '0 9 * * *', prompt: 'summarize', enabled: true }
		];
		global.fetch = vi.fn().mockResolvedValue(jsonResponse(200, sample)) as any;

		const result = await getProcesses('test-token');

		expect(result).toEqual(sample);
	});

	it('still throws on a non-501 error (e.g. 401 auth failure)', async () => {
		// A real auth error must still bubble up — the OSS 501 path
		// must not mask other failure modes.
		global.fetch = vi.fn().mockResolvedValue(
			jsonResponse(401, { detail: 'unauthorized' })
		) as any;

		await expect(getProcesses('bad-token')).rejects.toBeDefined();
	});
});
