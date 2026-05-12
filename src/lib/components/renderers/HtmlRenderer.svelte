<script lang="ts">
	import { WEBUI_API_BASE_URL } from '$lib/constants';
	import ArtifactFallback from './ArtifactFallback.svelte';

	// A pane for whatever HTML the agent has spun up — sandboxed,
	// origin-less, never granted the keys to the parent house.
	// Renderer Contract props
	export let filename: string;
	export let mime: string | undefined = undefined;
	export let file_id: string | undefined = undefined;
	export let path: string | undefined = undefined;
	export let editable = false; // HTML is non-editable in this spec
	export let content: Blob | string | undefined = undefined; // unused, kept for prop parity

	// Reference unused props to silence lint without changing behavior.
	void mime;
	void editable;
	void content;

	// Direct iframe src — relies on backend Content-Disposition: inline (Section 8.1).
	$: src = file_id
		? `${WEBUI_API_BASE_URL}/files/${file_id}/content`
		: path
			? `${WEBUI_API_BASE_URL}/hermes/media?path=${encodeURIComponent(path)}`
			: null;
</script>

{#if src}
	<iframe
		{src}
		title={filename}
		class="w-full h-full border-0"
		sandbox="allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox"
	></iframe>
{:else}
	<ArtifactFallback
		error={new Error('No file_id or path provided')}
		{filename}
		{file_id}
		{path}
	/>
{/if}
