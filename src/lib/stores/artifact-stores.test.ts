import { describe, it, expect } from 'vitest';
import { get } from 'svelte/store';
import {
	artifactSelection,
	artifactPendingEdits,
	artifactOpenFiles,
	artifactActiveTabIdx,
	artifactPaneOpen,
	currentArtifactFile,
	openArtifactInPane,
	closeArtifactPane
} from './index';

describe('artifact stores', () => {
	it('starts with empty/closed state', () => {
		artifactOpenFiles.set([]);
		artifactActiveTabIdx.set(-1);
		artifactPaneOpen.set(false);
		artifactSelection.set(null);
		artifactPendingEdits.set(new Map());

		expect(get(artifactOpenFiles)).toEqual([]);
		expect(get(artifactActiveTabIdx)).toBe(-1);
		expect(get(artifactPaneOpen)).toBe(false);
		expect(get(artifactSelection)).toBeNull();
		expect(get(artifactPendingEdits).size).toBe(0);
	});

	it('currentArtifactFile is derived: returns active open file', () => {
		artifactOpenFiles.set([
			{ file_key: 'path:/tmp/a.py', filename: 'a.py', path: '/tmp/a.py', source: 'agent-tool' },
			{ file_key: 'path:/tmp/b.py', filename: 'b.py', path: '/tmp/b.py', source: 'user-click' }
		]);
		artifactActiveTabIdx.set(1);
		expect(get(currentArtifactFile)?.filename).toBe('b.py');
	});

	it('currentArtifactFile is null when explorer view active', () => {
		artifactOpenFiles.set([
			{ file_key: 'path:/tmp/a.py', filename: 'a.py', path: '/tmp/a.py', source: 'agent-tool' }
		]);
		artifactActiveTabIdx.set(-1);
		expect(get(currentArtifactFile)).toBeNull();
	});

	it('currentArtifactFile is null when index out of range', () => {
		artifactOpenFiles.set([]);
		artifactActiveTabIdx.set(0);
		expect(get(currentArtifactFile)).toBeNull();
	});

	describe('openArtifactInPane', () => {
		it('appends a new file and focuses its tab; opens pane', () => {
			artifactOpenFiles.set([]);
			artifactActiveTabIdx.set(-1);
			artifactPaneOpen.set(false);

			openArtifactInPane({
				file_key: 'path:/tmp/foo.py',
				path: '/tmp/foo.py',
				filename: 'foo.py',
				source: 'user-click'
			});

			expect(get(artifactOpenFiles)).toHaveLength(1);
			expect(get(artifactOpenFiles)[0].file_key).toBe('path:/tmp/foo.py');
			expect(get(artifactActiveTabIdx)).toBe(0);
			expect(get(artifactPaneOpen)).toBe(true);
		});

		it('focuses the existing tab if file_key already open (no duplicate)', () => {
			artifactOpenFiles.set([
				{
					file_key: 'path:/tmp/foo.py',
					filename: 'foo.py',
					path: '/tmp/foo.py',
					source: 'agent-tool'
				},
				{
					file_key: 'path:/tmp/bar.py',
					filename: 'bar.py',
					path: '/tmp/bar.py',
					source: 'agent-tool'
				}
			]);
			artifactActiveTabIdx.set(1);

			openArtifactInPane({
				file_key: 'path:/tmp/foo.py',
				path: '/tmp/foo.py',
				filename: 'foo.py',
				source: 'user-click'
			});

			expect(get(artifactOpenFiles)).toHaveLength(2); // unchanged
			expect(get(artifactActiveTabIdx)).toBe(0); // jumped to existing tab
		});
	});

	describe('closeArtifactPane', () => {
		it('clears active idx, closes pane, clears selection; preserves openFiles', () => {
			artifactOpenFiles.set([
				{ file_key: 'path:/tmp/a.py', filename: 'a.py', path: '/tmp/a.py', source: 'agent-tool' }
			]);
			artifactActiveTabIdx.set(0);
			artifactPaneOpen.set(true);
			artifactSelection.set({
				kind: 'doc-text',
				anchor: { startOffset: 0, endOffset: 5, contextFingerprint: 'abc' },
				preview: 'hello',
				summary: '1 paragraph · 1 word'
			});

			closeArtifactPane();

			expect(get(artifactActiveTabIdx)).toBe(-1);
			expect(get(artifactPaneOpen)).toBe(false);
			expect(get(artifactSelection)).toBeNull();
			expect(get(artifactOpenFiles)).toHaveLength(1); // preserved
		});
	});
});
