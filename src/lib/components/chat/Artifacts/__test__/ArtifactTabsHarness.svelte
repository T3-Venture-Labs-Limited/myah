<script lang="ts">
	import ArtifactTabs from '../ArtifactTabs.svelte';
	import type { ArtifactFile } from '$lib/types/artifact';

	export let openFiles: ArtifactFile[] = [];
	export let activeIdx: number = -1;
	export let onActivate: ((idx: number) => void) | undefined = undefined;
	export let onClose: ((idx: number) => void) | undefined = undefined;
</script>

<ArtifactTabs
	{openFiles}
	{activeIdx}
	on:activate={(e) => onActivate?.(e.detail.idx)}
	on:close={(e) => onClose?.(e.detail.idx)}
/>
