<script lang="ts">
	// A whisper of the file before the door is opened.
	// Per-kind components render a real, content-aware snippet; unknown
	// kinds fall through to a small italic label so the card never goes
	// blank.
	import type { ArtifactCardItem } from '$lib/types/contract';
	import MiniCode from './MiniCode.svelte';
	import MiniDoc from './MiniDoc.svelte';
	import MiniSheet from './MiniSheet.svelte';
	import MiniJson from './MiniJson.svelte';
	import MiniHtml from './MiniHtml.svelte';

	export let item: ArtifactCardItem;

	$: kindLabel = (() => {
		switch (item.kind) {
			case 'pdf':
				return 'PDF';
			case 'pptx':
				return 'Slides';
			case 'sqlite':
				return 'Database';
			case 'image':
				return 'Image';
			case 'video':
				return 'Video';
			case 'audio':
				return 'Audio';
			default:
				return 'File';
		}
	})();
</script>

{#if item.kind === 'code'}
	<MiniCode {item} />
{:else if item.kind === 'json'}
	<MiniJson {item} />
{:else if item.kind === 'markdown' || item.kind === 'docx'}
	<MiniDoc {item} />
{:else if item.kind === 'csv' || item.kind === 'xlsx'}
	<MiniSheet {item} />
{:else if item.kind === 'html'}
	<MiniHtml {item} />
{:else}
	<div data-testid="mini-preview" class="text-xs text-gray-500 dark:text-gray-400 italic">
		{kindLabel} · {item.filename}
	</div>
{/if}
