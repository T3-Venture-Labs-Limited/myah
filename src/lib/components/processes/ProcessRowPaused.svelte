<script lang="ts">
	// Paused processes rest here — dimmed, quiet, waiting
	// for the day you decide to wake them.

	import type { Process } from '$lib/apis/processes';
	import { getScheduleDisplay, resumeProcess } from '$lib/apis/processes';
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	const i18n = getContext('i18n');

	export let process: Process;
	export let onUpdate: () => void;

	let isResuming = false;

	async function handleResume(e: Event) {
		e.stopPropagation();
		if (isResuming) return;
		isResuming = true;
		try {
			await resumeProcess(localStorage.token, process.id);
			toast.success('Process resumed');
			onUpdate();
		} catch (err) {
			toast.error(`${err}`);
		} finally {
			isResuming = false;
		}
	}
</script>

<div
	class="flex items-center justify-between rounded-xl border border-transparent hover:bg-neutral-900/30 px-3 py-2 transition-all duration-200"
>
	<span class="text-sm text-gray-500 truncate">
		{process.name}
	</span>

	<div class="flex items-center gap-3 flex-shrink-0">
		<span class="text-xs text-gray-600 hidden sm:inline">
			{getScheduleDisplay(process)}
		</span>

		<button
			class="flex items-center gap-1 text-xs text-emerald-400 hover:text-emerald-300 transition"
			disabled={isResuming}
			on:click={handleResume}
		>
			{#if isResuming}
				<div
					class="size-3 border-2 border-emerald-400/50 border-t-transparent rounded-full animate-spin"
				></div>
			{:else}
				<svg
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					stroke-width="1.5"
					stroke="currentColor"
					class="size-3"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 0 1 0 1.972l-11.54 6.347a1.125 1.125 0 0 1-1.667-.986V5.653Z"
					/>
				</svg>
				Resume
			{/if}
		</button>
	</div>
</div>
