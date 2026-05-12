<script lang="ts">
	import { onMount, onDestroy, getContext } from 'svelte';
	import { page } from '$app/stores';
	import { getFolderById } from '$lib/apis/folders';
	import { selectedFolder } from '$lib/stores';
	import Chat from '$lib/components/chat/Chat.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	const i18n = getContext('i18n');

	$: spaceId = $page.params.id ?? '';

	let loading = true;

	async function loadSpace(id: string) {
		if (!id) return;
		loading = true;
		try {
			const folder = await getFolderById(localStorage.token, id);
			selectedFolder.set(folder);
		} catch (err) {
			console.error('Failed to load space:', err);
			selectedFolder.set(null);
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		loadSpace(spaceId);
	});

	// Reload when the space ID changes (e.g. navigating between spaces)
	$: loadSpace(spaceId);

	onDestroy(() => {
		// Clear selectedFolder when leaving so it doesn't affect other pages
		selectedFolder.set(null);
	});
</script>

<svelte:head><title>{($selectedFolder as any)?.name ?? 'Space'}</title></svelte:head>

{#if loading}
	<div class="flex items-center justify-center h-full">
		<Spinner className="size-6" />
	</div>
{:else}
	<!-- Render the full Chat home screen with this space's folder pre-selected.
	     Chat.svelte detects $selectedFolder and shows FolderPlaceholder automatically,
	     which displays the space's chats and a full MessageInput scoped to this folder. -->
	<Chat chatIdProp="" />
{/if}
