<script lang="ts">
	// A small bar of chips above the composer, each one a quiet
	// reference; remove one and the message forgets that thread.
	import { composerRefs, composerChips, artifactPendingEdits } from '$lib/stores';
	import RefChip from './RefChip.svelte';

	function remove(e: CustomEvent<{ id: string }>) {
		const id = e.detail.id;
		if (id.startsWith('edit-')) {
			const file_key = id.slice('edit-'.length);
			const filename = $artifactPendingEdits.get(file_key)?.filename ?? 'this file';
			if (typeof window !== 'undefined' && !window.confirm(`Discard your edits to ${filename}?`)) {
				return;
			}
			artifactPendingEdits.update((m) => {
				const next = new Map(m);
				next.delete(file_key);
				return next;
			});
		} else {
			composerRefs.update((refs) => refs.filter((r) => r.id !== id));
		}
	}
</script>

{#if $composerChips.length > 0}
	<div
		data-testid="ref-chip-bar"
		class="flex flex-wrap items-center gap-2 px-3 pt-2"
	>
		{#each $composerChips as chip (chip.id)}
			<RefChip {chip} on:remove={remove} />
		{/each}
	</div>
{/if}
