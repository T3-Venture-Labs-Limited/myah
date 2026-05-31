export type ChatEventPayload = {
	chat_id?: string | null;
	message_id?: string | null;
	data?: {
		type?: string | null;
		data?: Record<string, any> | null;
	} | null;
};

export type ChatLike = {
	history?: {
		messages?: Record<string, any>;
		currentId?: string | null;
	};
};

type DurableFinalMessageOptions = {
	clearInflightSnapshot?: (chatId: string) => void;
};

export const applyDurableFinalMessageEvent = (
	event: ChatEventPayload,
	chatId: string | null | undefined,
	chat: ChatLike | null | undefined,
	options: DurableFinalMessageOptions = {}
): boolean => {
	if (!event || event.chat_id !== chatId) {
		return false;
	}

	if (event?.data?.type !== 'chat:completion') {
		return false;
	}

	const data = event.data.data ?? {};
	const messageId = String(event.message_id ?? '');
	const eventChatId = event.chat_id;
	const isDurableFinalFallback =
		data.done === true &&
		typeof data.content === 'string' &&
		!!messageId &&
		String(data.message_id ?? '') === messageId &&
		data.chat_id === eventChatId;
	if (!isDurableFinalFallback) {
		return false;
	}

	// Only the durable final-message endpoint emits matching inner markers.
	// Ordinary streaming completion events can also carry done/content, but
	// handling those here would race the normal chat completion handler and can
	// strip legitimate structured output.
	if (data.chat_id !== event.chat_id || data.message_id !== messageId) {
		return false;
	}

	const messages = chat?.history?.messages;
	const message = messages?.[messageId];
	if (!message) {
		return false;
	}

	message.content = data.content;
	message.done = true;
	if (Array.isArray(data.output)) {
		message.output = data.output;
	} else {
		delete message.output;
	}
	if (data.error) {
		message.error = data.error;
	}
	if (eventChatId && !eventChatId.startsWith('local:')) {
		options.clearInflightSnapshot?.(eventChatId);
	}
	messages[messageId] = message;
	return true;
};
