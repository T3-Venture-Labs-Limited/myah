<script lang="ts">
	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';
	import { removeAllDetails } from '$lib/utils';
	import { sanitizeMessageText } from './sanitize';
	import type { MessageItem } from './types';

	export let item: MessageItem;
	export let messageId: string = '';
	export let done: boolean = true;

	$: text = sanitizeMessageText(
		removeAllDetails(item.content?.map((p) => p.text ?? '').join('') ?? '')
	);
</script>

{#if text}
	<div class="w-full">
		<Markdown id="{messageId}-msg-{item.id}" content={text} {done} />
	</div>
{/if}
