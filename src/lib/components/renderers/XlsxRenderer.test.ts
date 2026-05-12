import { describe, it, expect, beforeEach, beforeAll } from 'vitest';
import { render, fireEvent, waitFor } from '@testing-library/svelte';
import * as XLSX from 'xlsx';
import XlsxRendererHarness from './__test__/XlsxRendererHarness.svelte';
import type { SelectionPayload, ToolbarItem } from '$lib/types/artifact';

// jsdom's Blob lacks .arrayBuffer(); polyfill it so the renderer can read content.
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

// Build a tiny in-memory workbook with the data the spec asserts on:
//   B2=100, B3=50, C2=200, C3=75 → sum = 425.
// We feed it to the renderer via a Blob containing the XLSX binary.
async function buildSheetBlob(): Promise<Blob> {
	const wb = XLSX.utils.book_new();
	const aoa = [
		['Header', 'Q1', 'Q2'],
		['Revenue', 100, 200],
		['Cost', 50, 75]
	];
	const ws = XLSX.utils.aoa_to_sheet(aoa);
	XLSX.utils.book_append_sheet(wb, ws, 'Sheet1');
	const arrayBuffer = XLSX.write(wb, { type: 'array', bookType: 'xlsx' });
	return new Blob([arrayBuffer], {
		type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
	});
}

// Multi-sheet workbook for tab-switching tests.
async function buildMultiSheetBlob(): Promise<Blob> {
	const wb = XLSX.utils.book_new();
	const sheet1 = XLSX.utils.aoa_to_sheet([
		['ItemA'],
		['SHEET_ONE_VALUE']
	]);
	XLSX.utils.book_append_sheet(wb, sheet1, 'Cash Flow Forecast');
	const sheet2 = XLSX.utils.aoa_to_sheet([
		['ItemB'],
		['SHEET_TWO_VALUE']
	]);
	XLSX.utils.book_append_sheet(wb, sheet2, 'Summary');
	const arrayBuffer = XLSX.write(wb, { type: 'array', bookType: 'xlsx' });
	return new Blob([arrayBuffer], {
		type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
	});
}

describe('XlsxRenderer', () => {
	let blob: Blob;

	beforeEach(async () => {
		blob = await buildSheetBlob();
	});

	it('renders the formula bar at top', async () => {
		const { container } = render(XlsxRendererHarness, {
			props: { content: blob, filename: 'test.xlsx' }
		});
		await waitFor(() => {
			expect(container.querySelector('[data-testid="formula-bar"]')).toBeInTheDocument();
		});
	});

	it('renders sheet tabs at bottom + status footer', async () => {
		const { container } = render(XlsxRendererHarness, {
			props: { content: blob, filename: 'test.xlsx' }
		});
		await waitFor(() => {
			expect(container.querySelector('[data-testid="sheet-tabs"]')).toBeInTheDocument();
			expect(container.querySelector('[data-testid="sheet-status"]')).toBeInTheDocument();
		});
	});

	it('emits select event with sheet-cells anchor on cell-range drag', async () => {
		const events: (SelectionPayload | null)[] = [];
		const { container } = render(XlsxRendererHarness, {
			props: {
				content: blob,
				filename: 'test.xlsx',
				onSelect: (payload) => events.push(payload)
			}
		});

		await waitFor(() => {
			expect(container.querySelector('[data-cell="B2"]')).toBeInTheDocument();
		});

		const start = container.querySelector('[data-cell="B2"]') as HTMLElement;
		const end = container.querySelector('[data-cell="C3"]') as HTMLElement;
		expect(start).not.toBeNull();
		expect(end).not.toBeNull();

		await fireEvent.mouseDown(start);
		await fireEvent.mouseEnter(end);
		await fireEvent.mouseUp(end);

		expect(events.length).toBeGreaterThan(0);
		const last = events[events.length - 1];
		expect(last).not.toBeNull();
		expect(last?.kind).toBe('sheet-cells');
		if (last && last.kind === 'sheet-cells') {
			expect(last.anchor.range).toBe('B2:C3');
		}
	});

	it('summary includes cell count + sum for numeric ranges', async () => {
		const events: (SelectionPayload | null)[] = [];
		const { container } = render(XlsxRendererHarness, {
			props: {
				content: blob,
				filename: 'test.xlsx',
				onSelect: (payload) => events.push(payload)
			}
		});

		await waitFor(() => {
			expect(container.querySelector('[data-cell="B2"]')).toBeInTheDocument();
		});

		const start = container.querySelector('[data-cell="B2"]') as HTMLElement;
		const end = container.querySelector('[data-cell="C3"]') as HTMLElement;

		await fireEvent.mouseDown(start);
		await fireEvent.mouseEnter(end);
		await fireEvent.mouseUp(end);

		const last = events[events.length - 1];
		expect(last).not.toBeNull();
		expect(last?.summary).toContain('4 cells');
		expect(last?.summary).toContain('sum: 425');
	});

	it('emits toolbar event on mount with reset-zoom item at overlay-tr', async () => {
		const toolbarEvents: ToolbarItem[][] = [];
		render(XlsxRendererHarness, {
			props: {
				content: blob,
				filename: 'test.xlsx',
				onToolbar: (items) => toolbarEvents.push(items)
			}
		});

		await waitFor(() => {
			expect(toolbarEvents.length).toBeGreaterThan(0);
		});

		const allItems = toolbarEvents.flat();
		const resetZoom = allItems.find((i) => i.id === 'reset-zoom');
		expect(resetZoom).toBeDefined();
		expect(resetZoom?.placement).toBe('overlay-tr');
	});

	// Regression: clicking a sheet tab must actually swap the rendered grid
	// to that sheet. Earlier the click mutated `activeSheet` but the
	// `$:` reactive that called `loadSheet()` did not list `activeSheet` as
	// a dependency, so the table never re-rendered.
	it('switching sheet tabs re-renders the grid with the other sheet content', async () => {
		const multi = await buildMultiSheetBlob();
		const { container } = render(XlsxRendererHarness, {
			props: { content: multi, filename: 'multi.xlsx' }
		});

		await waitFor(() => {
			expect(container.querySelector('[data-cell="A2"]')).toBeInTheDocument();
		});
		// First sheet's A2 cell.
		expect((container.querySelector('[data-cell="A2"]') as HTMLElement).textContent).toContain(
			'SHEET_ONE_VALUE'
		);

		// Click the "Summary" tab.
		const tabs = container.querySelectorAll('[data-testid="sheet-tabs"] button');
		expect(tabs.length).toBe(2);
		const summaryTab = Array.from(tabs).find((t) => t.textContent?.trim() === 'Summary');
		expect(summaryTab).toBeTruthy();
		await fireEvent.click(summaryTab as HTMLElement);

		await waitFor(() => {
			const cell = container.querySelector('[data-cell="A2"]') as HTMLElement | null;
			expect(cell?.textContent).toContain('SHEET_TWO_VALUE');
		});
	});

	// Regression: selecting cells must paint a visible blue tint on the
	// selected range AND a thicker outline on the active cell. Earlier the
	// code highlighted via helper-function calls inside the dynamic class
	// expression — Svelte didn't track the dependencies and cells stayed
	// unstyled.
	it('paints selection styles on cells inside the selected range', async () => {
		const { container } = render(XlsxRendererHarness, {
			props: { content: blob, filename: 'test.xlsx' }
		});

		await waitFor(() => {
			expect(container.querySelector('[data-cell="B2"]')).toBeInTheDocument();
		});

		const start = container.querySelector('[data-cell="B2"]') as HTMLElement;
		const end = container.querySelector('[data-cell="C3"]') as HTMLElement;
		await fireEvent.mouseDown(start);
		await fireEvent.mouseEnter(end);

		// Cells inside B2:C3 should carry the selection-fill class.
		for (const ref of ['B2', 'B3', 'C2', 'C3']) {
			const el = container.querySelector(`[data-cell="${ref}"]`) as HTMLElement;
			expect(el.className).toMatch(/bg-blue-500\/25/);
		}
		// The trailing cell (active) should also carry the outline.
		expect(end.className).toMatch(/outline-2/);
		// A cell OUTSIDE the range should not.
		const outside = container.querySelector('[data-cell="A1"]') as HTMLElement;
		expect(outside.className).not.toMatch(/bg-blue-500\/25/);
	});

	// Regression: clicking a column-letter header selects the full column.
	it('clicking a column header selects the whole column', async () => {
		const events: (SelectionPayload | null)[] = [];
		const { container } = render(XlsxRendererHarness, {
			props: {
				content: blob,
				filename: 'test.xlsx',
				onSelect: (p) => events.push(p)
			}
		});

		await waitFor(() => {
			expect(container.querySelector('[data-cell="B2"]')).toBeInTheDocument();
		});

		// Find the header for column B and click it.
		const headers = container.querySelectorAll('thead th');
		// First <th> is the corner; columns start at index 1.
		const colB = Array.from(headers).find((th) => th.textContent?.trim() === 'B');
		expect(colB).toBeTruthy();
		await fireEvent.mouseDown(colB as HTMLElement);

		// Last selection event should span the full column.
		const last = events[events.length - 1];
		expect(last?.kind).toBe('sheet-cells');
		if (last && last.kind === 'sheet-cells') {
			expect(last.anchor.range.startsWith('B1:B')).toBe(true);
		}
	});

	// Regression: clicking a row-number header selects the whole row.
	it('clicking a row header selects the whole row', async () => {
		const events: (SelectionPayload | null)[] = [];
		const { container } = render(XlsxRendererHarness, {
			props: {
				content: blob,
				filename: 'test.xlsx',
				onSelect: (p) => events.push(p)
			}
		});

		await waitFor(() => {
			expect(container.querySelector('[data-cell="B2"]')).toBeInTheDocument();
		});

		// Find the row-number cell for row 2 (second row, label "2").
		const rowHeaders = container.querySelectorAll('tbody td.excel-row-num');
		const row2 = Array.from(rowHeaders).find((td) => td.textContent?.trim() === '2');
		expect(row2).toBeTruthy();
		await fireEvent.mouseDown(row2 as HTMLElement);

		const last = events[events.length - 1];
		expect(last?.kind).toBe('sheet-cells');
		if (last && last.kind === 'sheet-cells') {
			// Row span starts at A2 (col 0) and ends at the last column on row 2.
			expect(last.anchor.range.startsWith('A2:')).toBe(true);
			expect(last.anchor.range.endsWith('2')).toBe(true);
		}
	});
});
