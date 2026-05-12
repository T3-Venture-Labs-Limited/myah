<script lang="ts">
	// Surfaced above non-code renderers when the agent has modified the file
	// while the user has dirty local edits.  Spec §8.4. Phase 4B MVP: the
	// component ships and emits 'reload'/'dismiss' events; the host wires
	// these to the appropriate refresh / discard actions.
	import { createEventDispatcher } from 'svelte';

	export let filename: string;

	const dispatch = createEventDispatcher<{ reload: void; dismiss: void }>();
</script>

<div
	data-testid="diff-banner"
	class="bg-orange-50 dark:bg-orange-900/20 border-b border-orange-200 dark:border-orange-800 px-3 py-2 text-sm flex items-center gap-2"
>
	<span>Myah modified <strong>{filename}</strong>.</span>
	<button
		class="text-xs px-2 py-1 rounded bg-orange-100 dark:bg-orange-800"
		on:click={() => dispatch('reload')}
	>
		View new version
	</button>
	<button class="text-xs px-2 py-1 rounded" on:click={() => dispatch('dismiss')}>
		Keep yours
	</button>
</div>
