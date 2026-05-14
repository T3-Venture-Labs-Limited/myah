import { MYAH_BASE_URL } from '$lib/constants';

// The petitions we send to the agent's living space — wrapped for the UI's comfort.

type ConfigResponse = Record<string, unknown>;
type PatchBody = Record<string, unknown>;
type SchemaResponse = Record<string, unknown>;
type ReseedInfo = {
	timestamp: string;
	// Older agent containers wrote `files` as a space-separated string.
	// Newer Hermes (≥ post-ISSUE-009 fix) returns a string array. Accept
	// either; the consumer (ReseedToast) normalises before joining.
	files: string[] | string;
	config_version?: string;
	soul_version?: string;
};

export const getAgentConfig = async (token: string): Promise<ConfigResponse> => {
	let error = null;
	const res = await fetch(`${MYAH_BASE_URL}/api/v1/agent/config`, {
		method: 'GET',
		headers: { Authorization: `Bearer ${token}` }
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			console.error(err);
			error = 'detail' in err ? err.detail : err;
			return null;
		});
	if (error) throw error;
	return res;
};

export const patchAgentConfig = async (token: string, body: PatchBody): Promise<ConfigResponse> => {
	let error = null;
	const res = await fetch(`${MYAH_BASE_URL}/api/v1/agent/config`, {
		method: 'PATCH',
		headers: {
			Authorization: `Bearer ${token}`,
			'Content-Type': 'application/json'
		},
		body: JSON.stringify(body)
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			console.error(err);
			error = 'detail' in err ? err.detail : err;
			return null;
		});
	if (error) throw error;
	return res;
};

type SoulResponse = {
	body: string;
	etag: string;
	softWarnChars?: number;
	hardCapChars?: number;
};

export const getAgentSoul = async (token: string): Promise<SoulResponse> => {
	let error = null;
	const res = await fetch(`${MYAH_BASE_URL}/api/v1/agent/soul`, {
		method: 'GET',
		headers: { Authorization: `Bearer ${token}` }
	})
		.then(async (r) => {
			if (!r.ok) throw new Error(`SOUL fetch failed: ${r.status}`);
			const body = await r.text();
			const etag = r.headers.get('ETag') ?? '';
			const softRaw = r.headers.get('X-Soul-Soft-Warn-Chars');
			const hardRaw = r.headers.get('X-Soul-Hard-Cap-Chars');
			return {
				body,
				etag,
				softWarnChars: softRaw ? Number(softRaw) : undefined,
				hardCapChars: hardRaw ? Number(hardRaw) : undefined
			};
		})
		.catch((err) => {
			console.error(err);
			error = err.message;
			return null;
		});
	if (error) throw error;
	return res as SoulResponse;
};

export const putAgentSoul = async (
	token: string,
	body: string,
	ifMatch: string
): Promise<{ etag: string; warning?: string } | { conflict: true; current_body: string }> => {
	const res = await fetch(`${MYAH_BASE_URL}/api/v1/agent/soul`, {
		method: 'PUT',
		headers: {
			Authorization: `Bearer ${token}`,
			'Content-Type': 'text/markdown',
			'If-Match': ifMatch
		},
		body
	});

	if (res.status === 412) {
		const data = await res.json();
		return { conflict: true, current_body: data.current_body ?? '' };
	}
	if (res.status === 413) {
		const err = await res.json().catch(() => ({}));
		console.error('SOUL oversize', err);
		throw err?.detail?.error ?? err?.error ?? 'SOUL content exceeds size limit';
	}
	if (!res.ok) {
		const err = await res.json().catch(() => ({}));
		console.error(err);
		throw 'detail' in err ? err.detail : err;
	}
	const data = await res.json().catch(() => ({} as { warning?: string }));
	return {
		etag: res.headers.get('ETag') ?? '',
		warning: data.warning
	};
};

export const addMcpServer = async (
	token: string,
	config: { name: string; command: string; args: string[]; env?: Record<string, string> }
): Promise<{ ok: boolean }> => {
	let error = null;
	const res = await fetch(`${MYAH_BASE_URL}/api/v1/agent/mcp`, {
		method: 'POST',
		headers: {
			Authorization: `Bearer ${token}`,
			'Content-Type': 'application/json'
		},
		body: JSON.stringify(config)
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			console.error(err);
			error = 'detail' in err ? err.detail : err;
			return null;
		});
	if (error) throw error;
	return res;
};

export const removeMcpServer = async (token: string, name: string): Promise<{ ok: boolean }> => {
	let error = null;
	const res = await fetch(`${MYAH_BASE_URL}/api/v1/agent/mcp/${name}`, {
		method: 'DELETE',
		headers: { Authorization: `Bearer ${token}` }
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			console.error(err);
			error = 'detail' in err ? err.detail : err;
			return null;
		});
	if (error) throw error;
	return res;
};

export const restartAgent = async (
	token: string
): Promise<{ status: string } | { busy: true; busy_sessions: string[] }> => {
	const res = await fetch(`${MYAH_BASE_URL}/api/v1/agent/restart`, {
		method: 'POST',
		headers: { Authorization: `Bearer ${token}` }
	});
	if (res.status === 409) {
		const data = await res.json();
		return { busy: true, busy_sessions: data.busy_sessions ?? [] };
	}
	if (!res.ok) {
		const err = await res.json().catch(() => ({}));
		console.error(err);
		throw 'detail' in err ? err.detail : err;
	}
	return res.json();
};

export const getAgentConfigSchema = async (token: string): Promise<SchemaResponse> => {
	let error = null;
	const res = await fetch(`${MYAH_BASE_URL}/api/v1/agent/config/schema`, {
		method: 'GET',
		headers: { Authorization: `Bearer ${token}` }
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			console.error(err);
			error = 'detail' in err ? err.detail : err;
			return null;
		});
	if (error) throw error;
	return res;
};

export const resetAgentConfigSection = async (
	token: string,
	section: string
): Promise<{ ok: boolean }> => {
	let error = null;
	const res = await fetch(`${MYAH_BASE_URL}/api/v1/agent/config/reset/${section}`, {
		method: 'POST',
		headers: { Authorization: `Bearer ${token}` }
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			console.error(err);
			error = 'detail' in err ? err.detail : err;
			return null;
		});
	if (error) throw error;
	return res;
};

export const getLastReseed = async (token: string): Promise<ReseedInfo | null> => {
	const res = await fetch(`${MYAH_BASE_URL}/api/v1/agent/last-reseed`, {
		method: 'GET',
		headers: { Authorization: `Bearer ${token}` }
	});
	if (res.status === 204) return null;
	if (!res.ok) {
		const err = await res.json().catch(() => ({}));
		console.error(err);
		throw 'detail' in err ? err.detail : err;
	}
	return res.json();
};

export type AuxResolvedEntry = {
	provider: string;
	model: string | null;
	source: string;
};

export const getAuxResolved = async (
	token: string
): Promise<Record<string, AuxResolvedEntry>> => {
	let error = null;
	const res = await fetch(`${MYAH_BASE_URL}/api/v1/agent/config/aux-resolved`, {
		method: 'GET',
		headers: { Authorization: `Bearer ${token}` }
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			console.error(err);
			error = 'detail' in err ? err.detail : err;
			return null;
		});
	if (error) throw error;
	return res ?? {};
};
