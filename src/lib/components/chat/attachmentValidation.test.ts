import { describe, expect, it } from 'vitest';
import { appendComposerFile, appendComposerFiles, ATTACH_MAX_AGGREGATE_BYTES } from './attachmentValidation';

describe('composer attachment validation', () => {
	it('rejects duplicate file ids without changing the current attachments', () => {
		const existing = [{ id: 'file-1', name: 'report.txt', size: 12 }];

		const result = appendComposerFile(existing, { id: 'file-1', name: 'report.txt', size: 12 });

		expect(result.status).toBe('duplicate');
		expect(result.files).toBe(existing);
	});

	it('rejects attachments that would exceed the aggregate 80 MB limit', () => {
		const existing = [{ id: 'file-1', name: 'large.bin', size: ATTACH_MAX_AGGREGATE_BYTES - 10 }];

		const result = appendComposerFile(existing, { id: 'file-2', name: 'too-large.bin', size: 11 });

		expect(result.status).toBe('too-large');
		expect(result.files).toBe(existing);
	});

	it('applies the same duplicate and size checks to pending file handoff batches', () => {
		const existing = [{ id: 'file-1', name: 'already.txt', size: 10 }];

		const result = appendComposerFiles(existing, [
			{ id: 'file-1', name: 'already.txt', size: 10 },
			{ id: 'file-2', name: 'ok.txt', size: 20 },
			{ id: 'file-3', name: 'huge.bin', size: ATTACH_MAX_AGGREGATE_BYTES }
		]);

		expect(result.files.map((file) => file.id)).toEqual(['file-1', 'file-2']);
		expect(result.results.map((item) => item.status)).toEqual(['duplicate', 'attached', 'too-large']);
	});
});
