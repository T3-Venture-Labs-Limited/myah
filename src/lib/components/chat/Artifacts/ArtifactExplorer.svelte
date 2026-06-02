<script lang="ts">
	import { onMount, createEventDispatcher } from 'svelte';
	import { getChatFiles } from '$lib/apis/chats';
	import { artifactExplorerRefreshTick } from '$lib/stores';
	import type { ArtifactFile } from '$lib/types/artifact';
	import { ActivityTracker } from './ActivityTracker';
	import ArtifactExplorerRow from './ArtifactExplorerRow.svelte';

	export let chatId: string;
	export let token: string;
	export let activityTracker: ActivityTracker = new ActivityTracker();

	const dispatch = createEventDispatcher<{ open: { file: ArtifactFile } }>();

	let files: ArtifactFile[] = [];
	let loading = true;
	let error: Error | null = null;
	let initialized = false;
	let lastSeenRefreshTick = -1;
	let lastChatIdLoaded = chatId;

	async function load(opts: { silent?: boolean } = {}) {
		if (!opts.silent) loading = true;
		error = null;
		try {
			if (!chatId) {
				files = [];
				return;
			}
			const raw = await getChatFiles(token, chatId);
			const seen = new Set<string>();
			const deduped: ArtifactFile[] = [];
			for (const f of raw ?? []) {
				if (seen.has(f.file_id)) continue;
				seen.add(f.file_id);
				deduped.push({
					file_key: `file_id:${f.file_id}`,
					file_id: f.file_id,
					filename: f.filename ?? 'untitled',
					mime: f.mime_type,
					size: f.size,
					mtime: (f.created_at ?? 0) * 1000,
					source: 'message-attachment' as const
				});
			}
			deduped.sort((a, b) => (b.mtime ?? 0) - (a.mtime ?? 0));
			files = deduped;
		} catch (e) {
			error = e instanceof Error ? e : new Error(String(e));
		} finally {
			loading = false;
			initialized = true;
		}
	}

	onMount(() => {
		lastSeenRefreshTick = $artifactExplorerRefreshTick;
		load();
	});

	$: if (initialized && chatId !== lastChatIdLoaded) {
		lastChatIdLoaded = chatId;
		load();
	}

	$: if (
		initialized &&
		$artifactExplorerRefreshTick !== lastSeenRefreshTick &&
		typeof window !== 'undefined'
	) {
		lastSeenRefreshTick = $artifactExplorerRefreshTick;
		load({ silent: true });
	}
</script>

<div class="flex flex-col h-full" data-testid="artifact-explorer">
	<header
		class="flex items-center justify-between gap-2 px-3 py-2 border-b border-gray-100 dark:border-gray-800"
	>
		<h2 class="text-sm font-medium shrink-0">Files</h2>
	</header>

	{#if loading}
		{#each Array(4) as _, i (i)}
			<div class="px-3 py-2 animate-pulse h-9 bg-gray-50 dark:bg-gray-850"></div>
		{/each}
	{:else if error}
		<div class="flex flex-col items-center gap-3 py-8 text-sm text-gray-600">
			<p>Failed to load files.</p>
			<button class="px-3 py-1 rounded bg-gray-100 dark:bg-gray-800" on:click={() => load()}>
				Retry
			</button>
		</div>
	{:else if files.length === 0}
		<div class="py-8 text-sm text-gray-500 text-center">
			No files yet. Files will appear here as Myah creates them.
		</div>
	{:else}
		<div class="flex-1 overflow-auto">
			{#each files as file (file.file_key)}
				<ArtifactExplorerRow
					{file}
					verb={activityTracker.lastOp(file.file_key)}
					isLive={activityTracker.isLive(file.file_key)}
					on:open={(e) => dispatch('open', e.detail)}
				/>
			{/each}
		</div>

		{#if activityTracker.liveEntries().length > 0}
			<footer
				class="border-t border-gray-100 dark:border-gray-800 px-3 py-2 text-xs text-orange-500 flex items-center gap-2"
			>
				<span class="w-2 h-2 rounded-full bg-orange-500 animate-pulse"></span>
				<span>
					Myah is editing {activityTracker.liveEntries()[0][0].split(/[/]/).pop()}
				</span>
			</footer>
		{/if}
	{/if}
</div>
