// Every process listed here is a standing order — a commitment
// Myah holds on your behalf. These functions are the channel
// through which that commitment is made, inspected, and revoked.

import { MYAH_API_BASE_URL } from '$lib/constants';

// Hermes returns schedule as an object
export interface ProcessSchedule {
	kind: 'cron' | string;
	expr: string; // e.g. "*/15 * * * *"
	display: string; // human-friendly string
}

export interface ProcessRepeat {
	times: number | null;
	completed: number;
}

export interface Process {
	id: string;
	name: string;
	// Hermes returns schedule as an object; create uses a plain string
	schedule: ProcessSchedule | string;
	schedule_display?: string;
	prompt: string;
	deliver?: string;
	skills?: string[];
	skill?: string | null;
	repeat?: ProcessRepeat | boolean | null;
	enabled: boolean;
	state?: 'scheduled' | 'paused' | 'running' | string;
	// Execution history from Hermes
	last_run_at?: string | null;
	next_run_at?: string | null;
	last_status?: 'ok' | 'error' | string | null;
	last_error?: string | null;
	last_run_headline?: string | null;
	has_pending_input?: boolean;
	chat_id?: string;
	created_at?: string | null;
	paused_at?: string | null;
	vite_port?: number | null;
	// ── Adopt Legacy Crons: Myah routing + adoption state (Phase 2/6) ──
	// `origin` is Hermes's native delivery source; `myah` is Myah-owned
	// routing metadata persisted on adoption. `adoptable` + `adoption_state`
	// are derived by the backend normalizer and consumed by the task list.
	origin?: { platform?: string; chat_id?: string; [key: string]: unknown };
	myah?: { chat_id?: string; chat_name?: string; adopted_at?: string; [key: string]: unknown };
	adoptable?: boolean;
	adoption_state?:
		| 'myah_linked'
		| 'legacy_unowned'
		| 'external_origin'
		| 'myah_origin_missing_chat';
}

export interface ProcessRun {
	id: string; // filename stem (timestamp)
	ran_at: string; // ISO timestamp
	status: 'ok' | 'error' | 'silent' | string;
	response: string;
	prompt: string;
}

export interface ProcessCreatePayload {
	name: string;
	schedule: string;
	prompt: string;
	deliver?: string;
	skills?: string[];
	repeat?: boolean;
	enabled?: boolean;
	// chat_id (Bug C-frontend): when supplied, the platform validates
	// ownership and synthesises an `origin` object for the agent so cron
	// output lands back in this chat.  Send only real DB chat IDs —
	// `local:`-prefixed temp IDs are rejected by the platform (matches
	// the link-chat policy).
	chat_id?: string;
}

export interface ProcessUpdatePayload {
	name?: string;
	schedule?: string;
	prompt?: string;
	deliver?: string;
	skills?: string[];
	repeat?: boolean;
	enabled?: boolean;
}

// Helper: extract the cron expression string from schedule regardless of shape
export function getScheduleExpr(p: Process): string {
	if (!p.schedule) return '';
	if (typeof p.schedule === 'string') return p.schedule;
	return p.schedule.expr ?? '';
}

// Helper: get a human-readable schedule string
export function getScheduleDisplay(p: Process): string {
	if (p.schedule_display) return p.schedule_display;
	if (typeof p.schedule === 'object' && p.schedule?.display) return p.schedule.display;
	return getScheduleExpr(p);
}

// ─── CRUD ──────────────────────────────────────────────────────────────────────

export const getProcesses = async (token: string): Promise<Process[]> => {
	// Retry on 503 — the agent container may be temporarily busy (mid-run).
	const maxAttempts = 3;
	const retryDelayMs = 2000;

	for (let attempt = 1; attempt <= maxAttempts; attempt++) {
		let error = null;
		// 501 (OSS mode — processes UI is hosted-only per spec §3
		// Q-oss-cron-processes-ui) is treated as "no processes" so the
		// task list still loads chats. Without this guard the
		// Promise.all([getChatList, getProcesses]) in TaskList rejects
		// on first error and the user sees an empty sidebar.
		let featureUnavailable = false;
		const res = await fetch(`${MYAH_API_BASE_URL}/processes/`, {
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				...(token && { authorization: `Bearer ${token}` })
			}
		})
			.then(async (res) => {
				if (res.status === 501) {
					// OSS mode — endpoint is intentionally not implemented.
					// Swallow silently and return an empty list.
					featureUnavailable = true;
					return [];
				}
				if (res.status === 503 && attempt < maxAttempts) {
					// Container busy — signal a retryable failure
					throw { _retry: true, status: 503 };
				}
				if (!res.ok) throw await res.json();
				return res.json();
			})
			.catch((err) => {
				if (err?._retry) throw err;
				console.error(err);
				error = 'detail' in err ? err.detail : err;
				return null;
			});

		if (featureUnavailable) return [];
		if (res !== null) return res ?? [];
		if (error) throw error;

		// 503 retry path
		await new Promise((r) => setTimeout(r, retryDelayMs));
	}

	return [];
};

export const getProcess = async (token: string, jobId: string): Promise<Process> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/processes/${jobId}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
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
	if (error) throw error;
	return res;
};

export const getProcessRuns = async (
	token: string,
	jobId: string,
	limit = 20
): Promise<ProcessRun[]> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/processes/${jobId}/runs?limit=${limit}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
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
	if (error) throw error;
	return res ?? [];
};

export const createProcess = async (
	token: string,
	payload: ProcessCreatePayload
): Promise<Process> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/processes/`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		},
		body: JSON.stringify(payload)
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
	if (error) throw error;
	return res;
};

export const updateProcess = async (
	token: string,
	jobId: string,
	payload: ProcessUpdatePayload
): Promise<Process> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/processes/${jobId}`, {
		method: 'PATCH',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		},
		body: JSON.stringify(payload)
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
	if (error) throw error;
	return res;
};

export const deleteProcess = async (token: string, jobId: string): Promise<{ ok: boolean }> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/processes/${jobId}`, {
		method: 'DELETE',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
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
	if (error) throw error;
	return res ?? { ok: true };
};

export const linkProcessToChat = async (
	token: string,
	jobId: string,
	chatId: string
): Promise<unknown> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/processes/${jobId}/link-chat`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		},
		body: JSON.stringify({ chat_id: chatId })
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
	if (error) throw error;
	return res;
};

export interface AdoptProcessPayload {
	chat_id?: string;
	backfill_limit?: number;
	preserve_deliver?: boolean;
}

export interface AdoptProcessResult {
	ok: boolean;
	job?: { id: string };
	chat_id: string;
	created_chat?: boolean;
	backfilled?: number;
	skipped_existing?: number;
	truncated?: boolean;
}

// Explicitly adopt a pre-existing Hermes cron into a Myah chat: creates/reuses
// a chat, persists `job.myah.chat_id`, and backfills history. Native external
// delivery (Telegram/Discord/…) is preserved. Throws on non-2xx (e.g. 501 in
// OSS) so the caller can surface it.
export const adoptProcess = async (
	token: string,
	jobId: string,
	payload?: AdoptProcessPayload
): Promise<AdoptProcessResult> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/processes/${jobId}/adopt`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		},
		body: JSON.stringify(payload ?? {})
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
	if (error) throw error;
	return res;
};

export const pauseProcess = async (token: string, jobId: string): Promise<Process> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/processes/${jobId}/pause`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
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
	if (error) throw error;
	return res;
};

export const resumeProcess = async (token: string, jobId: string): Promise<Process> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/processes/${jobId}/resume`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
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
	if (error) throw error;
	return res;
};

export const triggerProcess = async (token: string, jobId: string): Promise<unknown> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/processes/${jobId}/trigger`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
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
	if (error) throw error;
	return res;
};

export const getProcessArtifact = async (token: string, jobId: string): Promise<string> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/processes/${jobId}/artifact`, {
		method: 'GET',
		headers: {
			Accept: 'text/html',
			...(token && { authorization: `Bearer ${token}` })
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.text();
		})
		.catch((err) => {
			error = 'detail' in err ? err.detail : err;
			return null;
		});
	if (error) throw error;
	return res ?? '';
};

export const syncProcessChat = async (token: string, jobId: string): Promise<void> => {
	let error = null;
	await fetch(`${MYAH_API_BASE_URL}/processes/${jobId}/sync-chat`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
		})
		.catch((err) => {
			error = 'detail' in err ? err.detail : err;
		});
	if (error) throw error;
};

export const initArtifactProject = async (
	token: string,
	jobId: string
): Promise<{ ok: boolean }> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/processes/${jobId}/init-artifact`, {
		method: 'POST',
		headers: {
			...(token && { authorization: `Bearer ${token}` })
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
	if (error) throw error;
	return res;
};

export const submitUIAction = async (
	token: string,
	jobId: string,
	actionType: string,
	action: string,
	payload: Record<string, unknown> = {},
	messageId: string = '',
	formId: string = '',
	data: Record<string, unknown> = {}
) => {
	let error = null;

	const res = await fetch(`${MYAH_API_BASE_URL}/processes/${jobId}/ui-action`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			action_type: actionType,
			action,
			payload,
			message_id: messageId,
			form_id: formId,
			data
		})
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

	return res;
};

export const getProcessVitePort = async (token: string, jobId: string): Promise<number | null> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/processes/${jobId}/vite-port`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			...(token && { authorization: `Bearer ${token}` })
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
	if (error) throw error;
	return res?.vite_port ?? null;
};
