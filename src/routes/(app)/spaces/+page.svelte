<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { folders } from '$lib/stores';
	import { getFolders, createNewFolder } from '$lib/apis/folders';
	import FolderModal from '$lib/components/layout/Sidebar/Folders/FolderModal.svelte';
	import SpaceCard from '$lib/components/spaces/SpaceCard.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	const i18n = getContext('i18n');

	let loading = true;
	let showCreateModal = false;

	async function loadSpaces() {
		loading = true;
		try {
			const result = await getFolders(localStorage.token);
			folders.set(result ?? []);
		} catch (err) {
			console.error('Failed to load spaces:', err);
		} finally {
			loading = false;
		}
	}

	async function handleSpaceCreate(folderForm: any) {
		await createNewFolder(localStorage.token, folderForm);
		await loadSpaces();
	}

	onMount(loadSpaces);

	// Show only root-level spaces (no parent)
	$: rootSpaces = (($folders as any[]) ?? []).filter((f: any) => !f.parent_id);
</script>

<svelte:head><title>Spaces</title></svelte:head>

<div class="h-full overflow-y-auto">
	<div class="max-w-4xl mx-auto px-6 py-8">
		<div class="flex items-center justify-between mb-6">
			<h1 class="text-2xl font-semibold text-gray-800 dark:text-gray-200">{$i18n.t('Spaces')}</h1>
			<button
				class="px-4 py-2 text-sm rounded-xl bg-gray-900 dark:bg-white text-white dark:text-gray-900 hover:opacity-90 transition"
				on:click={() => (showCreateModal = true)}
			>
				{$i18n.t('New Space')}
			</button>
		</div>

		{#if loading}
			<div class="flex items-center justify-center py-12">
				<Spinner className="size-6" />
			</div>
		{:else if rootSpaces.length === 0}
			<div class="text-center py-12">
				<p class="text-sm text-gray-400">
					{$i18n.t('No spaces yet. Create one to organize your tasks.')}
				</p>
			</div>
		{:else}
			<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
				{#each rootSpaces as space (space.id)}
					<SpaceCard {space} />
				{/each}
			</div>
		{/if}
	</div>
</div>

<FolderModal bind:show={showCreateModal} onSubmit={handleSpaceCreate} />
