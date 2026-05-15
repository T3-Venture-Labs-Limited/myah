// Recursively unwrap a value that may be double-stringified JSON.
// Returns the innermost non-string value, or the original string on parse failure.
export function unwrapJSON(str: string): unknown {
	try {
		const parsed = JSON.parse(str);
		if (typeof parsed === 'string') return unwrapJSON(parsed);
		return parsed;
	} catch {
		return str;
	}
}
