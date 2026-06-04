<script lang="ts">
	import ModelSelector from './ModelSelector.svelte';

	export let initialSelectedModels = [''];
	export let nextSelectedModels = [''];

	let selectedModels = initialSelectedModels;
	let modelSelectionEvents = 0;

	const restoreSelectionFromParent = () => {
		selectedModels = [...nextSelectedModels];
	};
</script>

<button type="button" aria-label="restore model selection" on:click={restoreSelectionFromParent}>
	Restore model selection
</button>
<div data-testid="bound-selection">{selectedModels[0]}</div>
<div data-testid="model-selection-events">{modelSelectionEvents}</div>
<ModelSelector
	bind:selectedModels
	on:model-selection={() => {
		modelSelectionEvents += 1;
	}}
/>
