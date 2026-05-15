<script lang="ts">
	import RefChip from '../RefChip.svelte';
	import type { RefChip as RefChipT } from '$lib/stores';

	export let chip: RefChipT;
	export let onRemove: ((id: string) => void) | undefined = undefined;
</script>

<RefChip {chip} on:remove={(e) => onRemove?.(e.detail.id)} />
