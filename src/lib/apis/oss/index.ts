// OSS first-run UX client. Talks to /api/v1/oss/probe and
// /api/v1/oss/first_run_complete in the FastAPI backend.
//
// The probe is called by the root layout on every page load — see
// `src/routes/+layout.svelte`. The response gates which screen the
// user sees:
//   * hermes_reachable + first_run    -> Welcome.svelte
//   * hermes_reachable + !first_run   -> normal chat list
//   * !hermes_reachable               -> HermesDownError.svelte
//   * hermes_reachable + !plugin      -> PluginMissingError.svelte
//
// Backend reference: platform-oss/backend/myah/routers/oss.py
// Spec reference: docs/superpowers/specs/2026-05-13-myah-oss-v0.1.0-launch-design.md §8

import { MYAH_API_BASE_URL } from '$lib/constants';

export interface OssProbe {
	hermes_reachable: boolean;
	hermes_url: string;
	plugin_installed: boolean;
	plugin_version: string | null;
	providers_configured: string[];
	first_run: boolean;
	dashboard_running: boolean;
	dashboard_url: string;
}

export interface OssDiagnostics extends OssProbe {
	agent_ports: {
		gateway: number;
		standalone: number;
		web: number;
	};
	platform_port_binding: string;
	oss_version: string;
}

/**
 * Probe the host-side Hermes Agent + its Myah plugin. Always returns
 * an OssProbe shape — the backend treats every state (hermes down,
 * plugin missing) as a 200 with structured fields, so callers don't
 * need to catch network exceptions for happy paths.
 *
 * Throws only on true infrastructure failures (the backend itself is
 * down, or the JSON shape is malformed) — those crash the loading
 * indicator into the generic blocking error.
 */
export const getOssProbe = async (): Promise<OssProbe> => {
	let error: string | null = null;

	const res = await fetch(`${MYAH_API_BASE_URL}/oss/probe`, {
		method: 'GET',
		headers: {
			'Content-Type': 'application/json'
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			error = 'detail' in err ? err.detail : String(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res as OssProbe;
};

/**
 * Detailed diagnostics — superset of /probe. Drives the /diagnostics
 * page (linked from blocking-error screens + Help menu).
 */
export const getOssDiagnostics = async (): Promise<OssDiagnostics> => {
	let error: string | null = null;

	const res = await fetch(`${MYAH_API_BASE_URL}/oss/diagnostics`, {
		method: 'GET',
		headers: {
			'Content-Type': 'application/json'
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			error = 'detail' in err ? err.detail : String(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res as OssDiagnostics;
};

/**
 * Flip the persistent `oss.first_run` flag to false. Called when the
 * user clicks Continue on the Welcome screen. Subsequent probes will
 * return `first_run: false` so the front-end routes to the chat list.
 */
export const markFirstRunComplete = async (): Promise<void> => {
	let error: string | null = null;

	await fetch(`${MYAH_API_BASE_URL}/oss/first_run_complete`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json'
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			error = 'detail' in err ? err.detail : String(err);
			return null;
		});

	if (error) {
		throw error;
	}
};
