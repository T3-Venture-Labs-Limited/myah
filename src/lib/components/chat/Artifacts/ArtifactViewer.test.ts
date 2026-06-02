import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/svelte';
import ArtifactViewer from './ArtifactViewer.svelte';
import type { ArtifactFile } from '$lib/types/artifact';

vi.mock('$lib/components/renderers/MarkdownRenderer.svelte', async () => {
	const StubRenderer = (await import('./__test__/RendererSpy.svelte')).default;
	return { default: StubRenderer };
});

const mkFile = (id: string, name: string): ArtifactFile => ({
	file_key: `file_id:${id}`,
	file_id: id,
	filename: name,
	mime: 'text/markdown',
	mtime: 0,
	source: 'user-click'
});

describe('ArtifactViewer', () => {
	it('remounts the renderer when file_key changes', async () => {
		const fileA = mkFile('a-id', 'a.md');
		const fileB = mkFile('b-id', 'b.md');

		const { getByTestId, rerender } = render(ArtifactViewer, {
			props: { file: fileA, token: 't' }
		});

		const stubA = await vi.waitFor(() => getByTestId('renderer-spy'));
		const initialMountId = stubA.getAttribute('data-mount-id');
		expect(initialMountId).toBeTruthy();
		expect(stubA.getAttribute('data-file-id')).toBe('a-id');

		await rerender({ file: fileB, token: 't' });

		const stubB = await vi.waitFor(() => {
			const el = getByTestId('renderer-spy');
			if (el.getAttribute('data-file-id') !== 'b-id') throw new Error('not yet switched');
			return el;
		});
		const remountedId = stubB.getAttribute('data-mount-id');
		expect(remountedId).not.toBe(initialMountId);
	});
});
