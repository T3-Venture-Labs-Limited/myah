import { normalizeChatRuntimeEvent } from './chatRuntimeProjection';

export function ingestChatRuntimeSocketEvent(
	event: unknown,
	deps: {
		applyEvent: (event: unknown) => void;
		persistInflightSnapshotFromEvent: (event: unknown) => void;
	}
): void {
	const normalized = normalizeChatRuntimeEvent(event);
	if (!normalized) return;

	deps.applyEvent(event);
	if (normalized.type === 'chat:completion') {
		deps.persistInflightSnapshotFromEvent(event);
	}
}
