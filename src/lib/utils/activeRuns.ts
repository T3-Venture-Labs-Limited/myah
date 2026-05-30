import type { ActiveRun } from '$lib/apis/chats';

export function activeChatIdSetFromRuns(runs: ActiveRun[] | null | undefined): Set<string> {
	const ids = new Set<string>();
	for (const run of runs ?? []) {
		if (!run?.chat_id || !run.run_id) continue;
		ids.add(run.chat_id);
	}
	return ids;
}

export function applyActiveChatEvent(
	current: Set<string>,
	chatId: string | null | undefined,
	active: boolean
): Set<string> {
	const next = new Set(current);
	if (!chatId) return next;
	if (active) {
		next.add(chatId);
	} else {
		next.delete(chatId);
	}
	return next;
}
