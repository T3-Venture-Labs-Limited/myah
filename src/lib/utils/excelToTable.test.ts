import { describe, it, expect } from 'vitest';
import * as XLSX from 'xlsx';
import { excelToTable } from './excelToTable';

/**
 * Build a minimal worksheet with one cell set to the given value.
 */
function makeWorksheet(cells: Record<string, XLSX.CellObject>, ref: string): XLSX.WorkSheet {
	const ws: XLSX.WorkSheet = { '!ref': ref };
	for (const [addr, cell] of Object.entries(cells)) {
		ws[addr] = cell;
	}
	return ws;
}

describe('excelToTable', () => {
	it('returns formula, value, and type for a formula cell', () => {
		const ws = makeWorksheet(
			{
				A1: { v: 1, t: 'n' },
				A2: { v: 2, t: 'n' },
				A3: { v: 3, t: 'n' },
				A4: { v: 6, t: 'n' },
				A5: { v: 55, t: 'n', f: 'SUM(A1:A10)' }
			},
			'A1:A5'
		);

		const result = excelToTable(ws);
		const lastRow = result.rows[result.rows.length - 1];
		const cell = lastRow[0];

		expect(cell.formula).toBe('SUM(A1:A10)');
		expect(cell.value).toBe(55);
		expect(cell.type).toBe('n');
	});

	it('returns formula: null for a plain value cell', () => {
		const ws = makeWorksheet({ A1: { v: 'hello', t: 's' } }, 'A1:A1');

		const result = excelToTable(ws);
		expect(result.rows[0][0].formula).toBeNull();
		expect(result.rows[0][0].value).toBe('hello');
	});

	it('returns value: null and formula: null for an empty cell address', () => {
		// Worksheet ref covers B2 but B2 is not present — should be empty
		const ws: XLSX.WorkSheet = {
			'!ref': 'A1:B2',
			A1: { v: 'a', t: 's' }
		};

		const result = excelToTable(ws);
		// Row 0, col 1 (B1) — not set in worksheet
		const emptyCell = result.rows[0][1];
		expect(emptyCell.value).toBeNull();
		expect(emptyCell.formula).toBeNull();
		expect(emptyCell.type).toBe('s');
	});

	it('produces correct columnLetters for multi-column range', () => {
		const ws = makeWorksheet(
			{
				A1: { v: 1, t: 'n' },
				B1: { v: 2, t: 'n' },
				C1: { v: 3, t: 'n' }
			},
			'A1:C1'
		);

		const result = excelToTable(ws);
		expect(result.columnLetters).toEqual(['A', 'B', 'C']);
	});

	it('returns empty rows and columnLetters for a worksheet with no !ref', () => {
		const ws: XLSX.WorkSheet = {};
		const result = excelToTable(ws);
		expect(result.rows).toEqual([]);
		expect(result.columnLetters).toEqual([]);
	});
});
