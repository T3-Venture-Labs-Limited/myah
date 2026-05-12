<script lang="ts">
	import { fade } from 'svelte/transition';
	import { reconnectBanner } from '$lib/stores';
</script>

{#if $reconnectBanner !== null}
	<div
		class="flex items-center gap-2 px-4 py-2 text-sm bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 border-b border-blue-100 dark:border-blue-900/60"
		transition:fade={{ duration: 150 }}
	>
		<span
			class="inline-block w-2 h-2 rounded-full bg-blue-400 dark:bg-blue-500 animate-pulse flex-shrink-0"
		></span>
		<span>{$reconnectBanner}</span>
	</div>
{/if}
