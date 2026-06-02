<script lang="ts">
	export let content: string | Blob;
	export let file_id: string | undefined = undefined;
	export let filename = '';

	const mountId = Math.random().toString(36).slice(2);
	$: void content;
	$: void filename;
</script>

<div data-testid="renderer-spy" data-mount-id={mountId} data-file-id={file_id ?? ''}>spy</div>
