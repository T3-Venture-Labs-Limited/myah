<script lang="ts">
	// CSV/TSV are single-sheet workbooks — XlsxRenderer (via SheetJS) handles
	// both formats natively. No need for separate component logic.
	import XlsxRenderer from './XlsxRenderer.svelte';

	export let content: Blob | string;
	export let filename: string = '';
	export let mime: string | undefined = undefined;
	export let file_id: string | undefined = undefined;
	export let path: string | undefined = undefined;
</script>

<XlsxRenderer
	{content}
	{filename}
	{mime}
	{file_id}
	{path}
	editable={false}
	on:select
	on:toolbar
	on:error
/>
