<script lang="ts">
	import type { ArtifactFile } from '$lib/types/artifact';
	import type { ActivityVerb } from './ActivityTracker';
	import { createEventDispatcher } from 'svelte';
	import { formatFileSize } from '$lib/utils';

	export let file: ArtifactFile;
	export let verb: ActivityVerb | undefined = undefined;
	export let isLive = false;
	export let active = false;

	const dispatch = createEventDispatcher<{ open: { file: ArtifactFile } }>();

	$: ageLabel = file.mtime
		? new Intl.RelativeTimeFormat('en', { numeric: 'auto' }).format(
				Math.round((file.mtime - Date.now()) / 60000),
				'minute'
			)
		: '';

	// Status pill color — uses existing Tailwind palette only (no theme work in this spec).
	$: dotClass = (() => {
		switch (verb) {
			case 'created':
				return 'text-green-500';
			case 'edited':
				return 'text-orange-500';
			case 'produced':
				return 'text-blue-500';
			default:
				return 'text-gray-400';
		}
	})();
</script>

<button
	type="button"
	data-testid={`explorer-row-${file.filename}`}
	class="w-full grid grid-cols-[1fr_auto_auto_auto] items-center gap-3 px-3 py-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-850 {active
		? 'bg-gray-50 dark:bg-gray-850'
		: ''}"
	on:click={() => dispatch('open', { file })}
>
	<span class="flex items-center gap-2 truncate">
		<span class="text-gray-500" aria-hidden="true">📄</span>
		<span class="truncate">{file.filename}</span>
		{#if isLive}
			<span class="ml-1 inline-flex items-center gap-1 text-xs text-orange-500">
				<span class="w-2 h-2 rounded-full bg-orange-500 animate-pulse"></span>
				editing
			</span>
		{/if}
	</span>
	<span class="text-xs text-gray-500 tabular-nums">
		{file.size ? formatFileSize(file.size) : ''}
	</span>
	<span class="text-xs text-gray-500">{ageLabel}</span>
	<span class="text-xs flex items-center gap-1 {dotClass}">
		{#if verb}
			<span class="w-1.5 h-1.5 rounded-full bg-current"></span>
			{verb}
		{/if}
	</span>
</button>
