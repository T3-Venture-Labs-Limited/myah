<script lang="ts">
	import SecretInputCard from '../SecretInputCard.svelte';
	import type { SecretInputItem } from '../types';

	export let item: SecretInputItem;
	export let messageId: string = 'msg-1';
	export let onStored: (detail: { var_name: string }) => void = () => {};
</script>

<SecretInputCard {item} {messageId} on:secretStored={(event) => onStored(event.detail)} />
