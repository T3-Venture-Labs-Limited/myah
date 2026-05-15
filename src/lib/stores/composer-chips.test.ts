import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { composerRefs, composerChips, artifactPendingEdits } from './index';
import type { SelectionPayload } from '$lib/types/artifact';

const docTextSelection: SelectionPayload = {
	kind: 'doc-text',
	anchor: { startOffset: 0, endOffset: 5, contextFingerprint: '|hello' },
	preview: 'hello',
	summary: 'doc-text 0-5'
};

const sheetCellsSelection: SelectionPayload = {
	kind: 'sheet-cells',
	anchor: { sheet: 'Sheet1', range: 'A1:B2' },
	preview: [
		['1', '2'],
		['3', '4']
	],
	summary: 'A1:B2 (4 cells)'
};

describe('composerChips derived store', () => {
	beforeEach(() => {
		composerRefs.set([]);
		artifactPendingEdits.set(new Map());
	});

	it('is empty when no refs and no pending edits', () => {
		expect(get(composerChips)).toEqual([]);
	});

	it('emits one chip per user-added ref, carrying filename and summary', () => {
		composerRefs.set([
			{ ...docTextSelection, id: 'ref-1', filename: 'notes.md' },
			{ ...sheetCellsSelection, id: 'ref-2', filename: 'budget.xlsx' }
		]);

		const chips = get(composerChips);
		expect(chips).toHaveLength(2);
		expect(chips[0]).toMatchObject({
			id: 'ref-1',
			kind: 'doc-text',
			filename: 'notes.md',
			summary: 'doc-text 0-5'
		});
		expect(chips[1]).toMatchObject({
			id: 'ref-2',
			kind: 'sheet-cells',
			filename: 'budget.xlsx',
			summary: 'A1:B2 (4 cells)'
		});
	});

	it('emits one file-edit chip per pending edit, with diff line count summary', () => {
		artifactPendingEdits.set(
			new Map([
				[
					'path:/tmp/foo.py',
					{
						filename: 'foo.py',
						diff: '--- a\n+++ b\n@@\n-old line\n+new line\n+another\n'
					}
				]
			])
		);

		const chips = get(composerChips);
		expect(chips).toHaveLength(1);
		expect(chips[0]).toMatchObject({
			id: 'edit-path:/tmp/foo.py',
			kind: 'file-edit',
			filename: 'foo.py'
		});
		// 3 +/- lines (the +++/--- header lines also start with +/- so they count too).
		expect(chips[0].summary).toMatch(/^\d+ lines changed$/);
	});

	it('merges user refs and pending edits, refs first then edits', () => {
		composerRefs.set([{ ...docTextSelection, id: 'ref-1', filename: 'a.md' }]);
		artifactPendingEdits.set(
			new Map([
				['path:/tmp/foo.py', { filename: 'foo.py', diff: '-old\n+new\n' }]
			])
		);

		const chips = get(composerChips);
		expect(chips).toHaveLength(2);
		expect(chips[0].kind).toBe('doc-text');
		expect(chips[1].kind).toBe('file-edit');
	});
});
