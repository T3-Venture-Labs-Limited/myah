<script lang="ts">
	// The compact card shows what's running at a glance —
	// a quick status pulse, the last headline, and quiet actions.

	import type { Process } from '$lib/apis/processes';
	import {
		getScheduleDisplay,
		pauseProcess,
		resumeProcess,
		triggerProcess,
		deleteProcess
	} from '$lib/apis/processes';
	import { getContext, onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	const i18n = getContext('i18n');

	export let process: Process;
	export let onUpdate: () => void;
	export let onDelete: () => void;

	let isTriggering = false;
	let isPausing = false;
	let showMenu = false;
	let menuRef: HTMLElement;

	$: isRunning = process.state === 'running';
	$: isEnabled = process.enabled && process.state !== 'paused';
	$: runCount =
		typeof process.repeat === 'object' && process.repeat !== null && 'completed' in process.repeat
			? (process.repeat as { completed: number }).completed
			: 0;

	function statusDotClass(): string {
		if (isRunning) return 'bg-blue-400 animate-pulse';
		if (process.last_status === 'error') return 'bg-red-400';
		return 'bg-emerald-400';
	}

	function formatRelativeTime(iso: string | null | undefined): string {
		if (!iso) return '';
		try {
			const diff = Date.now() - new Date(iso).getTime();
			const mins = Math.floor(diff / 60000);
			if (mins < 1) return 'just now';
			if (mins < 60) return `${mins}m ago`;
			const hrs = Math.floor(mins / 60);
			if (hrs < 24) return `${hrs}h ago`;
			return `${Math.floor(hrs / 24)}d ago`;
		} catch {
			return '';
		}
	}

	onMount(() => {
		function handleClickOutside(e: MouseEvent) {
			if (showMenu && menuRef && !menuRef.contains(e.target as Node)) {
				showMenu = false;
			}
		}
		document.addEventListener('click', handleClickOutside);
		return () => document.removeEventListener('click', handleClickOutside);
	});

	function goToDetail() {
		goto(`/c/${process.id}`);
	}

	async function handleTrigger(e: Event) {
		e.stopPropagation();
		if (isTriggering) return;
		isTriggering = true;
		try {
			await triggerProcess(localStorage.token, process.id);
			toast.success('Run queued — output will arrive in the chat shortly.');
			onUpdate();
		} catch (err) {
			toast.error(`${err}`);
		} finally {
			isTriggering = false;
		}
	}

	async function handleTogglePause(e: Event) {
		e.stopPropagation();
		if (isPausing) return;
		isPausing = true;
		try {
			if (isEnabled) {
				await pauseProcess(localStorage.token, process.id);
				toast.success('Process paused');
			} else {
				await resumeProcess(localStorage.token, process.id);
				toast.success('Process resumed');
			}
			onUpdate();
		} catch (err) {
			toast.error(`${err}`);
		} finally {
			isPausing = false;
		}
	}

	async function handleDelete(e: Event) {
		e.stopPropagation();
		showMenu = false;
		try {
			await deleteProcess(localStorage.token, process.id);
			toast.success('Process deleted');
			onDelete();
		} catch (err) {
			toast.error(`${err}`);
		}
	}
</script>

<div
	class="group relative rounded-xl bg-neutral-900/50 border border-neutral-800 hover:border-neutral-700 transition-all duration-200 cursor-pointer p-3"
	on:click={goToDetail}
	role="button"
	tabindex="0"
	on:keydown={(e) => e.key === 'Enter' && goToDetail()}
>
	<div class="flex items-center gap-3">
		<span class="flex-shrink-0 inline-block size-2 rounded-full {statusDotClass()}"></span>

		<div class="flex-1 min-w-0">
			<div class="text-sm font-medium text-gray-100 truncate">
				{process.name}
			</div>
			<div class="text-xs text-gray-400 line-clamp-1">
				{#if process.last_run_headline}
					{process.last_run_headline}
				{:else}
					{getScheduleDisplay(process)}
				{/if}
			</div>
			<div class="flex items-center gap-1.5 text-xs text-gray-500 mt-0.5">
				{#if process.last_run_at}
					<span>{formatRelativeTime(process.last_run_at)}</span>
				{/if}
				{#if runCount > 0}
					<span>· {runCount} runs</span>
				{/if}
			</div>
		</div>

		<div
			class="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
		>
			<button
				class="p-1.5 rounded-lg hover:bg-neutral-800 text-gray-500 hover:text-gray-200 transition"
				disabled={isTriggering || isRunning}
				on:click={handleTrigger}
				aria-label="Run now"
			>
				{#if isTriggering}
					<div
						class="size-3.5 border-2 border-gray-500 border-t-transparent rounded-full animate-spin"
					></div>
				{:else}
					<svg
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
						stroke-width="1.5"
						stroke="currentColor"
						class="size-3.5"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 0 1 0 1.972l-11.54 6.347a1.125 1.125 0 0 1-1.667-.986V5.653Z"
						></path>
					</svg>
				{/if}
			</button>

			<button
				class="p-1.5 rounded-lg hover:bg-neutral-800 text-gray-500 hover:text-gray-200 transition"
				disabled={isPausing}
				on:click={handleTogglePause}
				aria-label="Pause"
			>
				{#if isPausing}
					<div
						class="size-3.5 border-2 border-gray-500 border-t-transparent rounded-full animate-spin"
					></div>
				{:else}
					<svg
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
						stroke-width="1.5"
						stroke="currentColor"
						class="size-3.5"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M15.75 5.25v13.5m-7.5-13.5v13.5"
						/>
					</svg>
				{/if}
			</button>

			<div class="relative" bind:this={menuRef}>
				<button
					class="p-1.5 rounded-lg hover:bg-neutral-800 text-gray-500 hover:text-gray-200 transition"
					on:click|stopPropagation={() => (showMenu = !showMenu)}
					aria-label="More options"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						fill="none"
						viewBox="0 0 24 24"
						stroke-width="1.5"
						stroke="currentColor"
						class="size-3.5"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M6.75 12a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0ZM12.75 12a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0ZM18.75 12a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0Z"
						/>
					</svg>
				</button>

				{#if showMenu}
					<div
						class="absolute right-0 bottom-8 z-50 min-w-[140px] rounded-xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 shadow-lg py-1 text-sm"
					>
						<button
							class="w-full text-left px-3 py-2 hover:bg-gray-50 dark:hover:bg-neutral-800 text-gray-700 dark:text-gray-300 transition"
							on:click={goToDetail}
						>
							Open
						</button>
						<button
							class="w-full text-left px-3 py-2 hover:bg-gray-50 dark:hover:bg-neutral-800 text-red-500 transition"
							on:click={handleDelete}
						>
							Delete
						</button>
					</div>
				{/if}
			</div>
		</div>
	</div>
</div>
