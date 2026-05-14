// KEEP IN SYNC WITH platform/backend/myah/utils/artifact_triggers.py

import fixture from './artifact-triggers.fixture.json';
import { detectFileType } from './fileTypeRegistry';

export const ARTIFACT_TOOL_NAMES: readonly string[] = fixture.tool_names;

export function isArtifactTriggerTool(toolName: string): boolean {
	return ARTIFACT_TOOL_NAMES.includes(toolName);
}

export function isArtifactExtension(filenameOrPath: string): boolean {
	const entry = detectFileType(filenameOrPath);
	return entry?.capability === 'panel' || entry?.capability === 'both';
}

/**
 * True if the filename/path's extension is recognised by fileTypeRegistry —
 * any known kind (panel OR inline). Used as the regex-scan gate inside
 * extractPathFromToolResult and by ActivityTracker. The stricter
 * isArtifactExtension above (panel-only) remains the renderer-dispatch gate.
 *
 * Python-parity note: this matches the permissiveness of the Python-side
 * `_ARTIFACT_EXTENSIONS` frozenset which includes media after artifact
 * pane redesign Task 1.3. The TS-side asymmetry (between isArtifactExtension
 * and isKnownFileExtension) goes away when Phase 2B upgrades media entries
 * in fileTypeRegistry to capability:'both'.
 */
export function isKnownFileExtension(filenameOrPath: string): boolean {
	return detectFileType(filenameOrPath) !== undefined;
}

// Mirrors _TOOL_OUTPUT_PATH_RE in artifact_triggers.py.
// Matches absolute paths in known workspace prefixes ending in a 1-8 char extension.
// Used as a fallback when neither a bare-path string nor an explicit path/filename
// key is present (typical for execute_code / terminal results).
const TOOL_OUTPUT_PATH_RE =
	/(?:^|[\s\n\r\t([{>="'`])((?:\/data\/\.hermes\/cache|\/tmp|\/workspace|\/data|\/root|\/Users\/[^/\s]+|\/home\/[^/\s]+)\/[^\s<>'"`,]+?\.(?:[a-zA-Z0-9]{1,8}))(?=[\s<>'")\]}`]|$)/g;

function scanStringForArtifactPath(text: string): string | null {
	for (const match of text.matchAll(TOOL_OUTPUT_PATH_RE)) {
		const candidate = match[1];
		if (isKnownFileExtension(candidate)) return candidate;
	}
	return null;
}

export function extractPathFromToolResult(result: unknown): string | null {
	if (!result) return null;

	// String starting with /
	if (typeof result === 'string') {
		const trimmed = result.trim();
		if (trimmed.startsWith('/')) return trimmed;
		// Try parsing as JSON
		try {
			const parsed = JSON.parse(trimmed);
			return extractPathFromToolResult(parsed);
		} catch {
			// Fallback: scan the string body for an artifact-extension path.
			// Used for execute_code / terminal results whose stdout
			// mentions the saved file path.
			return scanStringForArtifactPath(trimmed);
		}
	}

	if (typeof result !== 'object') return null;
	const obj = result as Record<string, unknown>;

	// Known shapes: {path}, {filename}, {file_path}, {filepath}
	for (const key of ['path', 'filename', 'file_path', 'filepath']) {
		const val = obj[key];
		if (typeof val === 'string' && val.trim()) return val.trim();
	}

	// terminal/execute_code use 'output' for captured stdout — scan it.
	for (const key of ['output', 'stdout', 'result']) {
		const val = obj[key];
		if (typeof val === 'string') {
			const found = scanStringForArtifactPath(val);
			if (found) return found;
		}
	}

	// Double-stringified JSON
	for (const key of Object.keys(obj)) {
		const val = obj[key];
		if (typeof val === 'string') {
			try {
				const inner = JSON.parse(val);
				const path = extractPathFromToolResult(inner);
				if (path) return path;
			} catch {
				// not JSON
			}
		}
	}

	return null;
}
