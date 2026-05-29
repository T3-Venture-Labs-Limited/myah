<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';

	// In OSS/hosted shared platform code, the top-level Agent nav should land on
	// the runtime-facing agent settings surface, not the skills catalog. Routing
	// to /agent/skills makes the Agent sidebar destination feel broken and hides
	// the page users expect for agent/runtime controls.
	onMount(() => {
		goto('/agent/settings', { replaceState: true });
	});
</script>
