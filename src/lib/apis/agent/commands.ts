import { MYAH_API_BASE_URL } from '$lib/constants';
import type { AgentCommand } from '$lib/types';

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const isTransientCommandsError = (status?: number, error?: unknown) => {
	if (status && [502, 503, 504].includes(status)) return true;
	if (error && typeof error === 'object' && 'detail' in error) {
		const detail = String((error as { detail?: unknown }).detail ?? '').toLowerCase();
		return detail.includes('dropped the connection') || detail.includes('agent unavailable');
	}
	return false;
};

export const getAgentCommands = async (token: string): Promise<AgentCommand[]> => {
	const maxAttempts = 3;
	let lastError: unknown = null;

	for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
		try {
			const res = await fetch(`${MYAH_API_BASE_URL}/agent/commands`, {
				method: 'GET',
				headers: {
					'Content-Type': 'application/json',
					Authorization: `Bearer ${token}`
				}
			});

			if (res.ok) {
				const data = await res.json();
				return data.commands;
			}

			const error = await res.json();
			lastError = error;
			if (attempt < maxAttempts - 1 && isTransientCommandsError(res.status, error)) {
				await sleep(350 * (attempt + 1));
				continue;
			}
			throw error;
		} catch (err) {
			lastError = err;
			if (attempt < maxAttempts - 1 && isTransientCommandsError(undefined, err)) {
				await sleep(350 * (attempt + 1));
				continue;
			}
			console.error(err);
			throw err;
		}
	}

	throw lastError;
};

export const invalidateAgentCommandsCache = async (token: string): Promise<void> => {
	let error = null;

	await fetch(`${MYAH_API_BASE_URL}/agent/commands/cache`, {
		method: 'DELETE',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			error = 'detail' in err ? err.detail : err;
			return null;
		});

	if (error) {
		throw error;
	}
};
