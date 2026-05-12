<script lang="ts">
	import { onMount, createEventDispatcher } from 'svelte';
	import { WEBUI_API_BASE_URL } from '$lib/constants';
	import type { ToolbarItem } from '$lib/types/artifact';
	import ArtifactFallback from './ArtifactFallback.svelte';

	export let content: Blob | string;
	export let filename: string;
	export let mime: string | undefined = undefined;
	export let file_id: string | undefined = undefined;
	export let path: string | undefined = undefined;
	export let editable = false;

	$: void editable;

	const dispatch = createEventDispatcher<{
		toolbar: { items: ToolbarItem[] };
		error: Error;
	}>();

	// For Blob content, create an object URL; for string (file ID) use the API endpoint.
	$: src =
		content instanceof Blob
			? URL.createObjectURL(content)
			: `${WEBUI_API_BASE_URL}/files/${content}/content`;

	let errorObj: Error | null = null;
	let reloadKey = 0;

	const handleError = () => {
		errorObj = new Error(`Failed to load audio: ${filename}`);
		dispatch('error', errorObj);
	};

	const reload = () => {
		errorObj = null;
		reloadKey += 1;
	};

	onMount(() => {
		dispatch('toolbar', { items: [] });
	});
</script>

{#if errorObj}
	<ArtifactFallback
		error={errorObj}
		{filename}
		file_id={typeof content === 'string' ? content : file_id}
		{path}
		onRetry={reload}
	/>
{:else}
	<div data-testid="audio-card" class="flex flex-col items-center justify-center h-full p-8 gap-4">
		<div class="text-sm font-medium text-gray-700 dark:text-gray-300 text-center break-all">
			{filename}
		</div>
		{#key reloadKey}
			<audio
				{src}
				class="w-full max-w-md border-0 rounded-lg"
				controls
				playsinline
				on:error={handleError}
			>
				Your browser does not support the audio element.
			</audio>
		{/key}
	</div>
{/if}
