<script lang="ts">
	// JSON glance: pretty-printed, top-level keys hinted,
	// the rest folded under quiet ellipses.
	import { onMount } from 'svelte';
	import { MYAH_API_BASE_URL } from '$lib/constants';
	import type { ArtifactCardItem } from '$lib/types/contract';

	export let item: ArtifactCardItem;

	const MAX_LINES = 10;
	const MAX_CHARS = 600;

	let snippet = '';
	let loading = !!item.file_id || !!item.path;
	let errored = false;

	async function load() {
		if (!item.file_id && !item.path) {
			loading = false;
			return;
		}
		try {
			let text = '';
			if (item.file_id) {
				const res = await fetch(`${MYAH_API_BASE_URL}/files/${item.file_id}/content`, {
					credentials: 'include'
				});
				if (!res.ok) throw new Error(`HTTP ${res.status}`);
				text = await res.text();
			} else if (item.path) {
				const res = await fetch(
					`${MYAH_API_BASE_URL}/hermes/media?path=${encodeURIComponent(item.path)}`,
					{ credentials: 'include' }
				);
				if (!res.ok) throw new Error(`HTTP ${res.status}`);
				text = await res.text();
			}
			try {
				snippet = JSON.stringify(JSON.parse(text), null, 2);
			} catch {
				snippet = text;
			}
			const lines = snippet.split('\n').slice(0, MAX_LINES);
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

<div data-testid="mini-json" class="text-xs">
	{#if loading}
		<div class="font-mono text-gray-400 dark:text-gray-500 animate-pulse">Loading preview…</div>
	{:else if errored || !snippet}
		<div class="text-gray-500 italic">JSON · {item.filename}</div>
	{:else}
		<pre
			class="font-mono leading-snug text-gray-700 dark:text-gray-300 overflow-hidden whitespace-pre-wrap break-all m-0"
			style="max-height: 11em;">{snippet}</pre>
	{/if}
</div>
