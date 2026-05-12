<script lang="ts">
	// A small grid, four columns wide, five rows tall —
	// enough to recognise the spreadsheet's shape from across the room.
	import { onMount } from 'svelte';
	import { WEBUI_API_BASE_URL } from '$lib/constants';
	import type { ArtifactCardItem } from '$lib/types/contract';

	export let item: ArtifactCardItem;

	const MAX_ROWS = 5;
	const MAX_COLS = 4;

	let cells: string[][] = [];
	let loading = !!item.file_id || !!item.path;
	let errored = false;

	function parseCsv(text: string): string[][] {
		// Tiny CSV splitter — handles quoted fields and embedded commas. Not
		// a full RFC-4180 parser; we only need the first 5 rows × 4 columns
		// readable, so corner cases gracefully degrade to truncated cells.
		const rows: string[][] = [];
		let i = 0;
		let row: string[] = [];
		let cell = '';
		let inQuotes = false;
		while (i < text.length && rows.length < MAX_ROWS) {
			const ch = text[i];
			if (inQuotes) {
				if (ch === '"' && text[i + 1] === '"') {
					cell += '"';
					i += 2;
					continue;
				}
				if (ch === '"') {
					inQuotes = false;
					i += 1;
					continue;
				}
				cell += ch;
				i += 1;
			} else if (ch === '"' && cell === '') {
				inQuotes = true;
				i += 1;
			} else if (ch === ',') {
				row.push(cell);
				cell = '';
				i += 1;
			} else if (ch === '\n' || ch === '\r') {
				row.push(cell);
				rows.push(row);
				row = [];
				cell = '';
				if (ch === '\r' && text[i + 1] === '\n') i += 2;
				else i += 1;
			} else {
				cell += ch;
				i += 1;
			}
		}
		if (cell !== '' || row.length > 0) {
			row.push(cell);
			rows.push(row);
		}
		return rows.map((r) => r.slice(0, MAX_COLS));
	}

	async function loadCsv() {
		if (!item.file_id && !item.path) {
			loading = false;
			return;
		}
		try {
			let text = '';
			if (item.file_id) {
				const res = await fetch(`${WEBUI_API_BASE_URL}/files/${item.file_id}/content`, {
					credentials: 'include'
				});
				if (!res.ok) throw new Error(`HTTP ${res.status}`);
				text = await res.text();
			} else if (item.path) {
				const res = await fetch(
					`${WEBUI_API_BASE_URL}/hermes/media?path=${encodeURIComponent(item.path)}`,
					{ credentials: 'include' }
				);
				if (!res.ok) throw new Error(`HTTP ${res.status}`);
				text = await res.text();
			}
			cells = parseCsv(text);
		} catch {
			errored = true;
		} finally {
			loading = false;
		}
	}

	async function loadXlsx() {
		if (!item.file_id && !item.path) {
			loading = false;
			return;
		}
		try {
			let blob: Blob;
			if (item.file_id) {
				const res = await fetch(`${WEBUI_API_BASE_URL}/files/${item.file_id}/content`, {
					credentials: 'include'
				});
				if (!res.ok) throw new Error(`HTTP ${res.status}`);
				blob = await res.blob();
			} else if (item.path) {
				const res = await fetch(
					`${WEBUI_API_BASE_URL}/hermes/media?path=${encodeURIComponent(item.path)}`,
					{ credentials: 'include' }
				);
				if (!res.ok) throw new Error(`HTTP ${res.status}`);
				blob = await res.blob();
			} else {
				errored = true;
				return;
			}
			const buf = await blob.arrayBuffer();
			const XLSX = await import('xlsx');
			const wb = XLSX.read(buf, { type: 'array' });
			const sheetName = wb.SheetNames[0];
			if (!sheetName) {
				cells = [];
				return;
			}
			const rows = XLSX.utils.sheet_to_json<string[]>(wb.Sheets[sheetName], {
				header: 1,
				defval: ''
			}) as string[][];
			cells = rows.slice(0, MAX_ROWS).map((r) => r.slice(0, MAX_COLS).map((c) => String(c ?? '')));
		} catch {
			errored = true;
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		if (item.kind === 'csv') loadCsv();
		else loadXlsx();
	});
</script>

<div data-testid="mini-sheet" class="text-xs">
	{#if loading}
		<div class="text-gray-400 dark:text-gray-500 animate-pulse">Loading preview…</div>
	{:else if errored || cells.length === 0}
		<div class="text-gray-500 italic">Spreadsheet · {item.filename}</div>
	{:else}
		<table class="border-collapse w-full font-mono text-[10px]">
			<tbody>
				{#each cells as row, rowIdx (rowIdx)}
					<tr>
						{#each row as cell, colIdx (colIdx)}
							<td
								class="border border-gray-200 dark:border-gray-800 px-1.5 py-0.5 text-gray-700 dark:text-gray-300 truncate max-w-[120px]"
								title={cell}>{cell}</td>
						{/each}
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</div>
