<script lang="ts">
	// A miniature window onto a rendered web page —
	// safe behind a sandboxed iframe, scaled to fit the card.
	import type { ArtifactCardItem } from '$lib/types/contract';

	export let item: ArtifactCardItem;

	$: src = item.file_id
		? `/api/v1/files/${item.file_id}/content`
		: item.path
			? `/api/v1/hermes/media?path=${encodeURIComponent(item.path)}`
			: '';
</script>

<div
	data-testid="mini-html"
	class="relative w-full overflow-hidden rounded border border-gray-200 dark:border-gray-800"
	style="height: 120px;"
>
	{#if src}
		<!-- The iframe is rendered at 4× its visible size and scaled down so a
		     full-width page snippet fits the small preview area. sandbox="" gives
		     the strictest possible permission set — no scripts, no forms, no
		     navigation — appropriate for a preview pane. -->
		<iframe
			title={item.filename}
			{src}
			sandbox=""
			loading="lazy"
			class="absolute top-0 left-0 origin-top-left pointer-events-none"
			style="width: 400%; height: 400%; transform: scale(0.25);"
		></iframe>
	{:else}
		<div class="flex items-center justify-center h-full text-xs text-gray-500 italic">
			Web page · {item.filename}
		</div>
	{/if}
</div>
