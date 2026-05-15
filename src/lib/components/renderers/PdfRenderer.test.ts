import { describe, it, expect, vi, beforeAll } from 'vitest';
import { render } from '@testing-library/svelte';
import PdfRenderer from './PdfRenderer.svelte';
import type { ToolbarItem } from '$lib/types/artifact';

beforeAll(() => {
	if (!Blob.prototype.arrayBuffer) {
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		(Blob.prototype as any).arrayBuffer = async function () {
			const text = await (this as Blob).text();
			const buf = new ArrayBuffer(text.length);
			const view = new Uint8Array(buf);
			for (let i = 0; i < text.length; i++) view[i] = text.charCodeAt(i);
			return buf;
		};
	}
});

// PDFViewer has heavy pdfjs-dist deps; stub it for unit tests.
vi.mock('$lib/components/common/PDFViewer.svelte', async () => {
	const Stub = (await import('./__test__/PDFViewerStub.svelte')).default;
	return { default: Stub };
});

describe('PdfRenderer', () => {
	const baseProps = {
		filename: 'doc.pdf',
		file_id: 'abc-123',
		editable: false
	};

	it('wraps PDFViewer in gray-inset container', async () => {
		const { container } = render(PdfRenderer, { props: baseProps });
		for (let i = 0; i < 10; i++) {
			if (container.querySelector('[data-testid="pdf-inset"]')) break;
			await new Promise((r) => setTimeout(r, 25));
		}
		const inset = container.querySelector('[data-testid="pdf-inset"]');
		expect(inset).toBeInTheDocument();
		expect(inset?.className ?? '').toMatch(/bg-gray-700|bg-gray-800/);
	});

	it('emits page-nav + zoom toolbar items', async () => {
		const { default: Harness } = await import('./__test__/PdfRendererHarness.svelte');
		const items: ToolbarItem[] = [];
		render(Harness, {
			props: {
				rendererProps: baseProps,
				onToolbar: (e: ToolbarItem[]) => items.push(...e)
			}
		});
		for (let i = 0; i < 10; i++) {
			if (items.length >= 4) break;
			await new Promise((r) => setTimeout(r, 25));
		}
		const ids = items.map((i) => i.id);
		expect(ids).toContain('pdf-prev');
		expect(ids).toContain('pdf-next');
		expect(ids).toContain('pdf-zoom-in');
		expect(ids).toContain('pdf-zoom-out');
		expect(items.find((i) => i.id === 'pdf-prev')?.placement).toBe('top');
		expect(items.find((i) => i.id === 'pdf-zoom-in')?.placement).toBe('overlay-tr');
	});
});
