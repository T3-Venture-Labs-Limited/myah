<script lang="ts">
	import {
		artifactOpenFiles,
		artifactActiveTabIdx,
		artifactPaneOpen,
		artifactSelection
	} from '$lib/stores';
	import type { ArtifactFile } from '$lib/types/artifact';
	import { ActivityTracker } from './ActivityTracker';
	import ArtifactTabs from './ArtifactTabs.svelte';
	import ArtifactExplorer from './ArtifactExplorer.svelte';
	import ArtifactViewer from './ArtifactViewer.svelte';

	export let chatId: string;
	export let token: string;

	// Activity tracker is per-chat; reset when chatId changes.
	let activityTracker = new ActivityTracker();

	// 2026-05-05 dogfooding: tab + selection state leaks across chats because
	// the underlying stores are module-global. When the user switches chats,
	// flush all per-chat artifact state so the new chat opens with a clean
	// explorer view rather than the previous chat's tabs. We track the last
	// chatId we saw and only fire on actual transitions (not on first mount).
	let lastChatId: string | undefined = undefined;
	$: if (chatId !== lastChatId) {
		// Skip the first assignment (mount) — only flush on real transitions
		// so we don't blow away tabs the user just opened on initial load.
		if (lastChatId !== undefined) {
			artifactOpenFiles.set([]);
			artifactActiveTabIdx.set(-1);
			artifactSelection.set(null);
			activityTracker.reset();
		}
		lastChatId = chatId;
	}

	function openFile(file: ArtifactFile) {
		artifactOpenFiles.update((files) => {
			const existing = files.findIndex((f) => f.file_key === file.file_key);
			if (existing >= 0) {
				artifactActiveTabIdx.set(existing);
				return files;
			}
			// Tab limit: 10. Evict the oldest tab if needed (simple LRU).
			// Phase 4 may add a dirty-state confirmation; Phase 1 just evicts.
			const trimmed = files.length >= 10 ? files.slice(1) : files;
			const next = [...trimmed, file];
			artifactActiveTabIdx.set(next.length - 1);
			return next;
		});
	}

	function activateTab(e: CustomEvent<{ idx: number }>) {
		artifactActiveTabIdx.set(e.detail.idx);
		artifactSelection.set(null); // single-selection store: clear on tab switch
	}

	function closeTab(e: CustomEvent<{ idx: number }>) {
		const idx = e.detail.idx;
		artifactOpenFiles.update((files) => {
			const next = files.filter((_, i) => i !== idx);
			const currentIdx = $artifactActiveTabIdx;
			if (idx === currentIdx) {
				artifactActiveTabIdx.set(Math.max(-1, idx - 1));
			} else if (idx < currentIdx) {
				artifactActiveTabIdx.set(currentIdx - 1);
			}
			return next;
		});
		artifactSelection.set(null);
	}

	$: activeFile =
		$artifactActiveTabIdx >= 0 ? ($artifactOpenFiles[$artifactActiveTabIdx] ?? null) : null;
</script>

{#if $artifactPaneOpen}
	<div data-testid="artifact-pane" class="flex flex-col h-full bg-white dark:bg-gray-900">
		{#if $artifactOpenFiles.length > 0}
			<ArtifactTabs
				openFiles={$artifactOpenFiles}
				activeIdx={$artifactActiveTabIdx}
				{token}
				on:activate={activateTab}
				on:close={closeTab}
			/>
		{/if}

		<div class="flex-1 overflow-hidden">
			{#if $artifactActiveTabIdx === -1 || activeFile === null}
				<ArtifactExplorer
					{chatId}
					{token}
					{activityTracker}
					on:open={(e) => openFile(e.detail.file)}
				/>
			{:else}
				<ArtifactViewer file={activeFile} {token} />
			{/if}
		</div>
	</div>
{/if}
