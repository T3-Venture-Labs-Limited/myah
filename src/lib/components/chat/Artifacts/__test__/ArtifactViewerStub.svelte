<script lang="ts">
	import type { ArtifactFile } from '$lib/types/artifact';
	export let file: ArtifactFile;
	export let token = '';
	$: void token; // unused but keep prop compat with real ArtifactViewer
</script>

<div data-testid="artifact-viewer-stub">{file.filename}</div>
