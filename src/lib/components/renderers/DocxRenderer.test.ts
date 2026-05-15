import { describe, it, expect, vi, beforeAll } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';
import DocxRendererHarness from './__test__/DocxRendererHarness.svelte';
import type { ToolbarItem } from '$lib/types/artifact';

// jsdom's Blob lacks .arrayBuffer(); polyfill it so mammoth can read content.
beforeAll(() => {
	if (typeof Blob.prototype.arrayBuffer !== 'function') {
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		(Blob.prototype as any).arrayBuffer = function (): Promise<ArrayBuffer> {
			return new Promise((resolve, reject) => {
				const reader = new FileReader();
				reader.onload = () => resolve(reader.result as ArrayBuffer);
				reader.onerror = () => reject(reader.error);
				reader.readAsArrayBuffer(this as Blob);
			});
		};
	}
});

vi.mock('mammoth', () => ({
	default: { convertToHtml: vi.fn(async () => ({ value: '<p>Hello world</p>' })) },
	convertToHtml: vi.fn(async () => ({ value: '<p>Hello world</p>' }))
}));

describe('DocxRenderer', () => {
	const baseProps = {
		filename: 'doc.docx',
		content: new Blob(['stub'])
	};

	it('renders content inside a paper card on inset background', async () => {
		const { container } = render(DocxRendererHarness, { props: baseProps });
		await waitFor(() => {
			expect(container.querySelector('[data-testid="docx-paper-card"]')).toBeInTheDocument();
		});
	});

	it('marks the paper card as a selection listener', async () => {
		const { container } = render(DocxRendererHarness, { props: baseProps });
		await waitFor(() => {
			const card = container.querySelector('[data-testid="docx-paper-card"]');
			expect(card?.getAttribute('data-listens-for-selection')).toBe('true');
		});
	});

	it('emits toolbar event with high-fidelity toggle item at placement: top', async () => {
		const items: ToolbarItem[] = [];
		render(DocxRendererHarness, {
			props: {
				...baseProps,
				onToolbar: (toolbarItems: ToolbarItem[]) => items.push(...toolbarItems)
			}
		});

		await waitFor(() => {
			expect(items.find((x) => x.id === 'docx-fidelity')).toBeDefined();
		});

		const fidelityItem = items.find((i) => i.id === 'docx-fidelity');
		expect(fidelityItem?.placement).toBe('top');
	});
});
