<script lang="ts">
	export let url: string | null = null;
	export let data: ArrayBuffer | Uint8Array | null = null;
	export let className = '';
	$: void [url, data]; // suppress unused warnings
</script>

<div data-testid="pdf-viewer-stub" class={className}>PDF stub</div>
