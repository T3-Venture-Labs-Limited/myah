<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import { MYAH_API_BASE_URL } from '$lib/constants';
	import { closeArtifactPane } from '$lib/stores';
	import type { ArtifactFile } from '$lib/types/artifact';

	export let openFiles: ArtifactFile[];
	export let activeIdx: number;
	export let token: string = '';

	const dispatch = createEventDispatcher<{
		activate: { idx: number };
		close: { idx: number };
	}>();

	$: activeFile = activeIdx >= 0 ? (openFiles[activeIdx] ?? null) : null;

	$: downloadUrl = activeFile?.file_id
		? `${MYAH_API_BASE_URL}/files/${activeFile.file_id}/content`
		: activeFile?.path
			? `${MYAH_API_BASE_URL}/hermes/media?path=${encodeURIComponent(activeFile.path)}`
			: null;

	let copied = false;
	const copyContents = async () => {
		if (!downloadUrl) return;
		try {
			const headers: Record<string, string> = {};
			if (token) headers['Authorization'] = `Bearer ${token}`;
			const res = await fetch(downloadUrl, { headers });
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const text = await res.text();
			await navigator.clipboard.writeText(text);
			copied = true;
			setTimeout(() => (copied = false), 1500);
		} catch (e) {
			console.error('Failed to copy contents:', e);
		}
	};

	const onWheel = (e: WheelEvent) => {
		if (e.deltaY === 0) return;
		const target = e.currentTarget as HTMLElement;
		if (target.scrollWidth > target.clientWidth) {
			e.preventDefault();
			target.scrollLeft += e.deltaY;
		}
	};
</script>

<div
	data-testid="artifact-tabs"
	class="flex items-center border-b border-gray-100 dark:border-gray-800"
>
	<div
		class="flex items-center overflow-x-auto flex-1 min-w-0 no-scrollbar"
		on:wheel={onWheel}
	>
		<button
				type="button"
				aria-label="Back to file explorer"
				class="px-3 py-2 text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-850 {activeIdx === -1
					? 'bg-gray-50 dark:bg-gray-850'
					: ''}"
				on:click={() => dispatch('activate', { idx: -1 })}
			>
				📁
			</button>

		{#each openFiles as file, i (file.file_key)}
			<div
				class="flex items-center gap-2 px-3 py-2 border-r border-gray-100 dark:border-gray-800 {i ===
				activeIdx
					? 'bg-white dark:bg-gray-900 border-t-2 border-t-pink-500'
					: ''}"
			>
				<button
					type="button"
					class="text-sm truncate max-w-[160px]"
					on:click={() => dispatch('activate', { idx: i })}
					on:auxclick={(e) => {
						if (e.button === 1) dispatch('close', { idx: i });
					}}
				>
					{file.filename}
				</button>
				<button
					type="button"
					aria-label={`Close ${file.filename}`}
					class="text-gray-400 hover:text-gray-700"
					on:click|stopPropagation={() => dispatch('close', { idx: i })}
				>
					✕
				</button>
			</div>
		{/each}
	</div>

	<!-- Right-side action strip: download / open / copy URL / close-pane.
	     Hidden in explorer view (activeIdx === -1) where there is no active file. -->
	{#if activeFile && downloadUrl}
		<div class="flex items-center shrink-0 px-2 border-l border-gray-100 dark:border-gray-800">
			<a
				href={downloadUrl}
				download={activeFile.filename}
				title="Download"
				aria-label="Download artifact"
				data-testid="artifact-action-download"
				class="ml-1 p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 dark:text-gray-400 transition shrink-0"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
					class="size-4"
				>
					<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
					<polyline points="7 10 12 15 17 10" />
					<line x1="12" y1="15" x2="12" y2="3" />
				</svg>
			</a>
			<button
				type="button"
				on:click={copyContents}
				title={copied ? 'Copied' : 'Copy contents'}
				aria-label={copied ? 'Contents copied' : 'Copy artifact contents'}
				data-testid="artifact-action-copy-contents"
				class="ml-1 p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 dark:text-gray-400 transition shrink-0"
			>
				{#if copied}
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
						class="size-4 text-green-500"
					>
						<polyline points="20 6 9 17 4 12" />
					</svg>
				{:else}
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
						class="size-4"
					>
						<rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
						<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
					</svg>
				{/if}
			</button>
			<button
				type="button"
				on:click={() => closeArtifactPane()}
				title="Close pane"
				aria-label="Close artifact pane"
				data-testid="artifact-action-close"
				class="ml-1 p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 dark:text-gray-400 transition shrink-0"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					class="size-4"
					viewBox="0 0 20 20"
					fill="currentColor"
				>
					<path
						fill-rule="evenodd"
						d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
						clip-rule="evenodd"
					/>
				</svg>
			</button>
		</div>
	{/if}
</div>

<style>
	.no-scrollbar {
		scrollbar-width: none;
		-ms-overflow-style: none;
	}
	.no-scrollbar::-webkit-scrollbar {
		display: none;
	}
</style>
