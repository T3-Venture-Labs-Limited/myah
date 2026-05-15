<script lang="ts">
	// columns can be:
	//   Array<{key:string;label:string}>   (structured)
	//   string[]                            (shorthand — key and label are both the string)
	export let columns: Array<{ key: string; label: string } | string> = [];
	// rows can be:
	//   Array<Record<string, unknown>>     (keyed objects)
	//   Array<unknown[]>                   (arrays — zipped against column order)
	export let rows: Array<Record<string, unknown> | unknown[]> = [];

	type Col = { key: string; label: string };

	$: safeCols = Array.isArray(columns) ? columns : [];
	$: normalizedCols = safeCols.map((c, i): Col => {
		if (typeof c === 'string') return { key: String(i), label: c };
		return c as Col;
	});

	function cellValue(row: Record<string, unknown> | unknown[], col: Col, idx: number): string {
		if (Array.isArray(row)) {
			const v = row[idx];
			return v == null ? '' : String(v);
		}
		const v = (row as Record<string, unknown>)[col.key];
		return v == null ? '' : String(v);
	}
</script>

<div
	style="overflow-x:auto;margin-bottom:12px;border-radius:var(--myah-radius);border:1px solid var(--myah-border)"
>
	<table style="width:100%;border-collapse:collapse;font-size:13px">
		<thead>
			<tr style="background:var(--myah-bg-card)">
				{#each normalizedCols as col}
					<th
						style="text-align:left;padding:10px 14px;font-weight:600;font-size:11px;color:var(--myah-text-muted);text-transform:uppercase;letter-spacing:0.04em;border-bottom:1px solid var(--myah-border);white-space:nowrap"
					>
						{col.label}
					</th>
				{/each}
			</tr>
		</thead>
		<tbody>
			{#each Array.isArray(rows) ? rows : [] as row, rowIdx}
				<tr
					style="border-bottom:1px solid var(--myah-border);background:{rowIdx % 2 === 0
						? 'transparent'
						: 'rgba(255,255,255,0.015)'}"
				>
					{#each normalizedCols as col, colIdx}
						<td style="padding:10px 14px;color:var(--myah-text)">
							{cellValue(row, col, colIdx)}
						</td>
					{/each}
				</tr>
			{/each}
		</tbody>
	</table>
</div>
