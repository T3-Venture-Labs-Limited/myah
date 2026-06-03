type JsonRecord = Record<string, unknown>;
type ChatHistoryMessage = JsonRecord & {
	id: string;
	role?: string;
	parentId?: string | null;
	childrenIds?: string[];
	timestamp?: number;
};

export type ChatHistory = JsonRecord & {
	currentId: string | null;
	messages: Record<string, ChatHistoryMessage>;
};

export type NormalizedChatRuntimeEvent = {
	chatId: string;
	messageId?: string;
	type: 'chat:completion' | 'chat:active';
	payload: JsonRecord;
	eventId?: string;
};

export type ChatRuntimeMessage = JsonRecord & {
	id: string;
	role?: string;
	content?: string;
	output?: unknown[];
	done?: boolean;
	timestamp?: number;
	// Graph fields, populated by seedHistory so route-independent projection can
	// render the current user + assistant pair before DB load returns.
	parentId?: string | null;
	childrenIds?: string[];
	model?: string;
	modelName?: string;
};

export type ChatRuntimeChatState = {
	chatId: string;
	messages: Record<string, ChatRuntimeMessage>;
	currentId: string | null;
	active: boolean;
	// A final event (done=true) or chat:active=false was observed. The projection
	// is retained — streamEnded is NOT the same as "safe to clear". Clearing waits
	// for durable final (DB) acknowledgement or a stale TTL.
	streamEnded?: boolean;
	lastUpdated: number;
	lastEventId?: string;
};

export type ChatRuntimeState = {
	chats: Record<string, ChatRuntimeChatState>;
};

const SUPPORTED_TYPES = new Set(['chat:completion', 'chat:active']);

export function emptyChatRuntimeState(): ChatRuntimeState {
	return { chats: {} };
}

function asRecord(value: unknown): JsonRecord {
	return value && typeof value === 'object' && !Array.isArray(value) ? (value as JsonRecord) : {};
}

function optionalString(value: unknown): string | undefined {
	return typeof value === 'string' && value ? value : undefined;
}

function eventIdFrom(event: JsonRecord, payload: JsonRecord): string | undefined {
	return optionalString(
		event.event_id ?? event.id ?? event.last_event_id ?? payload.event_id ?? payload.id
	);
}

export function normalizeChatRuntimeEvent(event: unknown): NormalizedChatRuntimeEvent | null {
	const eventRecord = asRecord(event);
	const chatId = String(eventRecord.chat_id ?? '');
	if (!chatId || chatId === '-' || chatId.startsWith('local:')) return null;

	const dataRecord = asRecord(eventRecord.data);
	const type = dataRecord.type;
	if (typeof type !== 'string' || !SUPPORTED_TYPES.has(type)) return null;

	const payload = asRecord(dataRecord.data);
	if (type === 'chat:completion') {
		const messageId = String(eventRecord.message_id ?? '');
		if (!messageId || messageId === '-' || messageId.startsWith('local:')) return null;
		return { chatId, messageId, type, payload, eventId: eventIdFrom(eventRecord, payload) };
	}

	return { chatId, type: 'chat:active', payload, eventId: eventIdFrom(eventRecord, payload) };
}

function ensureChat(state: ChatRuntimeState, chatId: string): ChatRuntimeChatState {
	return (
		state.chats[chatId] ?? {
			chatId,
			messages: {},
			currentId: null,
			active: false,
			lastUpdated: 0
		}
	);
}

export function applyChatRuntimeEvent(
	state: ChatRuntimeState,
	event: unknown,
	now = Date.now()
): ChatRuntimeState {
	const normalized = normalizeChatRuntimeEvent(event);
	if (!normalized) return state;

	const chat = ensureChat(state, normalized.chatId);

	if (normalized.type === 'chat:active') {
		const active = normalized.payload.active === true;
		const hasRuntimeMessages = Object.keys(chat.messages).length > 0;

		// active=false without a known assistant projection is just a completion
		// signal for a stream this tab cannot durably reconcile. Do not fabricate
		// awaiting-durable-final state or the active indicator will hang until TTL.
		if (!active && !hasRuntimeMessages) {
			if (!state.chats[normalized.chatId]) return state;
			const chats = { ...state.chats };
			delete chats[normalized.chatId];
			return { chats };
		}

		return {
			chats: {
				...state.chats,
				[normalized.chatId]: {
					...chat,
					active,
					// active=false means the backend observed the stream end, but the
					// projection is kept until durable final / stale TTL. active=true is
					// a new/current run and must clear any stale ended marker from a prior run.
					streamEnded: active ? false : true,
					lastUpdated: now,
					lastEventId: normalized.eventId ?? chat.lastEventId
				}
			}
		};
	}

	const messageId = normalized.messageId;
	if (!messageId) return state;

	const payload = normalized.payload;
	const prev = chat.messages[messageId] ?? { id: messageId, role: 'assistant', done: false };
	const done = payload.done === true;
	const nextMessage: ChatRuntimeMessage = {
		...prev,
		id: messageId,
		role: prev.role ?? 'assistant',
		...(typeof payload.content === 'string' ? { content: payload.content } : {}),
		...(Array.isArray(payload.output) ? { output: payload.output } : {}),
		...(typeof payload.usage !== 'undefined' ? { usage: payload.usage } : {}),
		...(payload.error ? { error: payload.error } : {}),
		done
	};

	return {
		chats: {
			...state.chats,
			[normalized.chatId]: {
				...chat,
				messages: { ...chat.messages, [messageId]: nextMessage },
				currentId: messageId,
				active: !done,
				streamEnded: done ? true : chat.streamEnded,
				lastUpdated: now,
				lastEventId: normalized.eventId ?? chat.lastEventId
			}
		}
	};
}

const STREAMING_FIELDS = ['content', 'output', 'usage', 'error', 'done'] as const;

function streamingFieldOverlay(message: ChatRuntimeMessage): JsonRecord {
	const overlay: JsonRecord = {};
	for (const key of STREAMING_FIELDS) {
		if (typeof message[key] !== 'undefined') overlay[key] = message[key];
	}
	return overlay;
}

// Seed the per-chat runtime state with the outgoing user/assistant graph so a
// route-independent projection can render the current pair before DB load.
// Existing streaming fields (from socket events that arrived first) win over
// the seeded shells, so seeding never overwrites newer content.
export function seedChatRuntimeGraph(
	prevChat: ChatRuntimeChatState | null | undefined,
	chatId: string,
	history: unknown,
	now = Date.now()
): ChatRuntimeChatState {
	const h = asHistory(history);
	const base: ChatRuntimeChatState = prevChat ?? {
		chatId,
		messages: {},
		currentId: null,
		active: false,
		lastUpdated: 0
	};
	const messages: Record<string, ChatRuntimeMessage> = { ...base.messages };

	for (const [id, raw] of Object.entries(h.messages)) {
		const seeded: ChatRuntimeMessage = {
			id,
			role: typeof raw.role === 'string' ? raw.role : 'assistant',
			parentId: typeof raw.parentId === 'string' ? raw.parentId : null,
			childrenIds: Array.isArray(raw.childrenIds) ? [...raw.childrenIds] : [],
			timestamp: typeof raw.timestamp === 'number' ? raw.timestamp : now,
			...(typeof raw.content === 'string' ? { content: raw.content } : {}),
			...(typeof raw.done === 'boolean' ? { done: raw.done } : {}),
			...(typeof raw.model === 'string' ? { model: raw.model } : {}),
			...(typeof raw.modelName === 'string' ? { modelName: raw.modelName } : {})
		};

		const existing = messages[id];
		messages[id] = existing ? { ...seeded, ...streamingFieldOverlay(existing) } : seeded;
	}

	return {
		...base,
		chatId,
		messages,
		// A socket event may have already advanced currentId — prefer it so
		// seeding can't rewind a live stream.
		currentId: base.currentId ?? optionalString(h.currentId) ?? null,
		lastUpdated: now
	};
}

function parentIdForSyntheticAssistant(history: ChatHistory): string | null {
	const currentId = history.currentId;
	if (!currentId) return null;
	const current = history.messages[currentId];
	return current?.role === 'user' ? currentId : null;
}

function asHistory(history: unknown): ChatHistory {
	const base = asRecord(history);
	return {
		...base,
		currentId: optionalString(base.currentId) ?? null,
		messages: asRecord(base.messages) as Record<string, ChatHistoryMessage>
	};
}

type ChatProjectionOptions = {
	chatId?: string;
	isolateToChat?: boolean;
};

function historyMatchesChat(history: ChatHistory, chatId?: string): boolean {
	return !chatId || history.chatId === chatId;
}

function isDifferentChatHistory(history: ChatHistory, chatId?: string): boolean {
	return !!(chatId && history.chatId && history.chatId !== chatId);
}

function applyRuntimeChatToHistory(
	history: unknown,
	runtimeChat?: ChatRuntimeChatState | null,
	now = Date.now(),
	options: ChatProjectionOptions = {}
): ChatHistory {
	const incomingBase = asHistory(history);
	const base =
		options.isolateToChat && isDifferentChatHistory(incomingBase, options.chatId)
			? { chatId: options.chatId ?? runtimeChat?.chatId, currentId: null, messages: {} }
			: { ...incomingBase, chatId: options.chatId ?? incomingBase.chatId ?? runtimeChat?.chatId };
	if (!runtimeChat) return base;

	const messages = { ...base.messages };
	let currentId = base.currentId;

	for (const [messageId, runtimeMessage] of Object.entries(runtimeChat.messages)) {
		const existing = messages[messageId];
		if (existing) {
			messages[messageId] = {
				...existing,
				...streamingFieldOverlay(runtimeMessage)
			};
			currentId = messageId;
			continue;
		}

		// A message carries seeded graph context if it knows its own parent or
		// children. Without that we fall back to inferring a parent from the
		// current user turn.
		const hasSeededGraph =
			typeof runtimeMessage.parentId !== 'undefined' || Array.isArray(runtimeMessage.childrenIds);
		const parentId = hasSeededGraph
			? (runtimeMessage.parentId ?? null)
			: parentIdForSyntheticAssistant({ ...base, messages, currentId });

		// Do not fabricate a parent for assistant-only runtime state. An orphan
		// assistant with no graph context is a fast-paint miss, not a render.
		if (!hasSeededGraph && parentId === null) {
			continue;
		}

		messages[messageId] = {
			id: messageId,
			role: runtimeMessage.role ?? 'assistant',
			parentId,
			childrenIds: Array.isArray(runtimeMessage.childrenIds)
				? [...runtimeMessage.childrenIds]
				: [],
			timestamp: runtimeMessage.timestamp ?? now,
			...(runtimeMessage.model ? { model: runtimeMessage.model } : {}),
			...(runtimeMessage.modelName ? { modelName: runtimeMessage.modelName } : {}),
			...streamingFieldOverlay(runtimeMessage)
		};

		// For inferred (non-seeded) parents, link the child back. Seeded graphs
		// already carry authoritative childrenIds and must not be recomputed.
		if (!hasSeededGraph && parentId && messages[parentId]) {
			const childrenIds = Array.isArray(messages[parentId].childrenIds)
				? messages[parentId].childrenIds
				: [];
			messages[parentId] = {
				...messages[parentId],
				childrenIds: childrenIds.includes(messageId) ? childrenIds : [...childrenIds, messageId]
			};
		}
		currentId = messageId;
	}

	// Only honour runtime currentId if that message was actually materialized;
	// otherwise an orphan-skipped message must not become the rendered head.
	const finalCurrentId =
		runtimeChat.currentId && messages[runtimeChat.currentId] ? runtimeChat.currentId : currentId;

	return {
		...base,
		currentId: finalCurrentId,
		messages
	};
}

export function getProjectedChatHistory(
	history: unknown,
	runtimeChat?: ChatRuntimeChatState | null,
	now = Date.now(),
	options: ChatProjectionOptions = {}
): ChatHistory {
	return applyRuntimeChatToHistory(history, runtimeChat, now, options);
}

export function reconcileLoadedHistoryWithRuntime(
	history: unknown,
	runtimeChat?: ChatRuntimeChatState | null,
	now = Date.now(),
	options: ChatProjectionOptions = {}
): ChatHistory {
	return applyRuntimeChatToHistory(history, runtimeChat, now, options);
}
