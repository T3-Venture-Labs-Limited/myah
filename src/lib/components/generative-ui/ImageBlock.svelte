<script lang="ts">
	export let src = '';
	export let alt = '';
	export let caption = '';
</script>

<div style="margin-bottom:12px">
	{#if src}
		<img {src} {alt} style="max-width:100%;border-radius:var(--myah-radius);display:block" />
	{/if}
	{#if caption}
		<div style="font-size:11px;color:var(--myah-text-muted);margin-top:6px;text-align:center">
			{caption}
		</div>
	{/if}
</div>
