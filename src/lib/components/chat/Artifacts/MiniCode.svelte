<script lang="ts">
	// A keyhole onto a code file: the first handful of lines, monospaced,
	// just enough to recognise what's inside without crossing the threshold.
	import { onMount } from 'svelte';
	import { WEBUI_API_BASE_URL } from '$lib/constants';
	import type { ArtifactCardItem } from '$lib/types/contract';

	export let item: ArtifactCardItem;

	const MAX_LINES = 10;
	const MAX_CHARS = 600;

	let snippet = '';
	// Skip the spinner state when nothing to load — reduces flicker AND keeps
	// preview-less test fixtures synchronous so render() + getByText still
	// passes on the kind label without awaiting timers.
	let loading =
		!!(item.preview && typeof item.preview === 'string') ||
		!!item.file_id ||
		!!item.path;
	let errored = false;

	$: void item.filename.split('.').pop()?.toLowerCase();

	async function load() {
		// Nothing to fetch — render the fallback immediately.
		if (!(item.preview && typeof item.preview === 'string') && !item.file_id && !item.path) {
			loading = false;
			return;
		}
		loading = true;
		errored = false;
		try {
			let text = '';
			if (item.preview && typeof item.preview === 'string') {
				text = item.preview;
			} else if (item.file_id) {
				const res = await fetch(`${WEBUI_API_BASE_URL}/files/${item.file_id}/content`, {
					credentials: 'include'
				});
				if (!res.ok) throw new Error(`HTTP ${res.status}`);
				text = await res.text();
			} else if (item.path) {
				const res = await fetch(
					`${WEBUI_API_BASE_URL}/hermes/media?path=${encodeURIComponent(item.path)}`,
					{ credentials: 'include' }
				);
				if (!res.ok) throw new Error(`HTTP ${res.status}`);
				text = await res.text();
			}
			const lines = text.split('\n').slice(0, MAX_LINES);
			snippet = lines.join('\n');
			if (snippet.length > MAX_CHARS) snippet = snippet.slice(0, MAX_CHARS) + '…';
		} catch {
			errored = true;
		} finally {
			loading = false;
		}
	}

	onMount(load);
</script>

<div data-testid="mini-code" class="text-xs">
	{#if loading}
		<div class="font-mono text-gray-400 dark:text-gray-500 animate-pulse">Loading preview…</div>
	{:else if errored || !snippet}
		<div class="text-gray-500 italic">Code · {item.filename}</div>
	{:else}
		<pre
			class="font-mono leading-snug text-gray-700 dark:text-gray-300 overflow-hidden whitespace-pre-wrap break-all m-0"
			style="max-height: 11em;">{snippet}</pre>
	{/if}
</div>
