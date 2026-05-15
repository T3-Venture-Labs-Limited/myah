<!-- platform/src/lib/components/tasks/TaskContextMenu.svelte -->
<!-- Every action offered here is a promise — to move, to rename, to end. -->
<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	import { folders } from '$lib/stores';
	import { toast } from 'svelte-sonner';
	import {
		deleteChatById,
		updateChatFolderIdById,
		updateChatById,
		toggleChatPinnedStatusById
	} from '$lib/apis/chats';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let task: any;
	export let show = false;
	export let x = 0;
	export let y = 0;

	$: currentFolderId = task?.chat?.folder_id ?? null;

	async function handlePin() {
		show = false;
		try {
			await toggleChatPinnedStatusById(localStorage.token, task.id);
			dispatch('refresh');
		} catch (err) {
			toast.error($i18n.t('Failed to pin task'));
		}
	}

	async function handleRename() {
		show = false;
		const newTitle = prompt($i18n.t('Rename task:'), task.title);
		if (!newTitle || newTitle === task.title) return;
		try {
			await updateChatById(localStorage.token, task.id, { title: newTitle });
			dispatch('refresh');
		} catch (err) {
			toast.error($i18n.t('Failed to rename task'));
		}
	}

	async function handleMoveToSpace(folderId: string | null) {
		show = false;
		try {
			await updateChatFolderIdById(localStorage.token, task.id, folderId ?? undefined);
			dispatch('refresh');
		} catch (err) {
			toast.error($i18n.t('Failed to move task'));
		}
	}

	async function handleDelete() {
		show = false;
		if (!confirm(`${$i18n.t('Delete')} "${task.title}"?`)) return;
		try {
			await deleteChatById(localStorage.token, task.id);
			dispatch('refresh');
		} catch (err) {
			toast.error($i18n.t('Failed to delete task'));
		}
	}
</script>

{#if show}
	<!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
	<button
		class="fixed inset-0 z-40"
		on:click={() => (show = false)}
		tabindex="-1"
		aria-label={$i18n.t('Close menu')}
	></button>
	<div
		class="fixed z-50 w-48 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl shadow-lg py-1"
		style="left: {x}px; top: {y}px;"
	>
		<button
			class="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-850 text-gray-700 dark:text-gray-300"
			on:click={handlePin}
		>
			<svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					d="M15.75 5.25a3 3 0 0 1 3 3m3 0a6 6 0 0 1-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 0 1 21.75 8.25Z"
				/>
			</svg>
			{$i18n.t('Pin task')}
		</button>

		<button
			class="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-850 text-gray-700 dark:text-gray-300"
			on:click={handleRename}
		>
			<svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L10.582 16.07a4.5 4.5 0 0 1-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 0 1 1.13-1.897l8.932-8.931Zm0 0L19.5 7.125"
				/>
			</svg>
			{$i18n.t('Rename task')}
		</button>

		<div class="border-t border-gray-200 dark:border-gray-700 my-1"></div>

		<!-- Move to space -->
		<div class="px-2">
			<div class="text-xs text-gray-400 px-2 py-1">{$i18n.t('Move to space')}</div>
			{#if currentFolderId}
				<button
					class="w-full flex items-center gap-2 px-2 py-1.5 text-sm rounded-lg hover:bg-gray-50 dark:hover:bg-gray-850 text-gray-600 dark:text-gray-400"
					on:click={() => handleMoveToSpace(null)}
				>
					<svg
						class="size-3.5"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
						stroke-width="1.5"
					>
						<path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
					</svg>
					{$i18n.t('Remove from space')}
				</button>
			{/if}
			{#each ($folders as any[]) ?? [] as folder}
				{#if folder.id !== currentFolderId}
					<button
						class="w-full flex items-center gap-2 px-2 py-1.5 text-sm rounded-lg hover:bg-gray-50 dark:hover:bg-gray-850 text-gray-700 dark:text-gray-300"
						on:click={() => handleMoveToSpace(folder.id)}
					>
						<span>{folder.name}</span>
					</button>
				{/if}
			{/each}
		</div>

		<div class="border-t border-gray-200 dark:border-gray-700 my-1"></div>

		<button
			class="w-full flex items-center gap-2 px-3 py-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-850 text-red-500"
			on:click={handleDelete}
		>
			<svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0"
				/>
			</svg>
			{$i18n.t('Delete task')}
		</button>
	</div>
{/if}
