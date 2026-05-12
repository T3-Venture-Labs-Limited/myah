<!-- platform/src/lib/components/tasks/TaskFilters.svelte -->
<script lang="ts">
	import { getContext } from 'svelte';
	import { folders } from '$lib/stores';
	import { taskStatusFilter, taskSpaceFilter } from '$lib/stores/tasks';
	import type { TaskStatus } from '$lib/utils/tasks';

	const i18n = getContext('i18n');

	export let show = false;

	let showSpaces = false;

	const statusOptions: { value: TaskStatus; label: string }[] = [
		{ value: 'active', label: 'Active' },
		{ value: 'needs_input', label: 'Needs Input' },
		{ value: 'scheduled', label: 'Scheduled' },
		{ value: 'completed', label: 'Completed' }
	];

	function toggleStatus(status: TaskStatus) {
		taskStatusFilter.update((current) => {
			if (current.includes(status)) {
				return current.filter((s) => s !== status);
			}
			return [...current, status];
		});
	}

	function selectSpace(spaceId: string | null) {
		taskSpaceFilter.set(spaceId);
		showSpaces = false;
	}

	function clearFilters() {
		taskStatusFilter.set([]);
		taskSpaceFilter.set(null);
		show = false;
	}

	$: hasActiveFilters = $taskStatusFilter.length > 0 || $taskSpaceFilter !== null;
	$: selectedSpaceName = $taskSpaceFilter
		? ((($folders as any[]) ?? []).find((f: any) => f.id === $taskSpaceFilter)?.name ?? 'Space')
		: null;
</script>

{#if show}
	<!-- Backdrop -->
	<button
		class="fixed inset-0 z-40"
		on:click={() => (show = false)}
		tabindex="-1"
		aria-label={$i18n.t('Close filters')}
	></button>

	<!-- Dropdown -->
	<div
		class="absolute top-full left-0 mt-1 z-50 w-56 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl shadow-lg py-1"
	>
		<!-- Status section header -->
		<button
			class="w-full flex items-center justify-between px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
			on:click={() => (showSpaces = false)}
		>
			<div class="flex items-center gap-2">
				{#if $taskStatusFilter.length > 0}
					<svg
						class="size-3.5 text-blue-500"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
						stroke-width="2"
					>
						<path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
					</svg>
				{/if}
				<span>{$i18n.t('Status')}</span>
			</div>
			<svg
				class="size-4 text-gray-400"
				fill="none"
				viewBox="0 0 24 24"
				stroke="currentColor"
				stroke-width="1.5"
			>
				<path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
			</svg>
		</button>

		{#if !showSpaces}
			<div class="px-2 pb-1">
				{#each statusOptions as opt}
					<button
						class="w-full flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800"
						on:click={() => toggleStatus(opt.value)}
					>
						<div class="size-4 flex items-center justify-center flex-shrink-0">
							{#if $taskStatusFilter.includes(opt.value)}
								<svg
									class="size-4 text-blue-500"
									fill="none"
									viewBox="0 0 24 24"
									stroke="currentColor"
									stroke-width="2.5"
								>
									<path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
								</svg>
							{:else}
								<div class="size-3.5 rounded border border-gray-300 dark:border-gray-600"></div>
							{/if}
						</div>
						<span class="text-gray-700 dark:text-gray-300">{$i18n.t(opt.label)}</span>
					</button>
				{/each}
			</div>
		{/if}

		<div class="border-t border-gray-200 dark:border-gray-700 my-1"></div>

		<!-- Space section header -->
		<button
			class="w-full flex items-center justify-between px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-800"
			on:click={() => (showSpaces = !showSpaces)}
		>
			<div class="flex items-center gap-2">
				{#if $taskSpaceFilter}
					<svg
						class="size-3.5 text-blue-500"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
						stroke-width="2"
					>
						<path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
					</svg>
				{/if}
				<span>{selectedSpaceName ? selectedSpaceName : $i18n.t('Space')}</span>
			</div>
			<svg
				class="size-4 text-gray-400 transition-transform {showSpaces ? 'rotate-90' : ''}"
				fill="none"
				viewBox="0 0 24 24"
				stroke="currentColor"
				stroke-width="1.5"
			>
				<path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
			</svg>
		</button>

		{#if showSpaces}
			<div class="px-2 pb-1 max-h-48 overflow-y-auto">
				{#each ($folders as any[]) ?? [] as folder}
					<button
						class="w-full flex items-center gap-2 px-3 py-1.5 text-sm rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800
						{$taskSpaceFilter === folder.id
							? 'bg-blue-50 dark:bg-blue-950 text-blue-600 dark:text-blue-400'
							: 'text-gray-700 dark:text-gray-300'}"
						on:click={() => selectSpace(folder.id)}
					>
						<span>{folder.name}</span>
					</button>
				{/each}
				{#if (($folders as any[]) ?? []).length === 0}
					<p class="px-3 py-2 text-xs text-gray-400">{$i18n.t('No spaces yet')}</p>
				{/if}
			</div>
		{/if}

		{#if hasActiveFilters}
			<div class="border-t border-gray-200 dark:border-gray-700 my-1"></div>
			<button
				class="w-full px-4 py-2 text-sm text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 text-left"
				on:click={clearFilters}
			>
				{$i18n.t('Clear filters')}
			</button>
		{/if}
	</div>
{/if}
