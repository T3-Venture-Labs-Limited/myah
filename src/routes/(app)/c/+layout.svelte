<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { mobile } from '$lib/stores';
	import { showTaskList, taskListWidth, allTasks } from '$lib/stores/tasks';
	import TaskList from '$lib/components/tasks/TaskList.svelte';

	$: selectedTaskId = $page.params?.id ?? '';

	$: firstSelectableTask = $allTasks[0] ?? null;
	$: if ($page.route.id === '/(app)/c' && firstSelectableTask && !selectedTaskId) {
		goto(`/c/${firstSelectableTask.chatId ?? firstSelectableTask.id}`, { replaceState: true });
	}

	function handleTaskSelect(e: CustomEvent) {
		const task = e.detail;
		if ($mobile) showTaskList.set(false);
		goto(`/c/${task.chatId ?? task.id}`);
	}

	let isResizing = false;
	let startWidth = 0;
	let startClientX = 0;

	function resizeStart(e: MouseEvent) {
		isResizing = true;
		startWidth = $taskListWidth;
		startClientX = e.clientX;
		window.addEventListener('mousemove', resizeMove);
		window.addEventListener('mouseup', resizeEnd);
	}

	function resizeMove(e: MouseEvent) {
		if (!isResizing) return;
		const delta = e.clientX - startClientX;
		const newWidth = Math.max(280, Math.min(600, startWidth + delta));
		taskListWidth.set(newWidth);
	}

	function resizeEnd() {
		isResizing = false;
		window.removeEventListener('mousemove', resizeMove);
		window.removeEventListener('mouseup', resizeEnd);
	}
</script>

<svelte:head>
	<title>Tasks</title>
</svelte:head>

<div class="flex h-screen max-h-[100dvh] w-full overflow-hidden">
	{#if $showTaskList && !$mobile}
		<div
			class="flex-shrink-0 h-full border-r border-gray-100 dark:border-gray-850 relative"
			style="width: {$taskListWidth}px"
		>
			<TaskList {selectedTaskId} on:select={handleTaskSelect} />

			<!-- svelte-ignore a11y-no-static-element-interactions -->
			<div
				class="absolute top-0 end-0 h-full w-1 cursor-col-resize hover:bg-gray-300 dark:hover:bg-gray-700 transition-colors z-10"
				on:mousedown={resizeStart}
			></div>
		</div>
	{/if}

	<div class="flex-1 min-w-0 h-full overflow-hidden">
		<slot />
	</div>
</div>

{#if $showTaskList && $mobile}
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div
		class="fixed z-40 top-0 right-0 left-0 bottom-0 bg-black/60 w-full min-h-screen h-screen overscroll-contain"
		on:mousedown={() => showTaskList.set(false)}
	></div>
	<div
		class="fixed z-50 top-0 left-0 h-screen max-h-[100dvh] min-h-screen select-none bg-gray-50 text-gray-900 dark:bg-gray-950 dark:text-gray-200 text-sm overflow-x-hidden flex-shrink-0"
		style="width: min(320px, 100vw)"
	>
		<TaskList {selectedTaskId} on:select={handleTaskSelect} />
	</div>
{/if}
