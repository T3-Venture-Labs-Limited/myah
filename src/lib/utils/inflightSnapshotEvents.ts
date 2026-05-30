import type { InflightSnapshot } from '../types';

export type SocketChatCompletionEvent = {
	event_id?: string;
	id?: string;
	chat_id?: string;
	message_id?: string;
	data?: {
		type?: string;
		data?: {
			id?: string;
			done?: boolean;
			choices?: Array<{
				delta?: { content?: string };
				message?: { content?: string };
			}>;
			content?: string;
			output?: InflightSnapshot['output'];
		};
	};
};

export type SnapshotUpdate =
	| { kind: 'none' }
	| { kind: 'save'; snapshot: InflightSnapshot }
	| { kind: 'complete'; snapshot: InflightSnapshot };

type SnapshotWithMetadata = InflightSnapshot & { last_event_id?: string };

function eventKey(event: SocketChatCompletionEvent): string | undefined {
	return event.event_id ?? event.id;
}

export function snapshotUpdateFromChatCompletionEvent(
	event: SocketChatCompletionEvent,
	existing: InflightSnapshot | null = null,
	now = Date.now()
): SnapshotUpdate {
	const chatId = event.chat_id ?? '';
	const messageId = event.message_id ?? '';
	const payload = event.data?.data ?? {};
	const type = event.data?.type ?? null;

	if (type !== 'chat:completion' || !chatId || chatId.startsWith('local:') || !messageId) {
		return { kind: 'none' };
	}

	const key = eventKey(event);
	if (key && (existing as SnapshotWithMetadata | null)?.last_event_id === key) {
		return { kind: 'none' };
	}

	let messageContent = existing?.message_content ?? '';
	const choice = payload.choices?.[0];
	const messageChoiceContent = choice?.message?.content;
	const deltaContent = choice?.delta?.content;

	if (typeof messageChoiceContent === 'string' && messageChoiceContent.length > 0) {
		messageContent += messageChoiceContent;
	} else if (typeof deltaContent === 'string') {
		if (!(messageContent === '' && deltaContent === '\n')) {
			messageContent += deltaContent;
		}
	}

	if (typeof payload.content === 'string' && payload.content.length > 0) {
		messageContent = payload.content;
	}

	const snapshot: SnapshotWithMetadata = {
		run_id: payload.id ?? existing?.run_id ?? '',
		chat_id: chatId,
		message_id: messageId,
		started_at: existing?.started_at ?? now,
		updated_at: now,
		message_content: messageContent,
		reasoning_content: existing?.reasoning_content ?? '',
		output: Array.isArray(payload.output) ? payload.output : (existing?.output ?? []),
		status: payload.done ? 'settled' : 'streaming'
	};

	if (key) {
		snapshot.last_event_id = key;
	}

	return payload.done ? { kind: 'complete', snapshot } : { kind: 'save', snapshot };
}
