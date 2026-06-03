// Server-side resume decision for an in-flight (or just-settled) assistant
// message. Extracted from Chat.svelte.tryResumeInflight so the reachability of
// the backend /live_state DB/final fallback is independently unit-testable and
// shared by the real component.
//
// T3-1096 fix (Task 6): previously the resume flow returned early the moment
// /active_run reported `run_id === null`, so it never called /live_state. That
// made the backend DB/final fallback unreachable from the refresh/navigation
// flow — after the process-local active run was gone there was no path to paint
// the settled assistant message without a full chat reload. Here, when there is
// no active run but a known assistant message id exists in loaded/known history,
// we still ask /live_state for that message so the DB-derived final snapshot can
// paint.

export type ActiveRunResponse = {
	run_id: string | null;
	started_at: number | null;
	message_id: string | null;
};

export type ResolveInflightServerStateDeps = {
	token: string;
	chatId: string;
	getActiveRun: (token: string, chatId: string) => Promise<ActiveRunResponse>;
	getChatLiveState: (
		token: string,
		chatId: string,
		messageId: string
	) => Promise<Record<string, unknown> | null>;
	// Assistant message id known from already-loaded/known history. Used as the
	// /live_state target when there is NO process-local active run, so the
	// backend DB/final fallback stays reachable on refresh / navigation return.
	knownAssistantMessageId?: () => string | null | undefined;
	// Stale-chat guard: returns true once the user has navigated to a different
	// chat. Every async boundary re-checks it so a late response can't paint into
	// the wrong chat.
	isStale?: () => boolean;
	// Optional trace probes (best-effort; no-ops in tests).
	onActiveResolved?: (active: ActiveRunResponse) => void;
	onLiveStateStart?: (messageId: string) => void;
	onLiveStateFinish?: (messageId: string, ok: boolean) => void;
};

/**
 * Resolve the freshest server snapshot for a chat's current assistant message.
 *
 * Returns the merged `{ ...active, ...live }` snapshot to paint, or `null` when
 * there is nothing useful to paint (no run and no known message, the message is
 * still settling without an id, or /live_state had no snapshot). Throws on a
 * malformed /active_run response so callers can surface a terminal banner.
 */
export async function resolveInflightServerState(
	deps: ResolveInflightServerStateDeps
): Promise<Record<string, unknown> | null> {
	const { token, chatId, getActiveRun, getChatLiveState } = deps;
	const isStale = deps.isStale ?? (() => false);

	const active = await getActiveRun(token, chatId);
	if (isStale()) return null;
	// Shape validation is the success gate (Class-7 mitigation).
	if (typeof active?.run_id === 'undefined') {
		throw new Error('malformed active_run response');
	}
	deps.onActiveResolved?.(active);

	// Pick the /live_state target:
	//   - prefer the in-flight run's own message id;
	//   - if there is NO active run, fall back to a known assistant message id
	//     from loaded history so the backend DB/final /live_state fallback stays
	//     reachable after a refresh where _active_runs is gone.
	// When a run IS active but reports no message id yet (still settling), we do
	// NOT guess a fallback — that case must resolve to null without a fetch.
	const fallbackMessageId =
		active.run_id === null ? (deps.knownAssistantMessageId?.() ?? null) : null;
	const messageId = active.message_id ?? fallbackMessageId;
	if (!messageId) {
		return null;
	}

	deps.onLiveStateStart?.(messageId);
	const live = await getChatLiveState(token, chatId, messageId);
	deps.onLiveStateFinish?.(messageId, !!live);
	if (isStale()) return null;
	if (!live) return null;
	return { ...active, ...live };
}
