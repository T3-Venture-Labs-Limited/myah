<script lang="ts">
	import { onMount, createEventDispatcher } from 'svelte';
	import { MYAH_API_BASE_URL } from '$lib/constants';
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

	let text = '';
	let errorObj: Error | null = null;
	let loading = true;

	const load = async () => {
		loading = true;
		errorObj = null;
		try {
			if (content instanceof Blob) {
				text = await content.text();
			} else {
				const res = await fetch(`${MYAH_API_BASE_URL}/files/${content}/content`, {
					credentials: 'include'
				});
				if (!res.ok) throw new Error(`HTTP ${res.status}`);
				text = await res.text();
			}
		} catch (e) {
			console.error('Error loading text file:', e);
			errorObj = e instanceof Error ? e : new Error(String(e));
			dispatch('error', errorObj);
		} finally {
			loading = false;
		}
	};

	onMount(() => {
		dispatch('toolbar', { items: [] });
		load();
	});
</script>

{#if loading}
	<div class="flex items-center justify-center py-8 text-sm text-gray-500">Loading…</div>
{:else if errorObj}
	<ArtifactFallback
		error={errorObj}
		{filename}
		file_id={typeof content === 'string' ? content : file_id}
		{path}
		onRetry={load}
	/>
{:else}
	<pre class="text-xs whitespace-pre-wrap font-mono leading-relaxed">{text}</pre>
{/if}
