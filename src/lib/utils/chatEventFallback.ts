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

export const applyDurableFinalMessageEvent = (
	event: ChatEventPayload,
	chatId: string | null | undefined,
	chat: ChatLike | null | undefined
): boolean => {
	if (!event || event.chat_id !== chatId) {
		return false;
	}

	if (event?.data?.type !== 'chat:completion') {
		return false;
	}

	const data = event.data.data ?? {};
	if (!data.done || typeof data.content !== 'string') {
		return false;
	}

	const messageId = String(event.message_id ?? '');
	if (!messageId) {
		return false;
	}

	const messages = chat?.history?.messages;
	const message = messages?.[messageId];
	if (!message) {
		return false;
	}

	message.content = data.content;
	message.done = true;
	if (data.error) {
		message.error = data.error;
	}
	messages[messageId] = message;
	return true;
};
