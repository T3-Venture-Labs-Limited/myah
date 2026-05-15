import { ARTIFACT_TOOL_NAMES, extractPathFromToolResult } from '$lib/utils/artifact-triggers';
import { detectFileType } from '$lib/utils/fileTypeRegistry';

export type ActivityVerb = 'created' | 'edited' | 'produced';

interface ActivityEntry {
	lastOp: ActivityVerb;
	lastOpAt: number;
	isLive: boolean;
}

/**
 * Per-chat activity Map. Aggregated client-side from `tool.completed` events
 * carried by the Hermes SSE stream. Verbs are derived from real registered
 * Hermes tool names — see spec Section 4 of the artifact-pane-redesign.
 *
 * Verb derivation:
 *   - write_file → 'created' if file_key is new, 'edited' otherwise
 *   - patch      → 'edited'
 *   - execute_code, terminal, image_generate, text_to_speech, browser_get_images
 *                → 'produced'
 *
 * The footer status bar reads `isLive` to render
 * "Myah is editing <filename>" while a tool is mid-flight.
 *
 * Path resolution: delegates entirely to `extractPathFromToolResult`, which
 * mirrors `extract_path_from_tool_result` in artifact_triggers.py — including
 * the stdout/output regex scan needed for execute_code / terminal tools that
 * mention the saved-file path inside their captured stdout. The
 * `isKnownFileExtension` gate inside that scan is the permissive sibling of
 * `isArtifactExtension`, so media (png/mp3/mp4) is recognised here too.
 *
 * File-type gate: uses detectFileType (any known kind) rather than the
 * stricter isArtifactExtension. This is intentional — the activity tracker
 * tracks all file-producing tool results, including media (png/mp3/mp4)
 * which the TS-side fileTypeRegistry currently classifies as
 * capability:'inline'. Phase 2B will upgrade those to capability:'both'
 * and the divergence between Python `_ARTIFACT_EXTENSIONS` and TS
 * `isArtifactExtension` will go away.
 */
export class ActivityTracker {
	private entries = new Map<string, ActivityEntry>();
	private inFlight = new Set<string>();

	onToolStarted(toolName: string, args: unknown): void {
		if (!ARTIFACT_TOOL_NAMES.includes(toolName)) return;
		const path = this.resolvePath(args);
		if (!path || !detectFileType(path)) return;
		const file_key = `path:${path}`;
		this.inFlight.add(file_key);
		const existing = this.entries.get(file_key);
		this.entries.set(file_key, {
			lastOp: existing?.lastOp ?? 'edited',
			lastOpAt: Date.now(),
			isLive: true
		});
	}

	onToolCompleted(toolName: string, result: unknown): void {
		if (!ARTIFACT_TOOL_NAMES.includes(toolName)) return;
		const path = extractPathFromToolResult(result);
		if (!path || !detectFileType(path)) return;
		const file_key = `path:${path}`;
		const existed = this.entries.has(file_key);

		let verb: ActivityVerb;
		if (toolName === 'write_file') {
			verb = existed ? 'edited' : 'created';
		} else if (toolName === 'patch') {
			verb = 'edited';
		} else {
			// execute_code, terminal, image_generate, text_to_speech, browser_get_images
			verb = 'produced';
		}

		this.inFlight.delete(file_key);
		this.entries.set(file_key, {
			lastOp: verb,
			lastOpAt: Date.now(),
			isLive: false
		});
	}

	lastOp(file_key: string): ActivityVerb | undefined {
		return this.entries.get(file_key)?.lastOp;
	}

	isLive(file_key: string): boolean {
		return this.entries.get(file_key)?.isLive ?? false;
	}

	liveEntries(): Array<[string, ActivityEntry]> {
		return [...this.entries].filter(([, e]) => e.isLive);
	}

	reset(): void {
		this.entries.clear();
		this.inFlight.clear();
	}

	size(): number {
		return this.entries.size;
	}

	/**
	 * Pulls a usable absolute path out of a tool's args object. Mirrors the
	 * key list in `extract_path_from_tool_result` (Python-side artifact_triggers).
	 */
	private resolvePath(args: unknown): string | null {
		if (!args || typeof args !== 'object') return null;
		const a = args as Record<string, unknown>;
		for (const k of ['path', 'filename', 'file_path', 'filepath']) {
			const v = a[k];
			if (typeof v === 'string' && v.trim().startsWith('/')) return v.trim();
		}
		return null;
	}
}
