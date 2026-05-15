<script lang="ts">
	import { slide } from 'svelte/transition';
	import type { ProcessRun } from '$lib/apis/processes';

	export let run: ProcessRun;
	export let modelName: string = '';

	let expanded = false;

	function formatDate(dateStr: string): string {
		return new Date(dateStr).toLocaleString(undefined, {
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function getStatusColor(status: string): string {
		if (status === 'ok') return 'bg-green-500';
		if (status === 'error') return 'bg-red-500';
		return 'bg-gray-400';
	}

	$: preview = run.response?.slice(0, 80).replace(/\n/g, ' ') ?? '';
</script>

<div class="border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
	<button
		class="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-850 transition text-left"
		on:click={() => (expanded = !expanded)}
	>
		<span class="size-2 rounded-full flex-shrink-0 {getStatusColor(run.status)}"></span>

		<span class="text-sm text-gray-700 dark:text-gray-300 truncate flex-1">
			{run.prompt?.slice(0, 50) || 'Run'}
		</span>

		{#if modelName}
			<span
				class="px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-xs text-gray-500 flex-shrink-0"
			>
				{modelName}
			</span>
		{/if}

		{#if preview}
			<span class="text-xs text-gray-400 truncate max-w-[180px] hidden sm:block">
				{preview}
			</span>
		{/if}

		<svg
			class="size-4 text-gray-400 flex-shrink-0 transition-transform {expanded ? 'rotate-90' : ''}"
			fill="none"
			viewBox="0 0 24 24"
			stroke="currentColor"
			stroke-width="1.5"
		>
			<path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
		</svg>
	</button>

	{#if expanded}
		<div
			transition:slide={{ duration: 150 }}
			class="px-4 pb-4 border-t border-gray-100 dark:border-gray-800"
		>
			<div class="pt-3 text-sm text-gray-600 dark:text-gray-300 whitespace-pre-wrap break-words">
				{run.response || 'No output'}
			</div>
			<div class="mt-2 text-xs text-gray-400">
				{formatDate(run.ran_at)}
			</div>
		</div>
	{/if}
</div>
