import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';
import InlineArtifactPreview from './InlineArtifactPreview.svelte';
import {
	artifactOpenFiles,
	artifactActiveTabIdx,
	artifactPaneOpen
} from '$lib/stores';
import type { ArtifactCardItem } from '$lib/types/contract';

const xlsxCard: ArtifactCardItem = {
	type: 'artifact_card',
	id: 'card-1',
	file_id: 'abc-123',
	filename: 'forecast.xlsx',
	mime: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
	mtime: 1234567890,
	kind: 'xlsx',
	summary: 'Q3-Q4 forecast'
};

const pathOnlyCard: ArtifactCardItem = {
	type: 'artifact_card',
	id: 'card-2',
	path: '/data/.hermes/output/notes.md',
	filename: 'notes.md',
	mime: 'text/markdown',
	mtime: 1234567891,
	kind: 'markdown'
};

describe('InlineArtifactPreview', () => {
	beforeEach(() => {
		artifactOpenFiles.set([]);
		artifactActiveTabIdx.set(-1);
		artifactPaneOpen.set(false);
	});

	it('renders filename, mime, summary, Open + Download', () => {
		render(InlineArtifactPreview, { props: { item: xlsxCard } });
		expect(screen.getByText('forecast.xlsx')).toBeInTheDocument();
		expect(screen.getByText(/spreadsheetml/)).toBeInTheDocument();
		expect(screen.getByText('Q3-Q4 forecast')).toBeInTheDocument();
		expect(screen.getByTestId('inline-artifact-open')).toBeInTheDocument();
		expect(screen.getByTestId('inline-artifact-download')).toBeInTheDocument();
	});

	it('clicking Open appends to artifactOpenFiles, sets active tab, opens pane', async () => {
		render(InlineArtifactPreview, { props: { item: xlsxCard } });
		await fireEvent.click(screen.getByTestId('inline-artifact-open'));

		const files = get(artifactOpenFiles);
		expect(files).toHaveLength(1);
		expect(files[0]).toMatchObject({
			file_key: 'file_id:abc-123',
			file_id: 'abc-123',
			filename: 'forecast.xlsx',
			source: 'agent-tool'
		});
		expect(get(artifactActiveTabIdx)).toBe(0);
		expect(get(artifactPaneOpen)).toBe(true);
	});

	it('clicking Open on path-only card uses path-based file_key', async () => {
		render(InlineArtifactPreview, { props: { item: pathOnlyCard } });
		await fireEvent.click(screen.getByTestId('inline-artifact-open'));
		expect(get(artifactOpenFiles)[0].file_key).toBe('path:/data/.hermes/output/notes.md');
	});

	it('clicking Open when file already open jumps to existing tab without duplicating', async () => {
		artifactOpenFiles.set([
			{
				file_key: 'file_id:abc-123',
				file_id: 'abc-123',
				filename: 'forecast.xlsx',
				mtime: 0,
				source: 'agent-tool'
			},
			{
				file_key: 'path:/tmp/other',
				path: '/tmp/other',
				filename: 'other',
				mtime: 0,
				source: 'agent-tool'
			}
		]);
		artifactActiveTabIdx.set(1);

		render(InlineArtifactPreview, { props: { item: xlsxCard } });
		await fireEvent.click(screen.getByTestId('inline-artifact-open'));

		expect(get(artifactOpenFiles)).toHaveLength(2); // unchanged
		expect(get(artifactActiveTabIdx)).toBe(0); // jumped to existing
	});

	it('Download link points at /api/v1/files/{id}/content for file_id-backed cards', () => {
		render(InlineArtifactPreview, { props: { item: xlsxCard } });
		const link = screen.getByTestId('inline-artifact-download') as HTMLAnchorElement;
		expect(link.getAttribute('href')).toBe('/api/v1/files/abc-123/content');
		expect(link.getAttribute('download')).toBe('forecast.xlsx');
	});

	it('Download link uses /api/v1/hermes/media?path= for path-only cards', () => {
		render(InlineArtifactPreview, { props: { item: pathOnlyCard } });
		const link = screen.getByTestId('inline-artifact-download') as HTMLAnchorElement;
		expect(link.getAttribute('href')).toBe(
			'/api/v1/hermes/media?path=' + encodeURIComponent('/data/.hermes/output/notes.md')
		);
	});
});
