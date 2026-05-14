<script lang="ts">
	// Numbers carry weight and meaning. Render the grid honestly,
	// expose the formulas that shape it, surface the sums beneath
	// the surface — and let selection speak in A1 notation, the
	// shared dialect of every spreadsheet ever opened.
	import { createEventDispatcher, onMount } from 'svelte';
	import * as XLSX from 'xlsx';
	import { MYAH_API_BASE_URL } from '$lib/constants';
	import { excelToTable } from '$lib/utils/excelToTable';
	import type { TableView, CellView } from '$lib/utils/excelToTable';
	import type { SelectionPayload, ToolbarItem } from '$lib/types/artifact';
	import ArtifactFallback from './ArtifactFallback.svelte';
	import SelectionToolbar from '$lib/components/chat/Artifacts/SelectionToolbar.svelte';
	import { artifactSelection } from '$lib/stores';

	export let content: Blob | string;
	export let filename: string = '';
	export let mime: string | undefined = undefined;
	export let file_id: string | undefined = undefined;
	export let path: string | undefined = undefined;
	// XLSX renders read-only in this iteration; the editable prop is part of
	// the Renderer Contract so the host can pass it uniformly.
	export let editable: boolean = false;

	// Suppress unused-prop warnings for fields the host hands us but we don't
	// directly consume — they're part of the Renderer Contract surface.
	void mime;
	void editable;

	const dispatch = createEventDispatcher<{
		select: SelectionPayload | null;
		toolbar: { items: ToolbarItem[] };
		error: Error;
	}>();

	let tableView: TableView | null = null;
	let sheets: string[] = [];
	let activeSheet = 0;
	let showFormulas = false;
	let loading = true;
	let errorObj: Error | null = null;
	let workbook: XLSX.WorkBook | null = null;

	// ── Selection state (A1-style ranges) ────────────────────────────
	let selectionStart: { col: number; row: number } | null = null;
	let selectionEnd: { col: number; row: number } | null = null;
	let isDragging = false;
	let activeCell: { ref: string; formula: string; value: unknown } | null = null;
	let container: HTMLElement;
	let toolbarAnchorRect: DOMRect | null = null;

	$: if ($artifactSelection === null) toolbarAnchorRect = null;

	// ── A1 helpers ───────────────────────────────────────────────────
	const colToA1 = (col: number): string => {
		// 0 → "A", 25 → "Z", 26 → "AA", 27 → "AB", 51 → "AZ", 52 → "BA", …
		let result = '';
		let n = col;
		while (n >= 0) {
			result = String.fromCharCode((n % 26) + 65) + result;
			n = Math.floor(n / 26) - 1;
		}
		return result;
	};

	const cellRefAt = (col: number, row: number): string => `${colToA1(col)}${row + 1}`;

	const rangeFromSelection = (
		s: { col: number; row: number },
		e: { col: number; row: number }
	): string => {
		const c1 = Math.min(s.col, e.col);
		const c2 = Math.max(s.col, e.col);
		const r1 = Math.min(s.row, e.row);
		const r2 = Math.max(s.row, e.row);
		const startRef = cellRefAt(c1, r1);
		if (c1 === c2 && r1 === r2) return startRef;
		return `${startRef}:${cellRefAt(c2, r2)}`;
	};

	// ── Loading ──────────────────────────────────────────────────────
	const loadSheet = () => {
		if (!workbook || sheets.length === 0) return;
		tableView = excelToTable(workbook.Sheets[sheets[activeSheet]]);
		// Reset selection when switching sheets.
		selectionStart = null;
		selectionEnd = null;
		activeCell = null;
	};

	const load = async () => {
		loading = true;
		errorObj = null;
		tableView = null;
		workbook = null;
		try {
			let arrayBuffer: ArrayBuffer;
			if (content instanceof Blob) {
				arrayBuffer = await content.arrayBuffer();
			} else {
				const res = await fetch(`${MYAH_API_BASE_URL}/files/${content}/content`, {
					credentials: 'include'
				});
				if (!res.ok) throw new Error(`HTTP ${res.status}`);
				arrayBuffer = await res.arrayBuffer();
			}
			workbook = XLSX.read(arrayBuffer, { type: 'array' });
			sheets = workbook.SheetNames;
			activeSheet = 0;
			loadSheet();
		} catch (e) {
			console.error('Error loading XLSX file:', e);
			const err = e instanceof Error ? e : new Error(String(e));
			errorObj = err;
			dispatch('error', err);
		} finally {
			loading = false;
		}
	};

	$: (content, load());
	// 2026-05-05 dogfooding: include `activeSheet` in the reactive expression
	// so changing the active tab re-renders the grid. Without `activeSheet`
	// being read in this `$:`, Svelte does not track it and clicking the
	// "Summary" tab sets the variable but never re-runs `loadSheet()`.
	$: if (workbook && sheets.length > 0 && activeSheet >= 0) {
		loadSheet();
	}

	onMount(() => {
		// Contribute the renderer's toolbar items to the host shell.
		dispatch('toolbar', {
			items: [
				{
					placement: 'overlay-tr',
					id: 'reset-zoom',
					label: 'Reset zoom'
				}
			]
		});
	});

	// ── Display helpers ──────────────────────────────────────────────
	const cellDisplay = (cell: CellView): string => {
		if (showFormulas && cell.formula) return `=${cell.formula}`;
		return cell.value !== null && cell.value !== undefined ? String(cell.value) : '';
	};

	// Pre-compute selection bounds in a `$:` reactive so the template can
	// read primitive values directly — guarantees Svelte invalidates every
	// affected cell when `selectionStart` / `selectionEnd` change. Helper
	// functions called from inside dynamic class expressions don't reliably
	// participate in reactivity tracking, which is why earlier iterations
	// of this code highlighted "nothing" even though the selection state
	// was correct internally.
	$: selBounds = (() => {
		if (!selectionStart || !selectionEnd) return null;
		return {
			c1: Math.min(selectionStart.col, selectionEnd.col),
			c2: Math.max(selectionStart.col, selectionEnd.col),
			r1: Math.min(selectionStart.row, selectionEnd.row),
			r2: Math.max(selectionStart.row, selectionEnd.row)
		};
	})();
	$: activeCellRef = selectionEnd ? cellRefAt(selectionEnd.col, selectionEnd.row) : null;

	const setActiveCellFromCoord = (col: number, row: number) => {
		if (!tableView) return;
		const cell = tableView.rows[row]?.[col];
		if (!cell) return;
		activeCell = {
			ref: cellRefAt(col, row),
			formula: cell.formula ?? '',
			value: cell.value
		};
	};

	// ── Mouse handlers ───────────────────────────────────────────────
	const onCellMouseDown = (col: number, row: number) => {
		selectionStart = { col, row };
		selectionEnd = { col, row };
		isDragging = true;
		setActiveCellFromCoord(col, row);
	};

	const onCellMouseEnter = (col: number, row: number) => {
		if (!isDragging) return;
		selectionEnd = { col, row };
		setActiveCellFromCoord(col, row);
	};

	// 2026-05-05 dogfooding: click a column-letter header to select the full
	// column; click a row-number header to select the full row. Mirrors
	// Google Sheets / Excel — the user expects the same affordance.
	// `isDragging = true` is set so the shared `onTableMouseUp` commit path
	// runs (it returns early when `isDragging` is false). The flag is then
	// flipped back inside `onTableMouseUp`.
	const onColumnHeaderMouseDown = (col: number) => {
		if (!tableView) return;
		const lastRow = Math.max(0, tableView.rows.length - 1);
		selectionStart = { col, row: 0 };
		selectionEnd = { col, row: lastRow };
		isDragging = true;
		setActiveCellFromCoord(col, 0);
		onTableMouseUp();
	};

	const onRowHeaderMouseDown = (row: number) => {
		if (!tableView) return;
		const lastCol = Math.max(0, tableView.columnLetters.length - 1);
		selectionStart = { col: 0, row };
		selectionEnd = { col: lastCol, row };
		isDragging = true;
		setActiveCellFromCoord(0, row);
		onTableMouseUp();
	};

	const onTableMouseUp = () => {
		if (!isDragging || !selectionStart || !selectionEnd || !tableView) {
			isDragging = false;
			return;
		}
		isDragging = false;

		const c1 = Math.min(selectionStart.col, selectionEnd.col);
		const c2 = Math.max(selectionStart.col, selectionEnd.col);
		const r1 = Math.min(selectionStart.row, selectionEnd.row);
		const r2 = Math.max(selectionStart.row, selectionEnd.row);

		const range = rangeFromSelection(selectionStart, selectionEnd);
		const sheetName = sheets[activeSheet] ?? '';

		// Build preview matrix + collect numeric values for sum.
		const preview: string[][] = [];
		const numerics: number[] = [];
		let cellCount = 0;
		let allNumeric = true;
		for (let r = r1; r <= r2; r++) {
			const row: string[] = [];
			for (let c = c1; c <= c2; c++) {
				const cell = tableView.rows[r]?.[c];
				const v = cell?.value;
				row.push(v !== null && v !== undefined ? String(v) : '');
				cellCount += 1;
				if (typeof v === 'number') {
					numerics.push(v);
				} else {
					allNumeric = false;
				}
			}
			preview.push(row);
		}

		let summary = `${range} · ${cellCount} cells`;
		if (allNumeric && numerics.length > 0) {
			const sum = numerics.reduce((acc, n) => acc + n, 0);
			summary += ` · sum: ${sum}`;
		}

		const payload: SelectionPayload = {
			kind: 'sheet-cells',
			anchor: { sheet: sheetName, range },
			preview,
			summary
		};
		dispatch('select', payload);
		// 2026-05-05 dogfooding: write the store directly — see CodeRenderer
		// for the rationale (Svelte 5 <svelte:component> event forwarding is
		// fragile, so the host doesn't always receive the dispatch).
		artifactSelection.set(payload);

		// Compute toolbar anchor rect from the selected cells' bounding box.
		if (container) {
			const startEl = container.querySelector(`[data-cell="${cellRefAt(c1, r1)}"]`);
			const endEl = container.querySelector(`[data-cell="${cellRefAt(c2, r2)}"]`);
			if (startEl && endEl) {
				const a = startEl.getBoundingClientRect();
				const b = endEl.getBoundingClientRect();
				const top = Math.min(a.top, b.top);
				const bottom = Math.max(a.bottom, b.bottom);
				const left = Math.min(a.left, b.left);
				const right = Math.max(a.right, b.right);
				toolbarAnchorRect = {
					top,
					bottom,
					left,
					right,
					width: right - left,
					height: bottom - top,
					x: left,
					y: top,
					toJSON: () => ''
				} as DOMRect;
			}
		}
	};
</script>

{#if loading}
	<div class="flex items-center justify-center py-8 text-sm text-gray-500 dark:text-gray-400">
		Loading…
	</div>
{:else if errorObj}
	<ArtifactFallback
		error={errorObj}
		{filename}
		file_id={typeof content === 'string' ? content : file_id}
		{path}
		onRetry={load}
	/>
{:else if tableView}
	<div class="flex flex-col h-full relative" bind:this={container}>
		<!-- Formula bar (top, ~32px) -->
		<div
			data-testid="formula-bar"
			class="flex items-center h-8 px-2 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 text-sm font-mono shrink-0"
		>
			<span
				class="min-w-[3rem] text-gray-600 dark:text-gray-400 px-2 border-r border-gray-200 dark:border-gray-800"
			>
				{activeCell?.ref ?? ''}
			</span>
			<span class="px-2 text-gray-700 dark:text-gray-200 truncate">
				{#if activeCell?.formula}
					={activeCell.formula}
				{:else if activeCell?.value !== null && activeCell?.value !== undefined}
					{activeCell.value}
				{/if}
			</span>
			<label
				class="ml-auto flex items-center gap-1.5 cursor-pointer select-none text-xs text-gray-600 dark:text-gray-400 font-sans"
			>
				<input type="checkbox" bind:checked={showFormulas} class="rounded" />
				Show formulas
			</label>
		</div>

		<!-- Grid (middle, fills remaining space) -->
		<div class="office-preview overflow-auto flex-1">
			<!-- svelte-ignore a11y-no-static-element-interactions -->
			<table
				class="text-xs border-collapse w-max select-none"
				on:mouseup={onTableMouseUp}
				on:mouseleave={onTableMouseUp}
			>
				<thead>
					<tr>
						<th
							class="excel-row-num border px-2 py-1 bg-gray-50 dark:bg-gray-700 sticky left-0 z-10"
						></th>
						{#each tableView.columnLetters as letter, c (letter)}
							<!-- svelte-ignore a11y-click-events-have-key-events -->
							<th
								class="excel-col-hdr border px-2 py-1 font-medium cursor-pointer transition {selBounds &&
								selBounds.c1 <= c &&
								c <= selBounds.c2
									? 'bg-blue-100 dark:bg-blue-900/40 text-blue-900 dark:text-blue-100'
									: 'bg-gray-50 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-600'}"
								on:mousedown={() => onColumnHeaderMouseDown(c)}
							>
								{letter}
							</th>
						{/each}
					</tr>
				</thead>
				<tbody>
					{#each tableView.rows as row, r}
						<tr>
							<!-- svelte-ignore a11y-click-events-have-key-events -->
							<!-- svelte-ignore a11y-no-static-element-interactions -->
							<td
								class="excel-row-num border px-2 py-1 sticky left-0 font-mono text-right cursor-pointer transition {selBounds &&
								selBounds.r1 <= r &&
								r <= selBounds.r2
									? 'bg-blue-100 dark:bg-blue-900/40 text-blue-900 dark:text-blue-100'
									: 'bg-gray-50 dark:bg-gray-700 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-600'}"
								on:mousedown={() => onRowHeaderMouseDown(r)}
							>
								{r + 1}
							</td>
							{#each row as cell, c (c)}
								{@const ref = cellRefAt(c, r)}
								{@const inSel =
									!!selBounds &&
									selBounds.c1 <= c &&
									c <= selBounds.c2 &&
									selBounds.r1 <= r &&
									r <= selBounds.r2}
								{@const isActive = activeCellRef === ref}
								<!-- svelte-ignore a11y-click-events-have-key-events -->
								<!-- svelte-ignore a11y-no-static-element-interactions -->
								<td
									data-cell={ref}
									class="border px-2 py-1 cursor-cell relative {cell.type === 'n'
										? 'text-right tabular-nums'
										: ''} {cell.formula && showFormulas
										? 'font-mono text-blue-600 dark:text-blue-400'
										: ''} {inSel ? 'bg-blue-500/25 dark:bg-blue-400/25' : ''} {isActive
										? 'outline outline-2 outline-blue-600 dark:outline-blue-400 outline-offset-[-2px] z-10'
										: ''}"
									on:mousedown={() => onCellMouseDown(c, r)}
									on:mouseenter={() => onCellMouseEnter(c, r)}
								>
									{cellDisplay(cell)}
								</td>
							{/each}
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		<!-- Bottom bar: sheet tabs (left) + status footer (right) -->
		<div
			class="flex items-center h-8 border-t border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900 text-sm shrink-0"
		>
			<div
				data-testid="sheet-tabs"
				class="flex scrollbar-none overflow-x-auto bg-transparent dark:text-gray-200"
			>
				{#each sheets as sheet, i}
					<button
						class="min-w-fit py-1 px-3 border-r border-gray-200 dark:border-gray-800 {i ===
						activeSheet
							? 'bg-white dark:bg-gray-800 font-medium'
							: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-white'} transition"
						type="button"
						on:click={() => (activeSheet = i)}>{sheet}</button
					>
				{/each}
			</div>
			<div
				data-testid="sheet-status"
				class="ml-auto px-3 text-xs text-gray-500 dark:text-gray-400 font-mono"
			>
				Ready · {tableView.rows.length} rows · {tableView.columnLetters.length} cols
			</div>
		</div>
		<SelectionToolbar placement="floating" anchorRect={toolbarAnchorRect} {filename} />
	</div>
{/if}
