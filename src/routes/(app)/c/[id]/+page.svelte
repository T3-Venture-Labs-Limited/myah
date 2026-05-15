<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { mobile } from '$lib/stores';
	import { showTaskList, processMap } from '$lib/stores/tasks';
	import { syncProcessChat } from '$lib/apis/processes';
	import Chat from '$lib/components/chat/Chat.svelte';

	$: taskId = $page.params.id ?? '';
	$: linkedProcess = taskId ? ($processMap.get(taskId) ?? null) : null;

	$: chatIdProp = taskId;

	onMount(() => {
		showTaskList.set(!$mobile);

		if (linkedProcess) {
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
	<Chat {chatIdProp} {linkedProcess} embedded={true} on:expand={handleExpand} />
{/key}
