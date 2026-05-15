<script lang="ts">
	import { onMount, createEventDispatcher, getContext } from 'svelte';
	import type { Process, ProcessRun } from '$lib/apis/processes';
	import { getProcessRuns, getScheduleDisplay } from '$lib/apis/processes';
	import { folders } from '$lib/stores';
	import { stripProcessPrefix } from '$lib/utils/tasks';
	import SchedulePopover from './SchedulePopover.svelte';
	import RunCard from './RunCard.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Chat from '$lib/components/chat/Chat.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let process: Process;
	export let chatId: string = '';

	let runs: ProcessRun[] = [];
	let loading = true;
	let showSchedule = false;

	$: title = stripProcessPrefix(process.name);
	$: scheduleDisplay = getScheduleDisplay(process);
	$: isRunning = process.state === 'running';
	$: linkedFolder = (($folders as any[]) ?? []).find(
		(f: any) => f.id === (process as any).folder_id
	) as { name: string; id: string } | undefined;
	$: nextRunDisplay = process.next_run_at ? getTimeUntil(new Date(process.next_run_at)) : null;

	function getTimeUntil(date: Date): string {
		const now = new Date();
		const diff = date.getTime() - now.getTime();
		if (diff <= 0) return 'now';
		const minutes = Math.floor(diff / 60000);
		const hours = Math.floor(minutes / 60);
		if (hours > 0) return `${hours}h ${minutes % 60}m`;
		return `${minutes} minutes`;
	}

	async function loadRuns() {
		loading = true;
		try {
			runs = (await getProcessRuns(localStorage.token, process.id)) ?? [];
		} catch (err) {
			console.error('Failed to load runs:', err);
			runs = [];
		} finally {
			loading = false;
		}
	}

	onMount(loadRuns);
</script>

<div class="flex flex-col h-full">
	<!-- Header -->
	<div
		class="flex items-center gap-2 px-4 py-3 border-b border-gray-100 dark:border-gray-850 flex-shrink-0"
	>
		<!-- Sidebar toggle (replaces back button) -->
		<button
			class="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 transition"
			on:click={() => dispatch('expand')}
			aria-label="Toggle task list"
		>
			<svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					d="M3.75 6.75h16.5M3.75 12h16.5M3.75 17.25h16.5"
				/>
			</svg>
		</button>

		<h1 class="text-sm font-semibold truncate flex-1 text-gray-800 dark:text-gray-200">{title}</h1>

		{#if linkedFolder != null}
			<span
				class="px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-xs text-gray-500 flex-shrink-0"
			>
				{linkedFolder.name}
			</span>
		{/if}

		<div class="relative flex-shrink-0">
			<button
				class="px-3 py-1.5 text-xs rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-850 transition text-gray-700 dark:text-gray-300"
				on:click={() => (showSchedule = !showSchedule)}
			>
				Schedule
			</button>
			<SchedulePopover {process} bind:show={showSchedule} on:refresh={loadRuns} />
		</div>

		<button
			class="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 transition flex-shrink-0"
			on:click={() => dispatch('expand')}
			aria-label="Toggle full width"
		>
			<svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15"
				/>
			</svg>
		</button>
	</div>

	<!-- Run log (collapsible top section) -->
	<div
		class="flex-shrink-0 max-h-[40%] overflow-y-auto px-4 py-4 border-b border-gray-100 dark:border-gray-850"
	>
		<!-- Scheduled task chip -->
		<div class="mb-3">
			<span
				class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-gray-100 dark:bg-gray-850 text-sm text-gray-600 dark:text-gray-400"
			>
				<svg
					class="size-3.5"
					fill="none"
					viewBox="0 0 24 24"
					stroke="currentColor"
					stroke-width="1.5"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"
					/>
				</svg>
				Scheduled task: {scheduleDisplay}
			</span>
		</div>

		{#if isRunning}
			<div class="flex items-center gap-2 mb-3 text-sm text-gray-500 dark:text-gray-400">
				<Spinner className="size-4" />
				<span>Running scheduled task</span>
			</div>
		{/if}

		{#if loading}
			<div class="flex items-center justify-center py-4">
				<Spinner className="size-5" />
			</div>
		{:else if runs.length === 0}
			<div class="text-center text-sm text-gray-400 py-4">No runs yet</div>
		{:else}
			<div class="space-y-2">
				{#each runs as run (run.id)}
					<RunCard {run} />
				{/each}
			</div>
		{/if}

		{#if nextRunDisplay}
			<div class="mt-3 text-xs text-gray-400">
				{title} · next run in {nextRunDisplay}
			</div>
		{/if}
	</div>

	<!-- Chat with agent about this process (full embedded chat) -->
	{#if chatId}
		<div class="flex-1 min-h-0">
			<Chat chatIdProp={chatId} embedded={true} on:expand={() => dispatch('expand')} />
		</div>
	{/if}
</div>
