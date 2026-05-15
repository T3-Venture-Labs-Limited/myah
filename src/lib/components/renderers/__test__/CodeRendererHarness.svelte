<script lang="ts">
	import CodeRenderer from '../CodeRenderer.svelte';
	import type { ToolbarItem, SelectionPayload } from '$lib/types/artifact';

	export let codeProps: {
		filename?: string;
		content?: Blob | string;
		file_id?: string;
		path?: string;
		editable?: boolean;
	} = {};
	export let onToolbar: (items: ToolbarItem[]) => void = () => {};
	export let onDirty: (payload: { isDirty: boolean; diff?: string }) => void = () => {};
	export let onSelect: (payload: SelectionPayload | null) => void = () => {};

	$: filename = codeProps.filename ?? 'test.txt';
	$: content = codeProps.content;
	$: file_id = codeProps.file_id;
	$: path = codeProps.path;
	$: editable = codeProps.editable ?? false;
</script>

<CodeRenderer
	{filename}
	{content}
	{file_id}
	{path}
	{editable}
	on:toolbar={(e: CustomEvent<{ items: ToolbarItem[] }>) => onToolbar(e.detail.items)}
	on:dirty={(e: CustomEvent<{ isDirty: boolean; diff?: string }>) => onDirty(e.detail)}
	on:select={(e: CustomEvent<SelectionPayload | null>) => onSelect(e.detail)}
/>
