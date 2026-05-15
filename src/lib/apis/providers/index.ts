import { MYAH_BASE_URL } from '$lib/constants';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ModelCapabilities {
	supports_tools?: boolean;
	supports_vision?: boolean;
	supports_reasoning?: boolean;
	context_window?: number;
	max_output_tokens?: number;
	model_family?: string;
}

export interface CuratedModel {
	id: string;
	name: string;
	capabilities?: ModelCapabilities;
}

export interface CatalogEntry {
	id: string;
	display_name: string;
	description: string;
	auth_type: 'api_key' | 'oauth_device_code' | 'oauth_external' | 'external_process';
	env_var: string | null;
	inference_base_url: string;
	default_model: string;
	curated_models: Array<string | CuratedModel>;
	v1_visible: boolean;
	write_type: 'env_var' | 'custom_provider' | 'oauth_codex' | 'oauth_pkce';
	custom_provider?: {
		slug: string;
		base_url: string;
		api_mode: string;
		model_provider_value: string;
	};
	validation?: {
		url: string;
		method: string;
		auth: string;
	};
}

export function normalizeCuratedModels(raw: CatalogEntry['curated_models']): CuratedModel[] {
	return (raw ?? []).map((m) => (typeof m === 'string' ? { id: m, name: m } : m));
}

export interface ProviderStatusRow {
	user_id: string;
	provider_id: string;
	entry_id: string | null;
	connected_at: number;
	last_validated_at: number | null;
	is_valid: boolean;
	key_last_four: string;
	reconnect_needed: boolean;
	reconnect_reason: string | null;
	sync_watermark: number | null;
}

export interface ConnectResult {
	provider_id: string;
	default_model: string;
	key_last_four: string;
}

export interface DeviceAuthSession {
	flow: 'device_code' | 'pkce';
	session_id: string;
	user_code?: string;
	verification_url?: string;
	auth_url?: string;
	interval?: number;
	expires_in?: number;
}

// The Hermes wire vocabulary lives in the typed contract module; the
// platform backend translates ``approved`` -> ``complete`` before this
// response reaches the frontend. The remaining values pass through 1:1.
// See `platform/shared/contract/enums.py::OAuthStatus`.
export type DeviceAuthStatus =
	| 'pending'
	| 'complete'
	| 'denied'
	| 'cancelled'
	| 'expired'
	| 'error';

export interface DeviceAuthPollResult {
	session_id: string;
	status: DeviceAuthStatus;
	error_message?: string | null;
	default_model?: string;
}

export interface ModelListItem {
	id: string;
	name: string;
	tags: { name: string }[];
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export const getCatalog = async (token: string): Promise<Record<string, CatalogEntry>> => {
	let error = null;

	const res = await fetch(`${MYAH_BASE_URL}/api/v1/providers/catalog`, {
		headers: { Authorization: `Bearer ${token}` }
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			console.error('getCatalog error:', err);
			error = 'detail' in err ? err.detail : err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const getStatus = async (token: string): Promise<ProviderStatusRow[]> => {
	let error = null;

	const res = await fetch(`${MYAH_BASE_URL}/api/v1/providers/status`, {
		headers: { Authorization: `Bearer ${token}` }
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			console.error('getStatus error:', err);
			error = 'detail' in err ? err.detail : err;
			return null;
		});

	if (error) throw error;
	return res ?? [];
};

export const connectCredential = async (
	token: string,
	providerId: string,
	apiKey: string,
	label = 'primary'
): Promise<ConnectResult> => {
	let error = null;

	const res = await fetch(`${MYAH_BASE_URL}/api/v1/providers/${providerId}/credential`, {
		method: 'POST',
		headers: {
			Authorization: `Bearer ${token}`,
			'Content-Type': 'application/json'
		},
		body: JSON.stringify({ api_key: apiKey, label })
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			console.error('connectCredential error:', err);
			error = 'detail' in err ? err.detail : err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const disconnectProvider = async (token: string, providerId: string): Promise<void> => {
	let error = null;

	await fetch(`${MYAH_BASE_URL}/api/v1/providers/${providerId}`, {
		method: 'DELETE',
		headers: { Authorization: `Bearer ${token}` }
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			console.error('disconnectProvider error:', err);
			error = 'detail' in err ? err.detail : err;
			return null;
		});

	if (error) throw error;
};

export const startDeviceAuth = async (
	token: string,
	providerId: string
): Promise<DeviceAuthSession> => {
	let error = null;

	const res = await fetch(`${MYAH_BASE_URL}/api/v1/providers/${providerId}/device-auth/start`, {
		method: 'POST',
		headers: { Authorization: `Bearer ${token}` }
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			console.error('startDeviceAuth error:', err);
			error = 'detail' in err ? err.detail : err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const pollDeviceAuth = async (
	token: string,
	providerId: string,
	sessionId: string
): Promise<DeviceAuthPollResult> => {
	let error = null;

	const res = await fetch(`${MYAH_BASE_URL}/api/v1/providers/${providerId}/device-auth/poll`, {
		method: 'POST',
		headers: {
			Authorization: `Bearer ${token}`,
			'Content-Type': 'application/json'
		},
		body: JSON.stringify({ session_id: sessionId })
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			console.error('pollDeviceAuth error:', err);
			error = 'detail' in err ? err.detail : err;
			return null;
		});

	if (error) throw error;
	return res;
};

export const setActiveProvider = async (
	token: string,
	providerId: string,
	modelId?: string
): Promise<void> => {
	let error = null;

	await fetch(`${MYAH_BASE_URL}/api/v1/providers/active`, {
		method: 'POST',
		headers: {
			Authorization: `Bearer ${token}`,
			'Content-Type': 'application/json'
		},
		body: JSON.stringify({ provider_id: providerId, model_id: modelId })
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			console.error('setActiveProvider error:', err);
			error = 'detail' in err ? err.detail : err;
			return null;
		});

	if (error) throw error;
};

export const getModelsUnified = async (token: string): Promise<ModelListItem[]> => {
	let error = null;

	const res = await fetch(`${MYAH_BASE_URL}/api/v1/providers/models`, {
		headers: { Authorization: `Bearer ${token}` }
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			console.error('getModelsUnified error:', err);
			error = 'detail' in err ? err.detail : err;
			return null;
		});

	if (error) throw error;
	return res ?? [];
};
