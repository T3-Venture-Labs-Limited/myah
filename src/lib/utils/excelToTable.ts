/**
 * Shared Excel → structured table data.
 *
 * Walks cells individually so formula information is preserved.
 * Callers that need HTML can build it from CellView[]; callers that
 * need formula visibility get it via the `formula` field.
 */

import * as XLSX from 'xlsx';

export interface CellView {
	value: string | number | boolean | null;
	formula: string | null;
	type: string;
}

export interface TableView {
	rows: CellView[][];
	columnLetters: string[];
}

export interface ExcelTableResult {
	html: string;
	rowCount: number;
	colCount: number;
}

/**
 * Convert a worksheet to a structured TableView, preserving formula data.
 * Uses cell-by-cell iteration rather than sheet_to_json to capture `cell.f`.
 */
export function excelToTable(worksheet: XLSX.WorkSheet): TableView {
	const ref = worksheet['!ref'];
	if (!ref) return { rows: [], columnLetters: [] };

	const range = XLSX.utils.decode_range(ref);
	const rows: CellView[][] = [];

	for (let r = range.s.r; r <= range.e.r; r++) {
		const row: CellView[] = [];
		for (let c = range.s.c; c <= range.e.c; c++) {
			const addr = XLSX.utils.encode_cell({ r, c });
			const cell = worksheet[addr];
			row.push({
				value: cell?.v ?? null,
				formula: cell?.f ?? null,
				type: cell?.t ?? 's'
			});
		}
		rows.push(row);
	}

	const columnLetters: string[] = [];
	for (let c = range.s.c; c <= range.e.c; c++) {
		columnLetters.push(XLSX.utils.encode_col(c));
	}

	return { rows, columnLetters };
}

// ── Legacy HTML-rendering path (kept for back-compat) ─────────────────────
// callers that previously used the async excelToTable(worksheet) → Promise<ExcelTableResult>
// should migrate to excelToTable(worksheet) → TableView + build their own table.

/** Escape HTML entities */
const esc = (v: unknown): string => {
	if (v === null || v === undefined || v === '') return '&nbsp;';
	return String(v)
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;');
};

/**
 * Render a TableView as an HTML table string.
 * Kept as a synchronous helper for components that need HTML output.
 */
export async function excelToHtml(worksheet: XLSX.WorkSheet): Promise<ExcelTableResult> {
	const { rows, columnLetters } = excelToTable(worksheet);

	if (rows.length === 0) {
		return {
			html: '<table><tbody><tr><td>&nbsp;</td></tr></tbody></table>',
			rowCount: 0,
			colCount: 0
		};
	}

	const colCount = columnLetters.length;
	const parts: string[] = [];
	parts.push('<table>');

	// Column letter header row
	parts.push('<thead><tr>');
	parts.push('<th class="excel-row-num"></th>');
	for (const letter of columnLetters) {
		parts.push(`<th class="excel-col-hdr">${letter}</th>`);
	}
	parts.push('</tr></thead>');

	// Data rows
	parts.push('<tbody>');
	for (let r = 0; r < rows.length; r++) {
		const row = rows[r];
		parts.push('<tr>');
		parts.push(`<td class="excel-row-num">${r + 1}</td>`);
		for (const cell of row) {
			const isNum = cell.type === 'n';
			const display = cell.value !== null ? cell.value : '';
			parts.push(`<td${isNum ? ' class="excel-num"' : ''}>${esc(display)}</td>`);
		}
		parts.push('</tr>');
	}
	parts.push('</tbody></table>');

	const DOMPurify = (await import('dompurify')).default;
	return {
		html: DOMPurify.sanitize(parts.join('')),
		rowCount: rows.length,
		colCount
	};
}
