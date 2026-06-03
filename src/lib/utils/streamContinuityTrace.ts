// A timeline left behind so the journey can be read after the fact.
// This is an RCA probe for stream continuity: it records WHEN each
// lifecycle phase happened for a chat, never WHAT was said. Content,
// prompts, file names, secrets, tool args and raw output are dropped
// on the way in so a trace is always safe to paste into PR notes.

// Only these fields survive sanitization — IDs, phases, durations,
// booleans, counts. Everything else (content, output, file, tool_args,
// attachments, prompts) is intentionally discarded.
const ALLOWED_DATA_KEYS = new Set([
	'message_id',
	'run_id',
	'event_id',
	'has_content',
	'output_count',
	'reason',
	'duration_ms',
	'count',
	'active',
	'done',
	'ok',
	'source'
]);

export type StreamContinuityPhase = string;

export type StreamContinuityEntry = {
	phase: StreamContinuityPhase;
	at: number;
	data?: Record<string, unknown>;
};

export type StreamContinuityTrace = {
	record(chatId: string, phase: StreamContinuityPhase, data?: Record<string, unknown>): void;
	entries(chatId: string): StreamContinuityEntry[];
	clear(chatId?: string): void;
};

type TraceOptions = {
	maxEntries?: number;
	now?: () => number;
};

function sanitize(data?: Record<string, unknown>): Record<string, unknown> | undefined {
	if (!data) return undefined;
	const safe: Record<string, unknown> = {};
	for (const [key, value] of Object.entries(data)) {
		if (!ALLOWED_DATA_KEYS.has(key)) continue;
		if (value === null || ['string', 'number', 'boolean'].includes(typeof value)) {
			safe[key] = value;
		}
	}
	return safe;
}

export function createStreamContinuityTrace(options: TraceOptions = {}): StreamContinuityTrace {
	const maxEntries = options.maxEntries ?? 200;
	const now = options.now ?? (() => Date.now());
	const buffers = new Map<string, StreamContinuityEntry[]>();

	return {
		record(chatId, phase, data) {
			if (!chatId) return;
			const entry: StreamContinuityEntry = { phase, at: now() };
			const safe = sanitize(data);
			if (safe && Object.keys(safe).length > 0) entry.data = safe;

			const buffer = buffers.get(chatId) ?? [];
			buffer.push(entry);
			while (buffer.length > maxEntries) buffer.shift();
			buffers.set(chatId, buffer);
		},
		entries(chatId) {
			return [...(buffers.get(chatId) ?? [])];
		},
		clear(chatId) {
			if (chatId) {
				buffers.delete(chatId);
			} else {
				buffers.clear();
			}
		}
	};
}

// Process-wide singleton. Exposed on window only in dev/debug so manual
// smoke runs (Task 8) can export a content-free timeline. Never persisted.
export const streamContinuityTrace = createStreamContinuityTrace();

export function exposeStreamContinuityTraceForDebug(): void {
	if (typeof window === 'undefined') return;
	try {
		const dev = Boolean((import.meta as { env?: { DEV?: boolean } }).env?.DEV);
		if (!dev) return;
		(window as unknown as { __MYAH_STREAM_TRACE__?: StreamContinuityTrace }).__MYAH_STREAM_TRACE__ =
			streamContinuityTrace;
	} catch {
		// Non-fatal — the probe is best-effort instrumentation only.
	}
}
