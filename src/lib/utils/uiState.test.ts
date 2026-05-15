import { describe, it, expect } from 'vitest';
import { assembleUIState, buildRefContextBlock } from './uiState';
import type { SelectionPayload } from '$lib/types/artifact';

describe('assembleUIState', () => {
	it('returns empty arrays for empty inputs', () => {
		const result = assembleUIState([], new Map());
		expect(result).toEqual({ selectionRefs: [], pendingEdits: [] });
	});

	it('truncates code-lines preview at 1500 chars', () => {
		const longPreview = 'x'.repeat(2000);
		const refs: Array<SelectionPayload & { id: string; filename: string; file_key?: string }> = [
			{
				id: 'r1',
				kind: 'code-lines',
				anchor: { startLine: 1, endLine: 100, language: 'python' },
				preview: longPreview,
				summary: '100 lines',
				filename: 'foo.py',
				file_key: 'path:/abs/foo.py'
			}
		];
		const result = assembleUIState(refs, new Map());
		expect(result.selectionRefs).toHaveLength(1);
		expect(result.selectionRefs[0].preview).toBeDefined();
		const pv = result.selectionRefs[0].preview as string;
		expect(pv.length).toBeLessThan(2100);
		expect(pv).toContain('content truncated');
		expect(pv).toContain('500 chars omitted');
	});

	it('truncates doc-text preview at 1500 chars', () => {
		const longPreview = 'a'.repeat(3000);
		const refs: Array<SelectionPayload & { id: string; filename: string; file_key?: string }> = [
			{
				id: 'r2',
				kind: 'doc-text',
				anchor: { startOffset: 0, endOffset: 3000, contextFingerprint: 'fp' },
				preview: longPreview,
				summary: 'doc',
				filename: 'doc.md',
				file_key: 'path:/abs/doc.md'
			}
		];
		const result = assembleUIState(refs, new Map());
		const pv = result.selectionRefs[0].preview as string;
		expect(pv.length).toBeLessThan(3100);
		expect(pv).toContain('content truncated');
	});

	it('truncates pendingEdits diff at 3000 chars', () => {
		const longDiff = 'd'.repeat(4000);
		const edits = new Map<string, { filename: string; diff: string }>([
			['path:/abs/a.py', { filename: 'a.py', diff: longDiff }]
		]);
		const result = assembleUIState([], edits);
		expect(result.pendingEdits).toHaveLength(1);
		expect(result.pendingEdits[0].diff.length).toBeLessThan(4100);
		expect(result.pendingEdits[0].diff).toContain('diff truncated');
		expect(result.pendingEdits[0].diff).toContain('1000 chars omitted');
	});

	it('omits preview for image-region selections', () => {
		const refs: Array<SelectionPayload & { id: string; filename: string; file_key?: string }> = [
			{
				id: 'i1',
				kind: 'image-region',
				anchor: { xPct: 0.1, yPct: 0.1, wPct: 0.5, hPct: 0.5 },
				preview: { dataUrl: 'data:image/png;base64,xxx' },
				summary: 'image region',
				filename: 'pic.png',
				file_key: 'file_id:abc'
			}
		];
		const result = assembleUIState(refs, new Map());
		expect(result.selectionRefs[0].preview).toBeUndefined();
		expect(result.selectionRefs[0].file_key).toBe('file_id:abc');
	});

	it('omits preview for video-region selections', () => {
		const refs: Array<SelectionPayload & { id: string; filename: string; file_key?: string }> = [
			{
				id: 'v1',
				kind: 'video-region',
				anchor: { startSeconds: 1, endSeconds: 5 },
				preview: { thumbnailDataUrl: 'data:image/jpeg;base64,xxx' },
				summary: 'video region',
				filename: 'clip.mp4',
				file_key: 'file_id:vid'
			}
		];
		const result = assembleUIState(refs, new Map());
		expect(result.selectionRefs[0].preview).toBeUndefined();
	});

	it('serializes sheet-cells preview as TSV', () => {
		const refs: Array<SelectionPayload & { id: string; filename: string; file_key?: string }> = [
			{
				id: 's1',
				kind: 'sheet-cells',
				anchor: { sheet: 'Sheet1', range: 'A1:B2' },
				preview: [
					['a', 'b'],
					['1', '2']
				],
				summary: '2x2',
				filename: 'data.xlsx',
				file_key: 'path:/abs/data.xlsx'
			}
		];
		const result = assembleUIState(refs, new Map());
		expect(result.selectionRefs[0].preview).toBe('a\tb\n1\t2');
	});

	it('preserves file_key when present and falls back when absent', () => {
		const refs: Array<SelectionPayload & { id: string; filename: string; file_key?: string }> = [
			{
				id: 'r1',
				kind: 'code-lines',
				anchor: { startLine: 1, endLine: 2, language: 'js' },
				preview: 'x',
				summary: 's',
				filename: 'a.js',
				file_key: 'path:/abs/a.js'
			},
			{
				id: 'r2',
				kind: 'code-lines',
				anchor: { startLine: 1, endLine: 2, language: 'js' },
				preview: 'y',
				summary: 's',
				filename: 'b.js'
			}
		];
		const result = assembleUIState(refs, new Map());
		expect(result.selectionRefs[0].file_key).toBe('path:/abs/a.js');
		expect(result.selectionRefs[1].file_key).toBe('path:/unknown/b.js');
	});

	it('does not truncate short previews or diffs', () => {
		const refs: Array<SelectionPayload & { id: string; filename: string; file_key?: string }> = [
			{
				id: 'r',
				kind: 'doc-text',
				anchor: { startOffset: 0, endOffset: 5, contextFingerprint: 'fp' },
				preview: 'short',
				summary: 's',
				filename: 'd.md',
				file_key: 'path:/d.md'
			}
		];
		const edits = new Map<string, { filename: string; diff: string }>([
			['k', { filename: 'a', diff: 'small diff' }]
		]);
		const result = assembleUIState(refs, edits);
		expect(result.selectionRefs[0].preview).toBe('short');
		expect(result.pendingEdits[0].diff).toBe('small diff');
	});
});

describe('buildRefContextBlock', () => {
	it('returns empty string when no refs', () => {
		expect(buildRefContextBlock([])).toBe('');
	});

	it('wraps refs in [USER_REFERENCED] sentinels', () => {
		const block = buildRefContextBlock([
			{
				id: 'r1',
				kind: 'code-lines',
				anchor: { startLine: 1, endLine: 3, language: 'python' },
				preview: 'def foo():\n    pass',
				summary: 'foo.py · L1-L3 · 3 lines',
				filename: 'foo.py'
			}
		]);
		expect(block.startsWith('[USER_REFERENCED]')).toBe(true);
		expect(block).toContain('[/USER_REFERENCED]');
		expect(block).toContain('foo.py');
		expect(block).toContain('def foo():');
		expect(block).toContain('```python');
	});

	it('renders sheet-cells as TSV inside a fenced block', () => {
		const block = buildRefContextBlock([
			{
				id: 's1',
				kind: 'sheet-cells',
				anchor: { sheet: 'Sheet1', range: 'A1:B2' },
				preview: [
					['name', 'qty'],
					['apple', '3']
				],
				summary: 'Sheet1 · A1:B2 · 4 cells',
				filename: 'data.csv'
			}
		]);
		expect(block).toContain('```tsv');
		expect(block).toContain('name\tqty');
		expect(block).toContain('apple\t3');
	});

	it('describes image-region without leaking the data URL', () => {
		const block = buildRefContextBlock([
			{
				id: 'i1',
				kind: 'image-region',
				anchor: { xPct: 10, yPct: 20, wPct: 50, hPct: 60 },
				preview: { dataUrl: 'data:image/png;base64,XXX' },
				summary: 'pic.png',
				filename: 'pic.png'
			}
		]);
		expect(block).toContain('image region');
		expect(block).not.toContain('data:image/png');
	});

	it('truncates long previews', () => {
		const long = 'x'.repeat(2000);
		const block = buildRefContextBlock([
			{
				id: 'r',
				kind: 'doc-text',
				anchor: { startOffset: 0, endOffset: 2000, contextFingerprint: '' },
				preview: long,
				summary: 'doc',
				filename: 'doc.md'
			}
		]);
		expect(block).toContain('content truncated');
		expect(block.length).toBeLessThan(2300);
	});

	it('emits one block for multiple refs', () => {
		const block = buildRefContextBlock([
			{
				id: 'a',
				kind: 'code-lines',
				anchor: { startLine: 1, endLine: 1, language: 'py' },
				preview: 'one',
				summary: 'a.py · L1',
				filename: 'a.py'
			},
			{
				id: 'b',
				kind: 'code-lines',
				anchor: { startLine: 1, endLine: 1, language: 'py' },
				preview: 'two',
				summary: 'b.py · L1',
				filename: 'b.py'
			}
		]);
		// Single open + close pair, both refs surfaced inside.
		expect(block.match(/\[USER_REFERENCED\]/g)?.length).toBe(1);
		expect(block.match(/\[\/USER_REFERENCED\]/g)?.length).toBe(1);
		expect(block).toContain('a.py');
		expect(block).toContain('b.py');
	});
});
