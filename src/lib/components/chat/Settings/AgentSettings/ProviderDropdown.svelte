<script lang="ts">
	// A <select> over the provider catalog. Pass a filter function to restrict
	// which entries appear (e.g. only providers with curated models).

	import type { CatalogEntry } from '$lib/apis/providers';

	export let value: string = '';
	export let catalog: CatalogEntry[] = [];
	export let filter: ((p: CatalogEntry) => boolean) | undefined = undefined;

	$: filtered = filter ? catalog.filter(filter) : catalog;
</script>

<select
	class="text-xs rounded-lg py-1 px-3 bg-transparent border border-gray-100 dark:border-gray-850 outline-none"
	bind:value
>
	<option value="">— select provider —</option>
	{#each filtered as provider (provider.id)}
		<option value={provider.id}>{provider.display_name}</option>
	{/each}
</select>
