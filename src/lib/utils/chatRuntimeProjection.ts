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
};

export type ChatRuntimeChatState = {
	chatId: string;
	messages: Record<string, ChatRuntimeMessage>;
	currentId: string | null;
	active: boolean;
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
		return {
			chats: {
				...state.chats,
				[normalized.chatId]: {
					...chat,
					active: normalized.payload.active === true,
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
				lastUpdated: now,
				lastEventId: normalized.eventId ?? chat.lastEventId
			}
		}
	};
}

function streamingFieldOverlay(message: ChatRuntimeMessage): JsonRecord {
	const overlay: JsonRecord = {};
	for (const key of ['content', 'output', 'usage', 'error', 'done']) {
		if (typeof message[key] !== 'undefined') overlay[key] = message[key];
	}
	return overlay;
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

		const parentId = parentIdForSyntheticAssistant({ ...base, messages, currentId });
		messages[messageId] = {
			id: messageId,
			role: runtimeMessage.role ?? 'assistant',
			parentId,
			childrenIds: [],
			timestamp: runtimeMessage.timestamp ?? now,
			...streamingFieldOverlay(runtimeMessage)
		};

		if (parentId && messages[parentId]) {
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

	return {
		...base,
		currentId: runtimeChat.currentId ?? currentId,
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
