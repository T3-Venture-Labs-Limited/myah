<script lang="ts">
	import DocxRenderer from '../DocxRenderer.svelte';
	import type { SelectionPayload, ToolbarItem } from '$lib/types/artifact';

	export let content: Blob | string = '';
	export let filename: string = 'test.docx';
	export let file_id: string | undefined = undefined;
	export let onSelect: ((payload: SelectionPayload | null) => void) | undefined = undefined;
	export let onToolbar: ((items: ToolbarItem[]) => void) | undefined = undefined;
	export let onError: ((err: Error) => void) | undefined = undefined;
</script>

<DocxRenderer
	{content}
	{filename}
	{file_id}
	editable={false}
	on:select={(e) => onSelect?.(e.detail)}
	on:toolbar={(e) => onToolbar?.(e.detail.items)}
	on:error={(e) => onError?.(e.detail)}
/>
