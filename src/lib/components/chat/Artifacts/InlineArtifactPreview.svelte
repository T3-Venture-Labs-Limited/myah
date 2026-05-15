<script lang="ts">
	// The card sits next to the message like a knock at the door —
	// open it and the artifact pane steps into the room.
	import type { ArtifactCardItem } from '$lib/types/contract';
	import { artifactOpenFiles, artifactActiveTabIdx, artifactPaneOpen } from '$lib/stores';
	import MiniPreview from './MiniPreview.svelte';

	export let item: ArtifactCardItem;

	function open() {
		const file = {
			file_key: item.file_id ? `file_id:${item.file_id}` : `path:${item.path}`,
			file_id: item.file_id ?? undefined,
			path: item.path ?? undefined,
			filename: item.filename,
			mime: item.mime ?? undefined,
			mtime: item.mtime,
			source: 'agent-tool' as const
		};
		artifactOpenFiles.update((files) => {
			const existing = files.findIndex((f) => f.file_key === file.file_key);
			if (existing >= 0) {
				artifactActiveTabIdx.set(existing);
				return files;
			}
			const next = [...files, file];
			artifactActiveTabIdx.set(next.length - 1);
			return next;
		});
		artifactPaneOpen.set(true);
	}
</script>

<div
	data-testid="inline-artifact-preview"
	class="my-2 border border-gray-200 dark:border-gray-800 rounded-lg overflow-hidden max-w-md"
>
	<header
		class="flex items-center justify-between px-3 py-2 bg-gray-50 dark:bg-gray-850 border-b border-gray-100 dark:border-gray-800"
	>
		<div class="text-xs">
			<span class="font-medium">{item.filename}</span>
			<span class="text-gray-500 ml-2">{item.mime ?? item.kind}</span>
		</div>
	</header>
	<div class="p-3">
		<MiniPreview {item} />
	</div>
	<footer
		class="flex items-center justify-end gap-2 px-3 py-2 border-t border-gray-100 dark:border-gray-800"
	>
		{#if item.summary}
			<span class="text-xs text-gray-500 mr-auto">{item.summary}</span>
		{/if}
		<button
			type="button"
			data-testid="inline-artifact-open"
			class="text-xs px-2 py-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800"
			on:click={open}
		>
			Open
		</button>
		<a
			data-testid="inline-artifact-download"
			class="text-xs px-2 py-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800"
			href={item.file_id
				? `/api/v1/files/${item.file_id}/content`
				: `/api/v1/hermes/media?path=${encodeURIComponent(item.path ?? '')}`}
			download={item.filename}
		>
			Download
		</a>
	</footer>
</div>
