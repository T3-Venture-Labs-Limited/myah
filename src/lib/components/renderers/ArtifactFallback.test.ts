import { describe, expect, test } from 'vitest';

// Pure function test of the URL builder logic
describe('ArtifactFallback URL building', () => {
	test('uses file_id URL when file_id provided', () => {
		const file_id = 'abc123';
		const path = undefined;
		const url = file_id
			? `/api/v1/files/${file_id}/content`
			: path
				? `/api/v1/hermes/media?path=${encodeURIComponent(path)}`
				: null;
		expect(url).toBe('/api/v1/files/abc123/content');
	});

	test('falls back to hermes media URL when only path provided', () => {
		const file_id = undefined;
		const path = '/root/foo.xlsx';
		const url = file_id
			? `/api/v1/files/${file_id}/content`
			: path
				? `/api/v1/hermes/media?path=${encodeURIComponent(path)}`
				: null;
		expect(url).toBe('/api/v1/hermes/media?path=%2Froot%2Ffoo.xlsx');
	});

	test('returns null when neither file_id nor path provided', () => {
		const file_id = undefined;
		const path = undefined;
		const url = file_id
			? `/api/v1/files/${file_id}/content`
			: path
				? `/api/v1/hermes/media?path=${encodeURIComponent(path)}`
				: null;
		expect(url).toBeNull();
	});
});

describe('ArtifactFallback error message extraction', () => {
	const extractMessage = (e: Error | string): string =>
		e instanceof Error ? e.message : String(e);

	test('extracts message from Error object', () => {
		expect(extractMessage(new Error('something failed'))).toBe('something failed');
	});

	test('coerces string to message', () => {
		expect(extractMessage('plain string error')).toBe('plain string error');
	});
});
