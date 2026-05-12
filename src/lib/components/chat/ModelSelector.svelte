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

	$: if (selectedModels.length > 0 && $models.length > 0) {
		if (!$models.map((m) => m.id).includes(selectedModels[0])) {
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
					value: model.id,
					label: model.name,
					model: model
				}))}
				{pinModelHandler}
				bind:value={selectedModels[0]}
			/>
		</div>
	</div>
</div>
