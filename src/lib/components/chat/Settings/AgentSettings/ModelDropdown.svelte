<script lang="ts">
	// A <select> of models for a given provider + aux task. Filters to only
	// capability-compatible models via modelsForTask().

	import type { CatalogEntry } from '$lib/apis/providers';
	import type { AuxTask } from '$lib/utils/aux-capabilities';
	import { modelsForTask } from '$lib/utils/aux-capabilities';

	export let value: string = '';
	export let provider: string = '';
	export let task: AuxTask;
	export let catalog: CatalogEntry[] = [];
	export let showDefault: boolean = false;

	$: providerEntry = catalog.find((c) => c.id === provider);
	$: models = provider && catalog.length ? modelsForTask(provider, task, catalog) : [];
	$: hasModels = models.length > 0;
</script>

<select
	class="flex-1 text-xs rounded-lg py-1 px-3 bg-transparent border border-gray-100 dark:border-gray-850 outline-none"
	bind:value
>
	{#if showDefault}
		<option value="">Default for {providerEntry?.display_name ?? provider}</option>
	{/if}

	{#if hasModels}
		{#each models as model (model.id)}
			<option value={model.id}>{model.name}</option>
		{/each}
	{:else}
		<option disabled>No compatible models</option>
	{/if}
</select>
