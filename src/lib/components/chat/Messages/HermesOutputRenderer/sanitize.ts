// Frontend content sanitization for the Hermes output renderer.
// The agent/model produces text that may contain internal markers, control
// characters, and code execution blocks that are not user-facing. These
// functions strip them at render time so the frontend — not the backend —
// is the authority on what's visible.

/**
 * Strip <ctrl##> control character tokens that some models emit.
 */
export function stripControlTokens(text: string): string {
	return text.replace(/<ctrl\d{1,4}>/g, '');
}

/**
 * Strip <execute_code>...</execute_code> blocks.
 */
export function stripExecuteCodeBlocks(text: string): string {
	return text.replace(/<execute_code>[\s\S]*?<\/execute_code>/g, '');
}

/**
 * Strip [RENDER_UI]{json}[/RENDER_UI] markers.
 */
export function stripRenderUIMarkers(text: string): string {
	return text.replace(/\[RENDER_UI\][\s\S]*?\[\/RENDER_UI\]/g, '');
}

/**
 * Collapse excessive whitespace left after stripping.
 */
export function collapseWhitespace(text: string): string {
	return text.replace(/\n{3,}/g, '\n\n');
}

/**
 * Full sanitization pipeline for message text.
 */
export function sanitizeMessageText(text: string): string {
	let result = text;
	result = stripControlTokens(result);
	result = stripExecuteCodeBlocks(result);
	result = stripRenderUIMarkers(result);
	result = collapseWhitespace(result);
	return result.trim();
}
