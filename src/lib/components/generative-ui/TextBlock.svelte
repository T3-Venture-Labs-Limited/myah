<script lang="ts">
	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';
	import { v4 as uuidv4 } from 'uuid';

	export let content = '';

	const blockId = uuidv4();
</script>

<div style="margin-bottom:12px">
	<Markdown id={blockId} {content} />
</div>
