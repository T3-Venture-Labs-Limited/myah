<script lang="ts">
	import VideoRenderer from '../VideoRenderer.svelte';
	import type { ToolbarItem, SelectionPayload } from '$lib/types/artifact';

	export let rendererProps: {
		filename?: string;
		content?: Blob | string;
		file_id?: string;
		path?: string;
		mime?: string;
		editable?: boolean;
	} = {};
	export let onToolbar: (items: ToolbarItem[]) => void = () => {};
	export let onSelect: (payload: SelectionPayload | null) => void = () => {};

	$: filename = rendererProps.filename ?? 'test.mp4';
	$: content = rendererProps.content;
	$: file_id = rendererProps.file_id;
	$: path = rendererProps.path;
	$: mime = rendererProps.mime;
	$: editable = rendererProps.editable ?? false;
</script>

<VideoRenderer
	{filename}
	{content}
	{file_id}
	{path}
	{mime}
	{editable}
	on:toolbar={(e: CustomEvent<{ items: ToolbarItem[] }>) => onToolbar(e.detail.items)}
	on:select={(e: CustomEvent<SelectionPayload | null>) => onSelect(e.detail)}
/>
