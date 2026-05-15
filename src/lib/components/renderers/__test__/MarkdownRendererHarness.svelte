<script lang="ts">
	import MarkdownRenderer from '../MarkdownRenderer.svelte';
	import type { SelectionPayload, ToolbarItem } from '$lib/types/artifact';

	export let content: Blob | string = '';
	export let filename: string = 'test.md';
	export let file_id: string | undefined = undefined;
	export let onSelect: ((payload: SelectionPayload | null) => void) | undefined = undefined;
	export let onToolbar: ((items: ToolbarItem[]) => void) | undefined = undefined;
	export let onError: ((err: Error) => void) | undefined = undefined;
</script>

<MarkdownRenderer
	{content}
	{filename}
	{file_id}
	editable={false}
	on:select={(e) => onSelect?.(e.detail)}
	on:toolbar={(e) => onToolbar?.(e.detail.items)}
	on:error={(e) => onError?.(e.detail)}
/>
