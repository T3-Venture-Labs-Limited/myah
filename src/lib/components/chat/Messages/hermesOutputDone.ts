export interface HermesOutputDoneInput {
	message?: {
		id?: string | null;
		role?: string | null;
		done?: boolean | null;
	} | null;
	history?: {
		currentId?: string | null;
	} | null;
	chatFadeStreamingText?: boolean;
}

/**
 * Structured Hermes output contains interactive cards (approvals, secret forms,
 * clarify prompts) whose raw stored item status can remain `pending` forever.
 * Only the current assistant branch can be live. Older assistant messages must
 * render as terminal/inactive even if persisted with `done: false`.
 */
export function computeHermesOutputDone({
	message,
	history,
	chatFadeStreamingText = true
}: HermesOutputDoneInput): boolean {
	if (!chatFadeStreamingText) return true;
	if (message?.done === true) return true;

	const messageId = message?.id;
	const currentId = history?.currentId;
	if (message?.role === 'assistant' && messageId && currentId && messageId !== currentId) {
		return true;
	}

	return false;
}
