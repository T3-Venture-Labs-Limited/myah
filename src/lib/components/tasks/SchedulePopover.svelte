<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import type { Process } from '$lib/apis/processes';
	import {
		getScheduleDisplay,
		pauseProcess,
		resumeProcess,
		triggerProcess
	} from '$lib/apis/processes';
	import { processMap } from '$lib/stores/tasks';
	import { toast } from 'svelte-sonner';

	export let process: Process;
	export let show = false;

	const dispatch = createEventDispatcher();

	// Loading flags so the buttons disable while a request is in flight,
	// preventing double-submits and giving the user visible feedback that
	// the click was received.
	let pauseResumeBusy = false;
	let runNowBusy = false;

	$: scheduleDisplay = getScheduleDisplay(process);
	$: isPaused = process.state === 'paused' || !process.enabled;
	$: nextRun = process.next_run_at ? new Date(process.next_run_at) : null;

	function getTimeUntil(date: Date): string {
		const now = new Date();
		const diff = date.getTime() - now.getTime();
		if (diff <= 0) return 'now';
		const minutes = Math.floor(diff / 60000);
		const hours = Math.floor(minutes / 60);
		if (hours > 0) return `in ${hours}h ${minutes % 60}m`;
		return `in ${minutes}m`;
	}

	function _toastErrorMessage(err: unknown, fallback: string): string {
		// Match the rest of the codebase's API-error pattern: backend errors
		// surface as ``{ detail: '...' }``; the apis/processes layer rethrows
		// either the detail string or the raw object.
		if (typeof err === 'string' && err.trim()) return err;
		if (err && typeof err === 'object') {
			const e = err as { detail?: string; message?: string };
			if (typeof e.detail === 'string' && e.detail.trim()) return e.detail;
			if (typeof e.message === 'string' && e.message.trim()) return e.message;
		}
		return fallback;
	}

	function _syncProcessMap(updated: Process) {
		// Keep the global processMap (TaskList.svelte populates this) in lockstep
		// with the new state.  TaskList writes the same Process under three keys
		// — ``proc.id``, ``proc.chat_id``, and the title-matched chat id — so any
		// reactive consumer (chat route's linkedProcess, RecurringTaskDetail,
		// the sidebar status pill, …) updates immediately without waiting for
		// the next ``getProcesses`` poll.
		processMap.update((m) => {
			const next = new Map(m);
			next.set(updated.id, updated);
			if (updated.chat_id) {
				next.set(updated.chat_id, updated);
			}
			// Preserve any title-convention key the parent set up; if it pointed
			// at the same process by id, the new value automatically replaces it
			// for any key already mapped to this process.id.
			for (const [k, v] of m.entries()) {
				if (v.id === updated.id) next.set(k, updated);
			}
			return next;
		});
	}

	async function handlePauseResume() {
		if (pauseResumeBusy) return;
		pauseResumeBusy = true;
		const wasPaused = isPaused;
		try {
			const token = localStorage.token;
			const updated = wasPaused
				? await resumeProcess(token, process.id)
				: await pauseProcess(token, process.id);
			// Update local prop so the button label flips immediately and the
			// status pill reflects the new state without waiting for the
			// parent to refetch.  The parent still receives `refresh` so any
			// other UI bound to the same Process can update too.
			if (updated && typeof updated === 'object') {
				process = updated as Process;
				_syncProcessMap(updated as Process);
			}
			dispatch('refresh');
			toast.success(wasPaused ? 'Schedule resumed' : 'Schedule paused');
		} catch (err) {
			console.error(err);
			toast.error(
				_toastErrorMessage(
					err,
					wasPaused ? 'Failed to resume schedule' : 'Failed to pause schedule'
				)
			);
		} finally {
			pauseResumeBusy = false;
		}
	}

	async function handleRunNow() {
		if (runNowBusy) return;
		runNowBusy = true;
		try {
			const updated = await triggerProcess(localStorage.token, process.id);
			// Hermes returns the job dict; reflect the new ``next_run_at`` so
			// the popover's "Next run: in 0m" line jumps to "now" right away.
			if (updated && typeof updated === 'object') {
				process = updated as Process;
				_syncProcessMap(updated as Process);
			}
			dispatch('refresh');
			toast.success('Task triggered — next run scheduled now');
		} catch (err) {
			console.error(err);
			toast.error(_toastErrorMessage(err, 'Failed to trigger task'));
		} finally {
			runNowBusy = false;
		}
	}
</script>

{#if show}
	<button
		class="fixed inset-0 z-40"
		on:click={() => (show = false)}
		tabindex="-1"
		aria-label="Close"
	></button>
	<div
		class="absolute top-full right-0 mt-1 z-50 w-72 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl shadow-lg p-4"
	>
		<div class="text-sm font-semibold mb-3 text-gray-800 dark:text-gray-200">Schedule</div>
		<div class="space-y-2.5 text-sm">
			<div class="flex justify-between items-center">
				<span class="text-gray-500 dark:text-gray-400">Schedule</span>
				<span class="text-gray-800 dark:text-gray-200 font-medium">{scheduleDisplay}</span>
			</div>
			{#if nextRun}
				<div class="flex justify-between items-center">
					<span class="text-gray-500 dark:text-gray-400">Next run</span>
					<span class="text-gray-800 dark:text-gray-200">{getTimeUntil(nextRun)}</span>
				</div>
			{/if}
			<div class="flex justify-between items-center">
				<span class="text-gray-500 dark:text-gray-400">Status</span>
				<span
					class="px-2 py-0.5 rounded-full text-xs font-medium {isPaused
						? 'bg-gray-100 dark:bg-gray-800 text-gray-500'
						: 'bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400'}"
				>
					{isPaused ? 'Paused' : 'Active'}
				</span>
			</div>
			<div class="flex gap-2 pt-1">
				<button
					class="flex-1 px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 transition text-gray-700 dark:text-gray-300 disabled:opacity-60 disabled:cursor-not-allowed"
					on:click={handlePauseResume}
					disabled={pauseResumeBusy}
				>
					{#if pauseResumeBusy}
						{isPaused ? 'Resuming…' : 'Pausing…'}
					{:else}
						{isPaused ? 'Resume' : 'Pause'}
					{/if}
				</button>
				<button
					class="flex-1 px-3 py-1.5 text-sm rounded-lg bg-gray-900 dark:bg-white text-white dark:text-gray-900 hover:opacity-90 transition disabled:opacity-60 disabled:cursor-not-allowed"
					on:click={handleRunNow}
					disabled={runNowBusy}
				>
					{runNowBusy ? 'Triggering…' : 'Run Now'}
				</button>
			</div>
		</div>
	</div>
{/if}
