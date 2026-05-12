import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import MiniPreview from './MiniPreview.svelte';
import type { ArtifactCardItem } from '$lib/types/contract';

function mk(kind: ArtifactCardItem['kind'], filename: string): ArtifactCardItem {
	return {
		type: 'artifact_card',
		id: 'card-1',
		filename,
		kind,
		mtime: 0
	};
}

describe('MiniPreview', () => {
	it('renders Spreadsheet · filename for xlsx', () => {
		render(MiniPreview, { props: { item: mk('xlsx', 'budget.xlsx') } });
		expect(screen.getByText('Spreadsheet · budget.xlsx')).toBeInTheDocument();
	});

	it('renders Document · filename for docx', () => {
		render(MiniPreview, { props: { item: mk('docx', 'plan.docx') } });
		expect(screen.getByText('Document · plan.docx')).toBeInTheDocument();
	});

	it('renders Code · filename for code', () => {
		render(MiniPreview, { props: { item: mk('code', 'app.py') } });
		expect(screen.getByText('Code · app.py')).toBeInTheDocument();
	});

	it('renders Image · filename for image', () => {
		render(MiniPreview, { props: { item: mk('image', 'chart.png') } });
		expect(screen.getByText('Image · chart.png')).toBeInTheDocument();
	});

	it('falls back to File for text kind', () => {
		render(MiniPreview, { props: { item: mk('text', 'notes.txt') } });
		expect(screen.getByText('File · notes.txt')).toBeInTheDocument();
	});
});
