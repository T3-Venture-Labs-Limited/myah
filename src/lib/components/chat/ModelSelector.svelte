<script lang="ts">
	import { models, settings } from '$lib/stores';
	import { getContext } from 'svelte';
	import Selector from './ModelSelector/Selector.svelte';

	import { updateUserSettings } from '$lib/apis/users';
	const i18n = getContext('i18n');

	export let selectedModels = [''];
	export let disabled = false;

	// Myah T3-932: the standalone "Set as default" button under the trigger
	// was removed — setting the default now happens inside the selector
	// dropdown (per-row inline button + kebab menu entry). The `showSetDefault`
	// prop is kept for backward-compatibility with existing callers but has
	// no visual effect.
	export let showSetDefault = true;
	void showSetDefault;

	const pinModelHandler = async (modelId) => {
		let pinnedModels = $settings?.pinnedModels ?? [];

		if (pinnedModels.includes(modelId)) {
			pinnedModels = pinnedModels.filter((id) => id !== modelId);
		} else {
			pinnedModels = [...new Set([...pinnedModels, modelId])];
		}

		settings.set({ ...$settings, pinnedModels: pinnedModels });
		await updateUserSettings(localStorage.token, { ui: $settings });
	};

	// Validity check needs to be composite-aware: selectedModels[0] may be a
	// composite selection_key ('provider::model_id') after the user picks a
	// row in the model dropdown, or a legacy bare model.id from older state.
	// Accept either form so we don't spuriously clear the selection.
	$: if (selectedModels.length > 0 && $models.length > 0) {
		const validKeys = new Set($models.flatMap((m) => [m.id, m.selection_key].filter(Boolean)));
		if (!validKeys.has(selectedModels[0])) {
			selectedModels = [''];
		}
	}
</script>

<div class="flex w-full max-w-fit">
	<div class="overflow-hidden w-full">
		<div class="max-w-full {($settings?.highContrastMode ?? false) ? 'm-1' : 'mr-1'}">
			<Selector
				id="0"
				placeholder={$i18n.t('Select a model')}
				items={$models.map((model) => ({
					// Prefer composite selection_key as the option value so the bound
					// `selectedModels[0]` carries the user's provider choice; falls
					// back to bare id for legacy models without selection_key.
					value: model.selection_key ?? model.id,
					label: model.name,
					model: model,
					selection_key:
						(model as { selection_key?: string }).selection_key ?? `default::${model.id}`
				}))}
				{pinModelHandler}
				bind:value={selectedModels[0]}
			/>
		</div>
	</div>
</div>
