<script lang="ts">
	// SQLite viewer — placeholder implementation.
	// A full implementation (Task 13+) would use sql.js to open and query
	// the database in-browser. For now we show metadata about the file.
	import { onMount, createEventDispatcher } from 'svelte';
	import type { ToolbarItem } from '$lib/types/artifact';

	export let content: Blob | string;
	export let filename: string;
	export let mime: string | undefined = undefined;
	// Accepted for prop-chain symmetry with other renderers; not used here.
	export let file_id: string | undefined = undefined;
	export let path: string | undefined = undefined;
	export let editable = false;

	$: void [file_id, path, editable];

	const dispatch = createEventDispatcher<{
		toolbar: { items: ToolbarItem[] };
	}>();

	onMount(() => {
		dispatch('toolbar', { items: [] });
	});

	$: sizeLabel =
		content instanceof Blob
			? `${(content.size / 1024).toFixed(1)} KB`
			: 'Stored on server';
</script>

<div class="flex flex-col items-center justify-center gap-3 py-10 text-sm text-gray-500 dark:text-gray-400">
	<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="size-10 opacity-40">
		<path stroke-linecap="round" stroke-linejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 2.625c0 2.278-3.694 4.125-8.25 4.125S3.75 11.278 3.75 9m16.5 2.625c0 2.278-3.694 4.125-8.25 4.125S3.75 13.903 3.75 11.625" />
	</svg>
	<div class="font-medium text-gray-700 dark:text-gray-300">{filename}</div>
	<div class="text-xs">{sizeLabel} · SQLite database</div>
	<div class="text-xs text-center max-w-xs opacity-70">
		In-browser SQLite querying is not yet available.<br />
		Download the file to open it in a local database viewer.
	</div>
</div>
