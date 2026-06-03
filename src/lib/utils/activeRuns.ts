import type { ActiveRun } from '$lib/apis/chats';

export function activeChatIdSetFromRuns(runs: ActiveRun[] | null | undefined): Set<string> {
	const ids = new Set<string>();
	for (const run of runs ?? []) {
		if (!run?.chat_id || !run.run_id) continue;
		ids.add(run.chat_id);
	}
	return ids;
}

export type ApplyActiveChatEventOptions = {
	// When true, a chat:active=false event must NOT flip the indicator to
	// completed: backend work / durable final is still unresolved. The indicator
	// is cleared later via clearActiveChatOnDurableFinal or a stale TTL.
	awaitingDurableFinal?: boolean;
};

export function applyActiveChatEvent(
	current: Set<string>,
	chatId: string | null | undefined,
	active: boolean,
	options: ApplyActiveChatEventOptions = {}
): Set<string> {
	const next = new Set(current);
	if (!chatId) return next;
	if (active) {
		next.add(chatId);
	} else if (!options.awaitingDurableFinal) {
		next.delete(chatId);
	}
	return next;
}

// Remove a chat's active indicator once its final assistant message is durably
// acknowledged (or a stale TTL forces resolution). Pure — never mutates input.
export function clearActiveChatOnDurableFinal(
	current: Set<string>,
	chatId: string | null | undefined
): Set<string> {
	const next = new Set(current);
	if (chatId) next.delete(chatId);
	return next;
}
