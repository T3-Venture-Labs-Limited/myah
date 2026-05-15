<script lang="ts">
	import PdfRenderer from '../PdfRenderer.svelte';
	import type { ToolbarItem } from '$lib/types/artifact';

	export let rendererProps: {
		filename?: string;
		content?: Blob | string;
		file_id?: string;
		path?: string;
		mime?: string;
		editable?: boolean;
	} = {};
	export let onToolbar: (items: ToolbarItem[]) => void = () => {};

	$: filename = rendererProps.filename ?? 'test.pdf';
	$: content = rendererProps.content;
	$: file_id = rendererProps.file_id;
	$: path = rendererProps.path;
	$: mime = rendererProps.mime;
	$: editable = rendererProps.editable ?? false;
</script>

<PdfRenderer
	{filename}
	{content}
	{file_id}
	{path}
	{mime}
	{editable}
	on:toolbar={(e: CustomEvent<{ items: ToolbarItem[] }>) => onToolbar(e.detail.items)}
/>
