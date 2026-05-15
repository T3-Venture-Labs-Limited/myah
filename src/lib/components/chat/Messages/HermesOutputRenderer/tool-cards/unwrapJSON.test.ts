import { describe, it, expect } from 'vitest';
import { unwrapJSON } from './unwrapJSON';

describe('unwrapJSON', () => {
	it('parses a plain JSON object', () => {
		expect(unwrapJSON('{"x": 1}')).toEqual({ x: 1 });
	});

	it('unwraps a double-stringified JSON object', () => {
		expect(unwrapJSON('"{\\"x\\": 1}"')).toEqual({ x: 1 });
	});

	it('returns the original string on parse failure', () => {
		expect(unwrapJSON('not json')).toBe('not json');
	});

	it('parses a numeric literal', () => {
		expect(unwrapJSON('42')).toBe(42);
	});

	it('parses null', () => {
		expect(unwrapJSON('null')).toBeNull();
	});

	it('returns empty string when given empty string', () => {
		expect(unwrapJSON('')).toBe('');
	});

	it('unwraps a triple-stringified JSON object (three layers of JSON encoding)', () => {
		// 3-level deep: JSON.stringify(JSON.stringify(JSON.stringify({x:1})))
		const tripleStringified = JSON.stringify(JSON.stringify(JSON.stringify({ x: 1 })));
		expect(unwrapJSON(tripleStringified)).toEqual({ x: 1 });
	});
});
