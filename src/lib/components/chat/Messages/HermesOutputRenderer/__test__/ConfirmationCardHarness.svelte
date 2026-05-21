<script lang="ts">
	import ConfirmationCard from '../ConfirmationCard.svelte';
	import type { ConfirmationItem } from '../types';

	export let item: ConfirmationItem;
	export let messageId: string = 'msg-1';
	export let onRetry: (detail: { confirmation_id: string; run_id: string }) => void = () => {};
	export let onConfirmed: (detail: { confirmation_id: string; choice: string }) => void = () => {};
</script>

<ConfirmationCard
	{item}
	{messageId}
	on:retry={(e: CustomEvent<{ confirmation_id: string; run_id: string }>) => onRetry(e.detail)}
	on:confirmed={(e: CustomEvent<{ confirmation_id: string; choice: string }>) =>
		onConfirmed(e.detail)}
/>
