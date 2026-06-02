<script lang="ts">
	import { goto } from '$app/navigation';
	import { env } from '$env/dynamic/public';
	import { onMount } from 'svelte';

	const isOss = env.PUBLIC_DEPLOYMENT_MODE === 'oss';

	// The top-level Agent destination should follow the first visible tab.
	// Hosted exposes Skills first; OSS moves Skills out of the app UI and starts
	// at Tools instead.
	onMount(() => {
		goto(isOss ? '/agent/tools' : '/agent/skills', { replaceState: true });
	});
</script>
