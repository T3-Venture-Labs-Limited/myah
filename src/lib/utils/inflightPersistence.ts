// Every thought in flight deserves a safe harbour. These utilities hold
// the shape of a streaming response so that if the page reloads mid-run,
// the UI can restore a plausible view while the server catches up.
// This is a paint hint only — server state is always authoritative.
import type { InflightSnapshot } from '../types';

const KEY_PREFIX = 'myah-inflight-state:';
const STALE_THRESHOLD_MS = 600_000; // 10 minutes
const MAX_SERIALIZED_SNAPSHOT_BYTES = 200_000;

function serializedLength(value: unknown): number {
	return JSON.stringify(value).length;
}

function boundedSnapshot(snapshot: InflightSnapshot): InflightSnapshot {
	const payload: InflightSnapshot = { ...snapshot, updated_at: Date.now() };
	if (serializedLength(payload) <= MAX_SERIALIZED_SNAPSHOT_BYTES) {
		return payload;
	}

	const withoutOutput: InflightSnapshot = { ...payload, output: [] };
	return serializedLength(withoutOutput) <= MAX_SERIALIZED_SNAPSHOT_BYTES
		? withoutOutput
		: { ...withoutOutput, message_content: withoutOutput.message_content.slice(0, 10_000) };
}

export function saveInflightSnapshot(snapshot: InflightSnapshot): void {
	const payload = boundedSnapshot(snapshot);
	try {
		localStorage.setItem(`${KEY_PREFIX}${snapshot.chat_id}`, JSON.stringify(payload));
	} catch (err) {
		if (err instanceof DOMException && err.name === 'QuotaExceededError') {
			return;
		}
		throw err;
	}
}

export function loadInflightSnapshot(chatId: string): InflightSnapshot | null {
	const raw = localStorage.getItem(`${KEY_PREFIX}${chatId}`);
	if (raw === null) return null;
	try {
		return JSON.parse(raw) as InflightSnapshot;
	} catch {
		return null;
	}
}

export function clearInflightSnapshot(chatId: string): void {
	localStorage.removeItem(`${KEY_PREFIX}${chatId}`);
}

export function pruneStaleSnapshots(): void {
	const cutoff = Date.now() - STALE_THRESHOLD_MS;
	const keysToRemove: string[] = [];

	for (let i = 0; i < localStorage.length; i++) {
		const key = localStorage.key(i);
		if (!key?.startsWith(KEY_PREFIX)) continue;
		const raw = localStorage.getItem(key);
		if (!raw) continue;
		try {
			const snapshot = JSON.parse(raw) as InflightSnapshot;
			if (snapshot.updated_at < cutoff) {
				keysToRemove.push(key);
			}
		} catch {
			// Malformed entry — remove it
			keysToRemove.push(key);
		}
	}

	for (const key of keysToRemove) {
		localStorage.removeItem(key);
	}
}
