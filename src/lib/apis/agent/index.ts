// Each call here is a question sent to the agent's living space —
// what can you do, what do you know? The answers come back
// as structures we can render and reason about.

import { MYAH_API_BASE_URL } from '$lib/constants';

// ── Types ─────────────────────────────────────────────────────────────────────

// -- Memory types --

export interface MemoryProfile {
	peer_card: string[];
	provisioned: boolean;
}

export interface MemoryConclusion {
	id: string;
	content: string;
	created_at: string | null;
}

export interface MemoryConclusionsResponse {
	conclusions: MemoryConclusion[];
	page: number;
	size: number;
}

export interface MemoryStatus {
	provisioned: boolean;
	workspace_id: string | null;
	pending: number;
	in_progress: number;
	completed: number;
	total_conclusions: number;
}

export interface MemoryRepresentation {
	representation: string;
	provisioned: boolean;
}

export interface MemoryOverview {
	provisioned: boolean;
	user_profile: string[];
	ai_profile: string[];
	representation: string;
	conclusions: MemoryConclusion[];
	pending: number;
	in_progress: number;
	completed: number;
}

export interface AgentTool {
	name: string;
	description: string;
	toolset: string;
	emoji?: string;
}

export interface AgentToolset {
	id: string;
	user_id: string;
	name: string;
	label: string;
	emoji?: string;
	enabled: boolean;
	tools: AgentTool[];
	last_synced_at: number;
}

export interface AgentSkill {
	id: string;
	user_id: string;
	name: string;
	category: string;
	description: string;
	source: string;
	trust: string;
	last_synced_at: number;
}

export interface AgentSkillDetail extends AgentSkill {
	content: string;
}

export interface AgentPlugin {
	id: string;
	user_id: string;
	filename: string;
	name: string;
	description: string;
	content: string;
	last_synced_at: number;
}

export interface AgentMcpServer {
	id: string;
	user_id: string;
	name: string;
	url?: string;
	command?: string;
	args: string[];
	status: string;
	last_synced_at: number;
}

export interface AgentModel {
	model: string;
}

export interface AgentSoul {
	content: string;
}

// ── Agent identity ────────────────────────────────────────────────────────────

export const getAgentModel = async (token: string): Promise<AgentModel> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/model`, {
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
	return res ?? { model: '' };
};

export const updateAgentModel = async (token: string, model: string): Promise<AgentModel> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/model`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
		body: JSON.stringify({ model })
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
	return res ?? { model };
};

export const getChatSessionModel = async (
	token: string,
	sessionId: string
): Promise<{ model: string; provider: string }> => {
	let error = null;

	const res = await fetch(`${MYAH_API_BASE_URL}/agent/sessions/${sessionId}/model`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
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

	return res as { model: string; provider: string };
};

export const setChatSessionModel = async (
	token: string,
	sessionId: string,
	model: string,
	provider?: string
): Promise<{ model: string; provider: string; provider_label: string; warning: string | null }> => {
	let error = null;

	const body: { model: string; provider?: string } = { model };
	if (provider) body.provider = provider;

	const res = await fetch(`${MYAH_API_BASE_URL}/agent/sessions/${sessionId}/model`, {
		method: 'PUT',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify(body)
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

	return res as {
		model: string;
		provider: string;
		provider_label: string;
		warning: string | null;
	};
};

export const getAgentSoul = async (token: string): Promise<AgentSoul> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/soul`, {
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
	return res ?? { content: '' };
};

export const updateAgentSoul = async (token: string, content: string): Promise<AgentSoul> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/soul`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
		body: JSON.stringify({ content })
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
	return res ?? { content };
};

// ── Toolsets ──────────────────────────────────────────────────────────────────

export const getAgentToolsets = async (token: string): Promise<AgentToolset[]> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/toolsets`, {
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
	return res ?? [];
};

export const toggleAgentToolset = async (
	token: string,
	name: string,
	enabled: boolean
): Promise<AgentToolset> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/toolsets/${name}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
		body: JSON.stringify({ enabled })
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

// ── Skills ────────────────────────────────────────────────────────────────────

export const getAgentSkills = async (token: string): Promise<AgentSkill[]> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/skills`, {
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
	return res ?? [];
};

export const getAgentSkillByName = async (
	token: string,
	name: string
): Promise<AgentSkillDetail> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/skills/${name}`, {
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

export const createAgentSkill = async (
	token: string,
	payload: {
		name: string;
		category: string;
		description: string;
		trigger: string;
		content: string;
	}
): Promise<AgentSkillDetail> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/skills`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
		body: JSON.stringify(payload)
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

export const updateAgentSkill = async (
	token: string,
	name: string,
	payload: Partial<{
		name: string;
		category: string;
		description: string;
		trigger: string;
		content: string;
	}>
): Promise<AgentSkillDetail> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/skills/${name}`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
		body: JSON.stringify(payload)
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

export const deleteAgentSkill = async (token: string, name: string): Promise<{ ok: boolean }> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/skills/${name}`, {
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
	return res ?? { ok: true };
};

// ── Plugins ───────────────────────────────────────────────────────────────────

export const getAgentPlugins = async (token: string): Promise<AgentPlugin[]> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/plugins`, {
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
	return res ?? [];
};

export const createAgentPlugin = async (
	token: string,
	payload: { name: string; description: string; content: string }
): Promise<AgentPlugin> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/plugins`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
		body: JSON.stringify(payload)
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

export const updateAgentPlugin = async (
	token: string,
	pluginId: string,
	payload: Partial<{ name: string; description: string; content: string }>
): Promise<AgentPlugin> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/plugins/${pluginId}`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
		body: JSON.stringify(payload)
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

export const deleteAgentPlugin = async (
	token: string,
	pluginId: string
): Promise<{ ok: boolean }> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/plugins/${pluginId}`, {
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
	return res ?? { ok: true };
};

// ── MCP Servers ───────────────────────────────────────────────────────────────

export const getAgentMcpServers = async (token: string): Promise<AgentMcpServer[]> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/mcp-servers`, {
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
	return res ?? [];
};

export const createAgentMcpServer = async (
	token: string,
	payload: {
		name: string;
		url?: string;
		command?: string;
		args?: string[];
		api_key?: string;
	}
): Promise<AgentMcpServer> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/mcp-servers`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
		body: JSON.stringify(payload)
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

export const deleteAgentMcpServer = async (
	token: string,
	name: string
): Promise<{ ok: boolean }> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/mcp-servers/${name}`, {
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
	return res ?? { ok: true };
};

// ── Sync ──────────────────────────────────────────────────────────────────────

export const syncAgentCapabilities = async (token: string): Promise<{ ok: boolean }> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/sync`, {
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
	return res ?? { ok: true };
};

// ── Memory API ────────────────────────────────────────────────────────────────

export const getMemoryOverview = async (
	token: string,
	page: number = 1,
	size: number = 50
): Promise<MemoryOverview> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/memory/overview?page=${page}&size=${size}`, {
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
	return (
		res ?? {
			provisioned: false,
			user_profile: [],
			ai_profile: [],
			representation: '',
			conclusions: [],
			pending: 0,
			in_progress: 0,
			completed: 0
		}
	);
};

export const getMemoryStatus = async (token: string): Promise<MemoryStatus> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/memory/status`, {
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
	return (
		res ?? { provisioned: false, workspace_id: null, pending: 0, in_progress: 0, completed: 0 }
	);
};

export const getMemoryProfile = async (token: string): Promise<MemoryProfile> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/memory/profile`, {
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
	return res ?? { peer_card: [], provisioned: false };
};

export const getMemoryAiProfile = async (token: string): Promise<MemoryProfile> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/memory/ai-profile`, {
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
	return res ?? { peer_card: [], provisioned: false };
};

export const getMemoryRepresentation = async (token: string): Promise<MemoryRepresentation> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/memory/representation`, {
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
	return res ?? { representation: '', provisioned: false };
};

export const getMemoryConclusions = async (
	token: string,
	page: number = 1,
	size: number = 50
): Promise<MemoryConclusionsResponse> => {
	let error = null;
	const res = await fetch(
		`${MYAH_API_BASE_URL}/agent/memory/conclusions?page=${page}&size=${size}`,
		{ headers: { Authorization: `Bearer ${token}` } }
	)
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
	return res ?? { conclusions: [], page, size };
};

export const searchMemoryConclusions = async (
	token: string,
	query: string,
	topK: number = 20
): Promise<MemoryConclusionsResponse> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/memory/conclusions/search`, {
		method: 'POST',
		headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
		body: JSON.stringify({ query, top_k: topK })
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
	return res ?? { conclusions: [], page: 1, size: 0 };
};

export const deleteMemoryConclusion = async (
	token: string,
	conclusionId: string
): Promise<boolean> => {
	let error = null;
	await fetch(`${MYAH_API_BASE_URL}/agent/memory/conclusions/${conclusionId}`, {
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
	return true;
};

// ── Env var (secrets) management ──────────────────────────────────────────────

export interface AgentEnvVar {
	is_set: boolean;
	redacted_value: string | null;
	description: string;
	url: string | null;
	category: string;
	is_password: boolean;
	tools: string[];
}

export const getAgentEnvVars = async (token: string): Promise<Record<string, AgentEnvVar>> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/env`, {
		method: 'GET',
		headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }
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

export const setAgentEnvVar = async (
	token: string,
	key: string,
	value: string
): Promise<{ ok: boolean; key: string }> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/env`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
		body: JSON.stringify({ key, value })
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

export const deleteAgentEnvVar = async (
	token: string,
	key: string
): Promise<{ ok: boolean; key: string }> => {
	let error = null;
	const res = await fetch(`${MYAH_API_BASE_URL}/agent/env/${encodeURIComponent(key)}`, {
		method: 'DELETE',
		headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }
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

export { getAgentCommands } from './commands';
