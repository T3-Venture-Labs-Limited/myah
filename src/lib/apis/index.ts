import { WEBUI_BASE_URL } from '$lib/constants';
import { getOpenAIModelsDirect } from './openai';

// Every request sent from here is a petition. May it reach
// the one for whom it was intended, and return answered.
export const getModels = async (
	token: string = '',
	connections: object | null = null,
	base: boolean = false,
	refresh: boolean = false
) => {
	const searchParams = new URLSearchParams();
	if (refresh) {
		searchParams.append('refresh', 'true');
	}

	let error = null;
	const res = await fetch(
		`${WEBUI_BASE_URL}/api/models${base ? '/base' : ''}?${searchParams.toString()}`,
		{
			method: 'GET',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				...(token && { authorization: `Bearer ${token}` })
			}
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	let models = res?.data ?? [];

	if (connections && !base) {
		let localModels = [];

		if (connections) {
			const OPENAI_API_BASE_URLS = connections.OPENAI_API_BASE_URLS;
			const OPENAI_API_KEYS = connections.OPENAI_API_KEYS;
			const OPENAI_API_CONFIGS = connections.OPENAI_API_CONFIGS;

			const requests = [];
			for (const idx in OPENAI_API_BASE_URLS) {
				const url = OPENAI_API_BASE_URLS[idx];

				if (idx.toString() in OPENAI_API_CONFIGS) {
					const apiConfig = OPENAI_API_CONFIGS[idx.toString()] ?? {};

					const enable = apiConfig?.enable ?? true;
					const modelIds = apiConfig?.model_ids ?? [];

					if (enable) {
						if (modelIds.length > 0) {
							const modelList = {
								object: 'list',
								data: modelIds.map((modelId) => ({
									id: modelId,
									name: modelId,
									owned_by: 'openai',
									openai: { id: modelId },
									urlIdx: idx
								}))
							};

							requests.push(
								(async () => {
									return modelList;
								})()
							);
						} else {
							requests.push(
								(async () => {
									return await getOpenAIModelsDirect(url, OPENAI_API_KEYS[idx])
										.then((res) => {
											return res;
										})
										.catch((err) => {
											return {
												object: 'list',
												data: [],
												urlIdx: idx
											};
										});
								})()
							);
						}
					} else {
						requests.push(
							(async () => {
								return {
									object: 'list',
									data: [],
									urlIdx: idx
								};
							})()
						);
					}
				}
			}

			const responses = await Promise.all(requests);

			for (const idx in responses) {
				const response = responses[idx];
				const apiConfig = OPENAI_API_CONFIGS[idx.toString()] ?? {};

				let models = Array.isArray(response) ? response : (response?.data ?? []);
				models = models.map((model) => ({ ...model, openai: { id: model.id }, urlIdx: idx }));

				const prefixId = apiConfig.prefix_id;
				if (prefixId) {
					for (const model of models) {
						model.id = `${prefixId}.${model.id}`;
					}
				}

				const tags = apiConfig.tags;
				if (tags) {
					for (const model of models) {
						model.tags = tags;
					}
				}

				localModels = localModels.concat(models);
			}
		}

		models = models.concat(
			localModels.map((model) => ({
				...model,
				name: model?.name ?? model?.id,
				direct: true
			}))
		);

		// Remove duplicates
		const modelsMap = {};
		for (const model of models) {
			modelsMap[model.id] = model;
		}

		models = Object.values(modelsMap);
	}

	return models;
};

export const getBaseModels = async (token: string = '') => {
	return getModels(token, null, true);
};

type ChatCompletedForm = {
	model: string;
	messages: string[];
	chat_id: string;
	session_id: string;
};

export const chatCompleted = async (token: string, body: ChatCompletedForm) => {
	let error = null;

	const res = await fetch(`${WEBUI_BASE_URL}/api/chat/completed`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		},
		body: JSON.stringify(body)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			if ('detail' in err) {
				error = err.detail;
			} else {
				error = err;
			}
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

type ChatActionForm = {
	model: string;
	messages: string[];
	chat_id: string;
};

export const chatAction = async (token: string, action_id: string, body: ChatActionForm) => {
	let error = null;

	const res = await fetch(`${WEBUI_BASE_URL}/api/chat/actions/${action_id}`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			...(token && { authorization: `Bearer ${token}` })
		},
		body: JSON.stringify(body)
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			if ('detail' in err) {
				error = err.detail;
			} else {
				error = err;
			}
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const stopTask = async (token: string, id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_BASE_URL}/api/tasks/stop/${id}`, {
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
			if ('detail' in err) {
				error = err.detail;
			} else {
				error = err;
			}
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getTaskIdsByChatId = async (token: string, chat_id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_BASE_URL}/api/tasks/chat/${chat_id}`, {
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
			if ('detail' in err) {
				error = err.detail;
			} else {
				error = err;
			}
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const generateTitle = async (
	token: string = '',
	model: string,
	messages: object[],
	chat_id?: string
) => {
	let error = null;

	const res = await fetch(`${WEBUI_BASE_URL}/api/v1/tasks/title/completions`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			model: model,
			messages: messages,
			...(chat_id && { chat_id: chat_id })
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			if ('detail' in err) {
				error = err.detail;
			}
			return null;
		});

	if (error) {
		throw error;
	}

	try {
		// Step 1: Safely extract the response string
		const response = res?.choices[0]?.message?.content ?? '';

		// Step 2: Attempt to fix common JSON format issues like single quotes
		const sanitizedResponse = response.replace(/['‘’`]/g, '"'); // Convert single quotes to double quotes for valid JSON

		// Step 3: Find the relevant JSON block within the response
		const jsonStartIndex = sanitizedResponse.indexOf('{');
		const jsonEndIndex = sanitizedResponse.lastIndexOf('}');

		// Step 4: Check if we found a valid JSON block (with both `{` and `}`)
		if (jsonStartIndex !== -1 && jsonEndIndex !== -1) {
			const jsonResponse = sanitizedResponse.substring(jsonStartIndex, jsonEndIndex + 1);

			// Step 5: Parse the JSON block
			const parsed = JSON.parse(jsonResponse);

			// Step 6: If there's a "tags" key, return the tags array; otherwise, return an empty array
			if (parsed && parsed.title) {
				return parsed.title;
			} else {
				return null;
			}
		}

		// If no valid JSON block found, return an empty array
		return null;
	} catch (e) {
		// Catch and safely return empty array on any parsing errors
		console.error('Failed to parse response: ', e);
		return null;
	}
};

export const generateFollowUps = async (
	token: string = '',
	model: string,
	messages: string,
	chat_id?: string
) => {
	let error = null;

	const res = await fetch(`${WEBUI_BASE_URL}/api/v1/tasks/follow_up/completions`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			model: model,
			messages: messages,
			...(chat_id && { chat_id: chat_id })
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			if ('detail' in err) {
				error = err.detail;
			}
			return null;
		});

	if (error) {
		throw error;
	}

	try {
		// Step 1: Safely extract the response string
		const response = res?.choices[0]?.message?.content ?? '';

		// Step 2: Attempt to fix common JSON format issues like single quotes
		const sanitizedResponse = response.replace(/['‘’`]/g, '"'); // Convert single quotes to double quotes for valid JSON

		// Step 3: Find the relevant JSON block within the response
		const jsonStartIndex = sanitizedResponse.indexOf('{');
		const jsonEndIndex = sanitizedResponse.lastIndexOf('}');

		// Step 4: Check if we found a valid JSON block (with both `{` and `}`)
		if (jsonStartIndex !== -1 && jsonEndIndex !== -1) {
			const jsonResponse = sanitizedResponse.substring(jsonStartIndex, jsonEndIndex + 1);

			// Step 5: Parse the JSON block
			const parsed = JSON.parse(jsonResponse);

			// Step 6: If there's a "follow_ups" key, return the follow_ups array; otherwise, return an empty array
			if (parsed && parsed.follow_ups) {
				return Array.isArray(parsed.follow_ups) ? parsed.follow_ups : [];
			} else {
				return [];
			}
		}

		// If no valid JSON block found, return an empty array
		return [];
	} catch (e) {
		// Catch and safely return empty array on any parsing errors
		console.error('Failed to parse response: ', e);
		return [];
	}
};

export const generateTags = async (
	token: string = '',
	model: string,
	messages: string,
	chat_id?: string
) => {
	let error = null;

	const res = await fetch(`${WEBUI_BASE_URL}/api/v1/tasks/tags/completions`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			model: model,
			messages: messages,
			...(chat_id && { chat_id: chat_id })
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			if ('detail' in err) {
				error = err.detail;
			}
			return null;
		});

	if (error) {
		throw error;
	}

	try {
		// Step 1: Safely extract the response string
		const response = res?.choices[0]?.message?.content ?? '';

		// Step 2: Attempt to fix common JSON format issues like single quotes
		const sanitizedResponse = response.replace(/['‘’`]/g, '"'); // Convert single quotes to double quotes for valid JSON

		// Step 3: Find the relevant JSON block within the response
		const jsonStartIndex = sanitizedResponse.indexOf('{');
		const jsonEndIndex = sanitizedResponse.lastIndexOf('}');

		// Step 4: Check if we found a valid JSON block (with both `{` and `}`)
		if (jsonStartIndex !== -1 && jsonEndIndex !== -1) {
			const jsonResponse = sanitizedResponse.substring(jsonStartIndex, jsonEndIndex + 1);

			// Step 5: Parse the JSON block
			const parsed = JSON.parse(jsonResponse);

			// Step 6: If there's a "tags" key, return the tags array; otherwise, return an empty array
			if (parsed && parsed.tags) {
				return Array.isArray(parsed.tags) ? parsed.tags : [];
			} else {
				return [];
			}
		}

		// If no valid JSON block found, return an empty array
		return [];
	} catch (e) {
		// Catch and safely return empty array on any parsing errors
		console.error('Failed to parse response: ', e);
		return [];
	}
};

export const generateEmoji = async (
	token: string = '',
	model: string,
	prompt: string,
	chat_id?: string
) => {
	let error = null;

	const res = await fetch(`${WEBUI_BASE_URL}/api/v1/tasks/emoji/completions`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			model: model,
			prompt: prompt,
			...(chat_id && { chat_id: chat_id })
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			if ('detail' in err) {
				error = err.detail;
			}
			return null;
		});

	if (error) {
		throw error;
	}

	const response = res?.choices[0]?.message?.content.replace(/["']/g, '') ?? null;

	if (response) {
		if (/\p{Extended_Pictographic}/u.test(response)) {
			return response.match(/\p{Extended_Pictographic}/gu)[0];
		}
	}

	return null;
};

export const generateQueries = async (
	token: string = '',
	model: string,
	messages: object[],
	prompt: string,
	type: string = 'web_search',
	chat_id?: string
) => {
	let error = null;

	const res = await fetch(`${WEBUI_BASE_URL}/api/v1/tasks/queries/completions`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			model: model,
			messages: messages,
			prompt: prompt,
			type: type,
			...(chat_id && { chat_id: chat_id })
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			if ('detail' in err) {
				error = err.detail;
			}
			return null;
		});

	if (error) {
		throw error;
	}

	// Step 1: Safely extract the response string
	const response = res?.choices[0]?.message?.content ?? '';

	try {
		const jsonStartIndex = response.indexOf('{');
		const jsonEndIndex = response.lastIndexOf('}');

		if (jsonStartIndex !== -1 && jsonEndIndex !== -1) {
			const jsonResponse = response.substring(jsonStartIndex, jsonEndIndex + 1);

			// Step 5: Parse the JSON block
			const parsed = JSON.parse(jsonResponse);

			// Step 6: If there's a "queries" key, return the queries array; otherwise, return an empty array
			if (parsed && parsed.queries) {
				return Array.isArray(parsed.queries) ? parsed.queries : [];
			} else {
				return [];
			}
		}

		// If no valid JSON block found, return response as is
		return [response];
	} catch (e) {
		// Catch and safely return empty array on any parsing errors
		console.error('Failed to parse response: ', e);
		return [response];
	}
};

export const generateAutoCompletion = async (
	token: string = '',
	model: string,
	prompt: string,
	messages?: object[],
	type: string = 'search query',
	chat_id?: string
) => {
	const controller = new AbortController();
	let error = null;

	const res = await fetch(`${WEBUI_BASE_URL}/api/v1/tasks/auto/completions`, {
		signal: controller.signal,
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			model: model,
			prompt: prompt,
			...(messages && { messages: messages }),
			type: type,
			stream: false,
			...(chat_id && { chat_id: chat_id })
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			if ('detail' in err) {
				error = err.detail;
			}
			return null;
		});

	if (error) {
		throw error;
	}

	const response = res?.choices[0]?.message?.content ?? '';

	try {
		const jsonStartIndex = response.indexOf('{');
		const jsonEndIndex = response.lastIndexOf('}');

		if (jsonStartIndex !== -1 && jsonEndIndex !== -1) {
			const jsonResponse = response.substring(jsonStartIndex, jsonEndIndex + 1);

			// Step 5: Parse the JSON block
			const parsed = JSON.parse(jsonResponse);

			// Step 6: If there's a "queries" key, return the queries array; otherwise, return an empty array
			if (parsed && parsed.text) {
				return parsed.text;
			} else {
				return '';
			}
		}

		// If no valid JSON block found, return response as is
		return response;
	} catch (e) {
		// Catch and safely return empty array on any parsing errors
		console.error('Failed to parse response: ', e);
		return response;
	}
};

export const getUsage = async (token: string = '') => {
	let error = null;

	const res = await fetch(`${WEBUI_BASE_URL}/api/usage`, {
		method: 'GET',
		headers: {
			'Content-Type': 'application/json',
			...(token && { Authorization: `Bearer ${token}` })
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			error = err;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getBackendConfig = async () => {
	let error = null;

	const res = await fetch(`${WEBUI_BASE_URL}/api/config`, {
		method: 'GET',
		credentials: 'include',
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
			error = err;
			return null;
		});

	if (error) {
		// When a forward-auth proxy (e.g. Authentik/Traefik) intercepts the
		// request and redirects to an external login page, the browser blocks
		// the cross-origin redirect for fetch() and throws a TypeError.
		// Detect this by re-fetching with redirect:"manual" — if the server
		// responded with a redirect, the probe returns an opaque redirect
		// response instead of throwing, confirming the backend is alive but
		// an auth proxy is intercepting.
		if (error instanceof TypeError) {
			try {
				const probeRes = await fetch(`${WEBUI_BASE_URL}/api/config`, {
					method: 'GET',
					credentials: 'include',
					redirect: 'manual',
					headers: { 'Content-Type': 'application/json' }
				});
				if (
					probeRes.type === 'opaqueredirect' ||
					(probeRes.status >= 300 && probeRes.status < 400)
				) {
					throw { authRedirect: true };
				}
			} catch (probeErr: any) {
				if (probeErr?.authRedirect) throw probeErr;
				// Probe also failed — genuine network/backend issue
			}
		}
		throw error;
	}

	return res;
};

export const getChangelog = async () => {
	let error = null;

	const res = await fetch(`${WEBUI_BASE_URL}/api/changelog`, {
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
			error = err;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getVersion = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_BASE_URL}/api/version`, {
		method: 'GET',
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
			error = err;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};


export const getWebhookUrl = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_BASE_URL}/api/webhook`, {
		method: 'GET',
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
			error = err;
			return null;
		});

	if (error) {
		throw error;
	}

	return res.url;
};

export const updateWebhookUrl = async (token: string, url: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_BASE_URL}/api/webhook`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			url: url
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			error = err;
			return null;
		});

	if (error) {
		throw error;
	}

	return res.url;
};

export const getModelConfig = async (token: string): Promise<GlobalModelConfig> => {
	let error = null;

	const res = await fetch(`${WEBUI_BASE_URL}/api/config/models`, {
		method: 'GET',
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
			error = err;
			return null;
		});

	if (error) {
		throw error;
	}

	return res.models;
};

export interface ModelConfig {
	id: string;
	name: string;
	meta: ModelMeta;
	base_model_id?: string;
	params: ModelParams;
}

export interface ModelMeta {
	toolIds: never[];
	description?: string;
	capabilities?: object;
	profile_image_url?: string;
}

export interface ModelParams {}

export type GlobalModelConfig = ModelConfig[];

export const getProviderModels = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_BASE_URL}/api/v1/users/user/llm/models`, {
		method: 'GET',
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

	return res;
};

// Fetch the union of admin base models + the user's provider-catalog models
// (openrouter, openai, anthropic, google) so the selector, default picker,
// and attribution badge all see the same list. Provider models take precedence
// on id collision. Returns an array usable as the $models store value.
// T3-932: previously the provider models were only merged in on hover of the
// model selector button, which caused "Model not found" toasts whenever a
// persisted provider model wasn't yet in $models.
export const getModelsWithProviders = async (
	token: string = '',
	connections: object | null = null
) => {
	const [baseModels, providerResult] = await Promise.all([
		getModels(token, connections),
		getProviderModels(token).catch(() => null)
	]);

	const providerModels = providerResult?.data ?? [];
	if (providerModels.length === 0) {
		return baseModels;
	}

	const providerIds = new Set(providerModels.map((m: { id: string }) => m.id));
	return [...providerModels, ...baseModels.filter((m: { id: string }) => !providerIds.has(m.id))];
};

export const updateModelConfig = async (token: string, config: GlobalModelConfig) => {
	let error = null;

	const res = await fetch(`${WEBUI_BASE_URL}/api/config/models`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			models: config
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			console.error(err);
			error = err;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};
