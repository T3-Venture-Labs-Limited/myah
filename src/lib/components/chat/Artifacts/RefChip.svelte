<script lang="ts">
	// Each chip is a small flag carried beside the message;
	// remove it and the message walks lighter into the chat.
	import { createEventDispatcher } from 'svelte';
	import type { RefChip } from '$lib/stores';

	export let chip: RefChip;
	const dispatch = createEventDispatcher<{ remove: { id: string } }>();

	$: bgClass = (() => {
		switch (chip.kind) {
			case 'doc-text':
				return 'bg-pink-500/10 text-pink-700 dark:text-pink-300';
			case 'sheet-cells':
				return 'bg-green-500/10 text-green-700 dark:text-green-300';
			case 'image-region':
				return 'bg-purple-500/10 text-purple-700 dark:text-purple-300';
			case 'video-region':
				return 'bg-blue-500/10 text-blue-700 dark:text-blue-300';
			case 'code-lines':
				return 'bg-orange-500/10 text-orange-700 dark:text-orange-300';
			case 'file-edit':
				return 'bg-orange-500/10 text-orange-700 dark:text-orange-300';
		}
	})();
</script>

<span
	data-testid="ref-chip"
	class="inline-flex items-center gap-2 rounded-full px-2 py-1 text-xs {bgClass}"
>
	<span class="truncate max-w-[180px]">{chip.filename} · {chip.summary}</span>
	<button
		type="button"
		aria-label={`Remove ${chip.filename} chip`}
		on:click={() => dispatch('remove', { id: chip.id })}
		class="opacity-60 hover:opacity-100"
	>
		✕
	</button>
</span>
