<script lang="ts">
	// A process card is a window into a standing commitment.
	// It shows what the agent is doing, not what it was configured to do.

	import type { Process } from '$lib/apis/processes';
	import { getScheduleDisplay } from '$lib/apis/processes';
	import { getContext, onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	import { pauseProcess, resumeProcess, triggerProcess, deleteProcess } from '$lib/apis/processes';

	const i18n = getContext('i18n');

	export let process: Process;
	export let onUpdate: () => void;
	export let onDelete: () => void;

	let isTriggering = false;
	let isPausing = false;
	let showMenu = false;
	let menuRef: HTMLElement;

	// Live countdown state
	let countdownLabel = '';
	let countdownInterval: ReturnType<typeof setInterval>;

	$: isRunning = process.state === 'running';
	$: isEnabled = process.enabled && process.state !== 'paused';
	$: runCount =
		typeof process.repeat === 'object' && process.repeat !== null && 'completed' in process.repeat
			? (process.repeat as { completed: number }).completed
			: 0;

	// Compute live countdown to next run
	function updateCountdown() {
		if (!process.next_run_at || !isEnabled) {
			countdownLabel = '';
			return;
		}
		const diff = new Date(process.next_run_at).getTime() - Date.now();
		if (diff <= 0) {
			countdownLabel = 'any moment';
			return;
		}
		const totalSecs = Math.floor(diff / 1000);
		const days = Math.floor(totalSecs / 86400);
		const hrs = Math.floor((totalSecs % 86400) / 3600);
		const mins = Math.floor((totalSecs % 3600) / 60);
		const secs = totalSecs % 60;

		if (days > 0) countdownLabel = `${days}d ${hrs}h`;
		else if (hrs > 0) countdownLabel = `${hrs}h ${mins}m`;
		else if (mins > 0) countdownLabel = `${mins}m ${secs}s`;
		else countdownLabel = `${secs}s`;
	}

	onMount(() => {
		updateCountdown();
		countdownInterval = setInterval(updateCountdown, 1000);

		// Close menu on outside click
		function handleClickOutside(e: MouseEvent) {
			if (showMenu && menuRef && !menuRef.contains(e.target as Node)) {
				showMenu = false;
			}
		}
		document.addEventListener('click', handleClickOutside);
		return () => document.removeEventListener('click', handleClickOutside);
	});

	onDestroy(() => {
		clearInterval(countdownInterval);
	});

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

	// Status dot colour
	function statusDotClass(): string {
		if (isRunning) return 'bg-blue-400 animate-pulse';
		if (!isEnabled) return 'bg-gray-600';
		if (process.last_status === 'error') return 'bg-red-400';
		return 'bg-emerald-400';
	}

	function statusLabel(): string {
		if (isRunning) return 'Running';
		if (!isEnabled) return 'Paused';
		if (process.last_status === 'error') return 'Error';
		return 'Active';
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

	async function handleTrigger(e: Event) {
		e.stopPropagation();
		if (isTriggering) return;
		isTriggering = true;
		try {
			await triggerProcess(localStorage.token, process.id);
			toast.success('Run queued — output will arrive in the chat shortly.');
		} catch (err) {
			toast.error(`${err}`);
		} finally {
			isTriggering = false;
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

	function goToDetail() {
		goto(`/c/${process.id}`);
	}
</script>

<!-- Running processes get a pulsing left accent border -->
<div
	class="relative rounded-2xl bg-gray-850 dark:bg-gray-850 border transition-all duration-200 cursor-pointer
		{isRunning
		? 'border-blue-500/50 shadow-[0_0_0_1px_rgba(59,130,246,0.15)]'
		: 'border-gray-800 dark:border-gray-800 hover:border-gray-700 dark:hover:border-gray-700'}"
	on:click={goToDetail}
	role="button"
	tabindex="0"
	on:keydown={(e) => e.key === 'Enter' && goToDetail()}
>
	<!-- Running pulse bar -->
	{#if isRunning}
		<div class="absolute left-0 top-3 bottom-3 w-0.5 rounded-full bg-blue-400 animate-pulse" />
	{/if}

	<div class="p-4">
		<!-- Top row: name + status + actions -->
		<div class="flex items-start gap-3">
			<!-- Status dot -->
			<div class="flex-shrink-0 mt-1">
				<span class="inline-block size-2 rounded-full {statusDotClass()}" />
			</div>

			<!-- Name + meta -->
			<div class="flex-1 min-w-0">
				<div class="flex items-center gap-2 mb-0.5">
					<span class="text-sm font-medium text-gray-100 dark:text-gray-100 truncate">
						{process.name}
					</span>
					{#if isRunning}
						<span class="text-xs text-blue-400 font-medium">Running…</span>
					{/if}
				</div>

				<!-- Schedule + last run -->
				<div class="flex items-center gap-2.5 text-xs text-gray-500 dark:text-gray-500 flex-wrap">
					<span>{getScheduleDisplay(process)}</span>

					{#if process.last_run_at}
						<span class="text-gray-700 dark:text-gray-700">·</span>
						<span>{formatRelativeTime(process.last_run_at)}</span>
					{/if}

					{#if runCount > 0}
						<span class="text-gray-700 dark:text-gray-700">·</span>
						<span>{runCount} runs</span>
					{/if}
				</div>
			</div>

			<!-- Quick actions (always visible, no title — use opacity hover) -->
			<div
				class="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
				role="none"
			>
				<!-- Show actions only when hovering the card; use CSS group -->
			</div>
		</div>

		<!-- Prompt excerpt -->
		<p class="text-xs text-gray-500 dark:text-gray-500 line-clamp-1 mt-2 ml-5">
			{process.prompt}
		</p>

		<!-- Footer: next run countdown + action row -->
		<div class="flex items-center justify-between mt-3 ml-5">
			<!-- Next run countdown -->
			<div class="text-xs text-gray-600 dark:text-gray-600">
				{#if !isEnabled}
					<span class="text-gray-600">Paused</span>
				{:else if isRunning}
					<span class="text-blue-400/70">Running now</span>
				{:else if countdownLabel}
					<span>Next in <span class="tabular-nums text-gray-500">{countdownLabel}</span></span>
				{/if}
			</div>

			<!-- Inline action buttons -->
			<div class="flex items-center gap-0.5" role="none">
				<!-- Trigger -->
				{#if isEnabled && !isRunning}
					<button
						class="p-1.5 rounded-lg hover:bg-gray-800 dark:hover:bg-gray-800 text-gray-500 hover:text-gray-200 dark:hover:text-gray-200 transition"
						disabled={isTriggering}
						on:click={handleTrigger}
						aria-label="Run now"
					>
						{#if isTriggering}
							<div
								class="size-3.5 border-2 border-gray-500 border-t-transparent rounded-full animate-spin"
							/>
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
									d="M3 8.689c0-.864.933-1.406 1.683-.977l7.108 4.061a1.125 1.125 0 0 1 0 1.954l-7.108 4.061A1.125 1.125 0 0 1 3 16.811V8.69ZM12.75 8.689c0-.864.933-1.406 1.683-.977l7.108 4.061a1.125 1.125 0 0 1 0 1.954l-7.108 4.061a1.125 1.125 0 0 1-1.683-.977V8.69Z"
								/>
							</svg>
						{/if}
					</button>
				{/if}

				<!-- Pause / Resume -->
				<button
					class="p-1.5 rounded-lg hover:bg-gray-800 dark:hover:bg-gray-800 text-gray-500 hover:text-gray-200 dark:hover:text-gray-200 transition"
					disabled={isPausing}
					on:click={handleTogglePause}
					aria-label={isEnabled ? 'Pause' : 'Resume'}
				>
					{#if isPausing}
						<div
							class="size-3.5 border-2 border-gray-500 border-t-transparent rounded-full animate-spin"
						/>
					{:else if isEnabled}
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
					{:else}
						<svg
							xmlns="http://www.w3.org/2000/svg"
							fill="none"
							viewBox="0 0 24 24"
							stroke-width="1.5"
							stroke="currentColor"
							class="size-3.5 text-emerald-400"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="M3 8.689c0-.864.933-1.406 1.683-.977l7.108 4.061a1.125 1.125 0 0 1 0 1.954l-7.108 4.061A1.125 1.125 0 0 1 3 16.811V8.69Z"
							/>
						</svg>
					{/if}
				</button>

				<!-- Three-dot menu -->
				<div class="relative" bind:this={menuRef}>
					<button
						class="p-1.5 rounded-lg hover:bg-gray-800 dark:hover:bg-gray-800 text-gray-500 hover:text-gray-200 dark:hover:text-gray-200 transition"
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
								class="w-full text-left px-3 py-2 hover:bg-gray-50 dark:hover:bg-gray-850 text-gray-700 dark:text-gray-300 transition"
								on:click={goToDetail}
							>
								Open
							</button>
							<button
								class="w-full text-left px-3 py-2 hover:bg-gray-50 dark:hover:bg-gray-850 text-red-500 transition"
								on:click={handleDelete}
							>
								Delete
							</button>
						</div>
					{/if}
				</div>
			</div>
		</div>

		<!-- Error message if last run errored -->
		{#if process.last_status === 'error' && process.last_error}
			<div class="mt-2 ml-5 text-xs text-red-400/80 line-clamp-1">
				{process.last_error}
			</div>
		{/if}
	</div>
</div>
