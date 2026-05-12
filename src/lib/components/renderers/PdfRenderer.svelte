<script lang="ts">
	import { onMount, createEventDispatcher } from 'svelte';
	import PDFViewer from '$lib/components/common/PDFViewer.svelte';
	import { WEBUI_API_BASE_URL } from '$lib/constants';
	import ArtifactFallback from './ArtifactFallback.svelte';
	import type { ToolbarItem } from '$lib/types/artifact';

	export let content: Blob | string | undefined = undefined;
	export let filename: string;
	export let mime: string | undefined = undefined;
	export let file_id: string | undefined = undefined;
	export let path: string | undefined = undefined;
	export let editable = false;

	// Suppress unused-prop warnings for Renderer Contract props.
	$: void [mime, editable];

	const dispatch = createEventDispatcher<{
		toolbar: { items: ToolbarItem[] };
		error: Error;
	}>();

	// Resolution priority mirrors CodeRenderer Phase 2A: file_id > path > Blob > legacy
	// `content: string` (treated as file_id for backwards compat).
	$: url = file_id
		? `${WEBUI_API_BASE_URL}/files/${file_id}/content`
		: path
			? `${WEBUI_API_BASE_URL}/hermes/media?path=${encodeURIComponent(path)}`
			: typeof content === 'string'
				? `${WEBUI_API_BASE_URL}/files/${content}/content`
				: undefined;

	let reloadKey = 0;
	const reload = () => {
		reloadKey += 1;
	};

	function emitToolbar() {
		// Phase 2B: items declared without onClick — the host Phase 3 toolbar will
		// wire them to PDFViewer's prev/next/zoom (those need to be exposed as a
		// methods/binding, which is its own task).
		dispatch('toolbar', {
			items: [
				{ placement: 'top', id: 'pdf-prev', label: 'Previous page' },
				{ placement: 'top', id: 'pdf-next', label: 'Next page' },
				{ placement: 'overlay-tr', id: 'pdf-zoom-in', label: 'Zoom in' },
				{ placement: 'overlay-tr', id: 'pdf-zoom-out', label: 'Zoom out' }
			]
		});
	}

	onMount(emitToolbar);
</script>

<div data-testid="pdf-inset" class="bg-gray-700 dark:bg-gray-800 h-full w-full overflow-auto p-6">
	{#if url}
		<PDFViewer {url} className="w-full bg-white shadow-md mx-auto max-w-[800px]" />
	{:else if content instanceof Blob}
		{#key reloadKey}
			{#await content.arrayBuffer()}
				<div class="flex items-center justify-center py-8 text-sm text-gray-300">Loading…</div>
			{:then buffer}
				<PDFViewer
					data={new Uint8Array(buffer)}
					className="w-full bg-white shadow-md mx-auto max-w-[800px]"
				/>
			{:catch err}
				<ArtifactFallback
					error={err instanceof Error ? err : new Error(String(err))}
					{filename}
					{file_id}
					{path}
					onRetry={reload}
				/>
			{/await}
		{/key}
	{:else}
		<div class="text-sm text-gray-300 p-4">No PDF source.</div>
	{/if}
</div>
