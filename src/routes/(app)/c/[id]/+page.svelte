<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { mobile } from '$lib/stores';
	import { showTaskList, processMap } from '$lib/stores/tasks';
	import { syncProcessChat } from '$lib/apis/processes';
	import { isProcessAdoptable } from '$lib/utils/tasks';
	import Chat from '$lib/components/chat/Chat.svelte';
	import AdoptProcessCard from '$lib/components/tasks/AdoptProcessCard.svelte';

	$: taskId = $page.params.id ?? '';
	$: linkedProcess = taskId ? ($processMap.get(taskId) ?? null) : null;
	// Adopt Legacy Crons (Phase 6): a recurring task with no linked Myah chat
	// shows the Adopt affordance instead of a fake empty chat at /c/{job_id}.
	$: adoptable = linkedProcess ? isProcessAdoptable(linkedProcess) : false;

	$: chatIdProp = taskId;

	onMount(() => {
		showTaskList.set(!$mobile);

		// Adoptable crons have no chat to sync yet — adoption creates it.
		if (linkedProcess && !adoptable) {
			syncProcessChat(localStorage.token, linkedProcess.id).catch(() => {});
		}
	});

	function handleExpand() {
		showTaskList.update((v) => !v);
	}
</script>

<!--
	{#key taskId} forces Chat to fully remount when switching between tasks,
	ensuring navigateHandler fires cleanly for every task change.
-->
{#key taskId}
	{#if adoptable && linkedProcess}
		<AdoptProcessCard process={linkedProcess} />
	{:else}
		<Chat {chatIdProp} {linkedProcess} embedded={true} on:expand={handleExpand} />
	{/if}
{/key}
