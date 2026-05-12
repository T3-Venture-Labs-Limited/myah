// Skills API — backed by Hermes agent (name-keyed files, not OWI UUIDs).
// All endpoints proxy through /api/v1/agent/skills on the platform backend.
import { WEBUI_API_BASE_URL } from '$lib/constants';

export const getAgentSkills = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/agent/skills`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
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

	return res;
};

export const getAgentSkill = async (token: string, name: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/agent/skills/${encodeURIComponent(name)}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
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

	return res;
};

export const createAgentSkillEntry = async (
	token: string,
	payload: { name: string; category?: string; description?: string; trigger?: string; content: string }
) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/agent/skills`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
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

	if (error) {
		throw error;
	}

	return res;
};

export const updateAgentSkillEntry = async (
	token: string,
	name: string,
	payload: { name?: string; category?: string; description?: string; trigger?: string; content?: string }
) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/agent/skills/${encodeURIComponent(name)}`, {
		method: 'PUT',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
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

	if (error) {
		throw error;
	}

	return res;
};

export const deleteAgentSkillEntry = async (token: string, name: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/agent/skills/${encodeURIComponent(name)}`, {
		method: 'DELETE',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
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

	return res;
};
