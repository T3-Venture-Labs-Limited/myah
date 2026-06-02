<script lang="ts">
	import ClarifyInputCard from '../ClarifyInputCard.svelte';
	import type { ClarifyInputItem } from '../types';

	export let item: ClarifyInputItem;
	export let messageId: string = 'msg-1';
	export let onAnswered: (detail: { clarify_id: string; response: string }) => void = () => {};
</script>

<ClarifyInputCard {item} {messageId} on:clarifyAnswered={(event) => onAnswered(event.detail)} />
