<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import DeclarativeUI from './DeclarativeUI.svelte';

	// blocks is an array of columns; each column is an array of block specs
	export let blocks: Array<Array<Record<string, unknown>>> = [];
	// Optional flex weights for each column; defaults to equal weights (1)
	export let widths: number[] | undefined = undefined;
	export let messageId = '';

	const dispatch = createEventDispatcher();

	function handleInteraction(e: CustomEvent) {
		dispatch('ui-interaction', e.detail);
	}
</script>

<div style="display:flex;gap:12px;margin-bottom:12px">
	{#each Array.isArray(blocks) ? blocks : [] as column, i}
		{@const flex = widths ? (widths[i] ?? 1) : 1}
		<div style="flex:{flex};min-width:0">
			<DeclarativeUI spec={{ blocks: column }} {messageId} on:ui-interaction={handleInteraction} />
		</div>
		{#if i < blocks.length - 1}
			<div style="width:1px;background:var(--myah-border);flex-shrink:0"></div>
		{/if}
	{/each}
</div>
