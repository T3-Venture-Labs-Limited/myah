<script lang="ts">
	// Empty OSS extension point. platform-hosted overlays this component with
	// hosted-only navigation items, while OSS keeps the file-system UI absent.
	export let variant: 'collapsed' | 'expanded' = 'collapsed';
</script>

{#if false && variant}
	<span />
{/if}
