<!-- platform/src/lib/components/tasks/TaskList.svelte -->
<!-- The left panel — a living record of every task asked, every thread still open. -->
<script lang="ts">
	import { onMount, onDestroy, getContext, createEventDispatcher, tick } from 'svelte';
	import { goto } from '$app/navigation';
	import { folders, activeChatIds, user, mobile, socket } from '$lib/stores';
	import {
		allTasks,
		processMap,
		taskStatusFilter,
		taskSpaceFilter,
		taskSearchQuery
	} from '$lib/stores/tasks';
	import { getChatList, deleteChatById, updateChatFolderIdById } from '$lib/apis/chats';
	import { getProcesses } from '$lib/apis/processes';
	import { getFolders } from '$lib/apis/folders';
	import { mergeChatsAndProcesses, filterTasks } from '$lib/utils/tasks';
	import type { TaskItem as TaskItemType } from '$lib/utils/tasks';
	import TaskItemRow from './TaskItem.svelte';
	import TaskFilters from './TaskFilters.svelte';
	import TaskContextMenu from './TaskContextMenu.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let selectedTaskId: string = '';

	let loading = false;
	let showSearch = false;
	let showFilters = false;
	let searchInputEl: HTMLInputElement;
	let newTaskInput = '';

	// Context menu state
	let contextMenuTask: any = null;
	let contextMenuShow = false;
	let contextMenuX = 0;
	let contextMenuY = 0;

	// Multi-select state
	let selectedTaskIds = new Set<string>();
	$: selectionMode = selectedTaskIds.size > 0;

	// Pagination state
	let currentPage = 1;
	let allChatsLoaded = false;
	let loadingMore = false;
	let scrollContainer: HTMLElement;

	// Reactive filtered list
	$: filteredTasks = filterTasks(
		$allTasks,
		{
			status: $taskStatusFilter,
			spaceId: $taskSpaceFilter,
			search: $taskSearchQuery
		},
		$activeChatIds
	);

	$: hasActiveFilters = $taskStatusFilter.length > 0 || $taskSpaceFilter !== null;

	async function loadTasks(reset = false) {
		if (reset) {
			currentPage = 1;
			allChatsLoaded = false;
		}
		if (loading || (allChatsLoaded && !reset)) return;
		loading = reset;
		loadingMore = !reset;

		try {
			const token = localStorage.token;

			// Fetch chats and processes in parallel on reset; chats only for pagination
			const [chatList, processes] = await Promise.all([
				getChatList(token, reset ? 1 : currentPage),
				reset ? getProcesses(token) : Promise.resolve(null)
			]);

			if (processes !== null) {
				// Build processMap keyed by every ID we might navigate to:
				// - proc.id (process UUID)
				// - proc.chat_id (explicit, if API ever returns it)
				// - the chat's ID matched by title "Process: {name}"
				const newMap = new Map<string, (typeof processes)[0]>();
				const chatByProcName = new Map<string, any>();
				for (const chat of chatList ?? []) {
					const t: string = chat.title ?? '';
					if (t.startsWith('Process: ')) {
						chatByProcName.set(t.slice(9), chat);
					}
				}
				for (const proc of processes) {
					// Always key by process ID
					newMap.set(proc.id, proc);
					// Key by explicit chat_id if present
					if (proc.chat_id) {
						newMap.set(proc.chat_id, proc);
					}
					// Key by linked chat ID found by title convention
					const linkedChat = chatByProcName.get(proc.name);
					if (linkedChat?.id) {
						newMap.set(linkedChat.id, proc);
					}
				}
				processMap.set(newMap);

				// Full merge on reset
				const merged = mergeChatsAndProcesses(chatList ?? [], processes);
				allTasks.set(merged);
			} else {
				// Pagination: append new chat-only tasks
				const processIds = new Set(
					[...$processMap.values()].map((p) => p.chat_id).filter(Boolean) as string[]
				);
				const newChatTasks: TaskItemType[] = (chatList ?? [])
					.filter((c: any) => !processIds.has(c.id))
					.map((chat: any) => ({
						id: chat.id,
						title: chat.title ?? 'New Chat',
						type: 'chat' as const,
						status: 'completed' as const,
						updated_at: chat.updated_at ?? 0,
						files: chat.meta?.files ?? [],
						chat,
						folder_id: chat.folder_id
					}));

				allTasks.update((prev) => [...prev, ...newChatTasks]);

				if ((chatList ?? []).length === 0) {
					allChatsLoaded = true;
				}
			}

			currentPage = reset ? 2 : currentPage + 1;
		} catch (err) {
			console.error('Failed to load tasks:', err);
		} finally {
			loading = false;
			loadingMore = false;
		}
	}

	async function loadFolders() {
		try {
			const result = await getFolders(localStorage.token);
			folders.set(result);
		} catch (err) {
			console.error('Failed to load spaces:', err);
		}
	}

	function handleScroll() {
		if (!scrollContainer || allChatsLoaded || loadingMore) return;
		const { scrollTop, scrollHeight, clientHeight } = scrollContainer;
		if (scrollHeight - scrollTop - clientHeight < 100) {
			loadTasks(false);
		}
	}

	function handleTaskSelect(e: CustomEvent<TaskItemType>) {
		dispatch('select', e.detail);
	}

	async function toggleSearch() {
		showSearch = !showSearch;
		if (showSearch) {
			await tick();
			searchInputEl?.focus();
		} else {
			taskSearchQuery.set('');
		}
	}

	function handleSearchInput(e: Event) {
		taskSearchQuery.set((e.target as HTMLInputElement).value);
	}

	function handleSearchKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			showSearch = false;
			taskSearchQuery.set('');
		}
	}

	async function handleNewTask() {
		const prompt = newTaskInput.trim();
		if (!prompt) return;
		newTaskInput = '';
		goto(`/?q=${encodeURIComponent(prompt)}`);
	}

	function handleMenuEvent(e: CustomEvent) {
		const { task, x, y } = e.detail;
		contextMenuTask = task;
		contextMenuX = x;
		contextMenuY = y;
		contextMenuShow = true;
	}

	function handleToggleSelect(e: CustomEvent) {
		const task = e.detail;
		const newSet = new Set(selectedTaskIds);
		if (newSet.has(task.id)) {
			newSet.delete(task.id);
		} else {
			newSet.add(task.id);
		}
		selectedTaskIds = newSet;
	}

	async function handleBulkDelete() {
		if (!confirm(`${$i18n.t('Delete')} ${selectedTaskIds.size} ${$i18n.t('tasks')}?`)) return;
		const ids = [...selectedTaskIds];
		for (const id of ids) {
			try {
				await deleteChatById(localStorage.token, id);
			} catch (err) {
				console.error('Failed to delete', id, err);
			}
		}
		selectedTaskIds = new Set();
		await loadTasks(true);
	}

	async function handleBulkMoveToSpace(folderId: string | null) {
		for (const id of selectedTaskIds) {
			try {
				await updateChatFolderIdById(localStorage.token, id, folderId ?? undefined);
			} catch (err) {
				console.error('Failed to move', id, err);
			}
		}
		selectedTaskIds = new Set();
		await loadTasks(true);
	}

	// Socket: refresh on process lifecycle events
	function handleProcessEvent() {
		loadTasks(true);
	}

	onMount(async () => {
		await Promise.all([loadTasks(true), loadFolders()]);

		if ($socket) {
			$socket.on('process:run-complete', handleProcessEvent);
			$socket.on('process:run-started', handleProcessEvent);
		}
	});

	onDestroy(() => {
		if ($socket) {
			$socket.off('process:run-complete', handleProcessEvent);
			$socket.off('process:run-started', handleProcessEvent);
		}
	});
</script>

<div class="flex flex-col h-full">
	<!-- Header -->
	<div class="flex-shrink-0 px-4 pt-4 pb-2">
		{#if selectionMode}
			<!-- Multi-select action bar -->
			<div class="flex items-center gap-2 mb-3">
				<span class="text-sm font-medium text-gray-700 dark:text-gray-300 flex-1">
					{selectedTaskIds.size}
					{$i18n.t('selected')}
				</span>
				<button
					class="px-3 py-1.5 text-sm rounded-lg bg-red-500 text-white hover:bg-red-600 transition"
					on:click={handleBulkDelete}
				>
					{$i18n.t('Delete')}
				</button>
				<button
					class="px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-850 transition text-gray-700 dark:text-gray-300"
					on:click={() => {
						selectedTaskIds = new Set();
					}}
				>
					{$i18n.t('Cancel')}
				</button>
			</div>
		{:else}
			<div class="flex items-center justify-between mb-3">
				<h2 class="text-base font-semibold text-gray-800 dark:text-gray-200">
					{$i18n.t('All tasks')}
				</h2>
				<div class="flex items-center gap-1">
					<!-- Search toggle -->
					<button
						class="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 transition {showSearch
							? 'bg-gray-100 dark:bg-gray-850'
							: ''}"
						on:click={toggleSearch}
						aria-label={$i18n.t('Search tasks')}
					>
						<svg
							class="size-4 text-gray-500"
							fill="none"
							viewBox="0 0 24 24"
							stroke="currentColor"
							stroke-width="1.5"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z"
							/>
						</svg>
					</button>

					<!-- Filter toggle -->
					<div class="relative">
						<button
							class="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 transition {hasActiveFilters ||
							showFilters
								? 'bg-gray-100 dark:bg-gray-850'
								: ''}"
							on:click={() => (showFilters = !showFilters)}
							aria-label={$i18n.t('Filter tasks')}
						>
							<svg
								class="size-4 {hasActiveFilters ? 'text-blue-500' : 'text-gray-500'}"
								fill="none"
								viewBox="0 0 24 24"
								stroke="currentColor"
								stroke-width="1.5"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									d="M12 3c2.755 0 5.455.232 8.083.678.533.09.917.556.917 1.096v1.044a2.25 2.25 0 0 1-.659 1.591l-5.432 5.432a2.25 2.25 0 0 0-.659 1.591v2.927a2.25 2.25 0 0 1-1.244 2.013L9.75 21v-6.568a2.25 2.25 0 0 0-.659-1.591L3.659 7.409A2.25 2.25 0 0 1 3 5.818V4.774c0-.54.384-1.006.917-1.096A48.32 48.32 0 0 1 12 3Z"
								/>
							</svg>
						</button>
						<TaskFilters bind:show={showFilters} />
					</div>

					<!-- Task count badge -->
					{#if filteredTasks.length > 0}
						<span class="text-xs text-gray-400 font-medium px-1">{filteredTasks.length}</span>
					{/if}
				</div>
			</div>
		{/if}

		<!-- Search input (shown when toggled) -->
		{#if showSearch}
			<div class="mb-2">
				<input
					bind:this={searchInputEl}
					type="text"
					placeholder={$i18n.t('Search tasks...')}
					value={$taskSearchQuery}
					on:input={handleSearchInput}
					on:keydown={handleSearchKeydown}
					class="w-full px-3 py-2 text-sm bg-gray-100 dark:bg-gray-850 border-0 rounded-xl outline-none focus:ring-1 focus:ring-gray-300 dark:focus:ring-gray-600 placeholder-gray-400 dark:placeholder-gray-500"
				/>
			</div>
		{/if}
	</div>

	<!-- Start a task input -->
	<div class="flex-shrink-0 px-3 pb-3 border-b border-gray-100 dark:border-gray-850">
		<form
			class="flex items-center gap-2 px-3 py-2.5 bg-gray-50 dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 focus-within:border-gray-300 dark:focus-within:border-gray-700 transition"
			on:submit|preventDefault={handleNewTask}
		>
			<input
				type="text"
				bind:value={newTaskInput}
				placeholder={$i18n.t('Start a task...')}
				class="flex-1 bg-transparent text-sm outline-none placeholder-gray-400 dark:placeholder-gray-500 text-gray-800 dark:text-gray-200"
			/>
			{#if newTaskInput.trim()}
				<button
					type="submit"
					class="p-1 rounded-lg bg-gray-900 dark:bg-white text-white dark:text-gray-900 hover:opacity-80 transition"
					aria-label={$i18n.t('Submit')}
				>
					<svg
						class="size-3.5"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
						stroke-width="2.5"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M4.5 10.5 12 3m0 0 7.5 7.5M12 3v18"
						/>
					</svg>
				</button>
			{/if}
		</form>
	</div>

	<!-- Task list -->
	<div
		bind:this={scrollContainer}
		class="flex-1 overflow-y-auto px-2 py-2"
		on:scroll={handleScroll}
	>
		{#if loading}
			<div class="flex items-center justify-center py-8">
				<Spinner className="size-5" />
			</div>
		{:else if filteredTasks.length === 0}
			<div class="flex items-center justify-center py-8">
				<p class="text-sm text-gray-400">
					{hasActiveFilters || $taskSearchQuery
						? $i18n.t('No tasks match filters')
						: $i18n.t('No tasks yet')}
				</p>
			</div>
		{:else}
			<div class="space-y-0.5">
				{#each filteredTasks as task (task.id)}
					<TaskItemRow
						{task}
						{selectionMode}
						isSelected={selectedTaskIds.has(task.id)}
						selected={task.id === selectedTaskId}
						on:select={handleTaskSelect}
						on:toggle-select={handleToggleSelect}
						on:menu={handleMenuEvent}
					/>
				{/each}
			</div>

			{#if loadingMore}
				<div class="flex justify-center py-4">
					<Spinner className="size-4" />
				</div>
			{/if}
		{/if}
	</div>

	<TaskContextMenu
		task={contextMenuTask}
		bind:show={contextMenuShow}
		x={contextMenuX}
		y={contextMenuY}
		on:refresh={() => loadTasks(true)}
	/>
</div>
