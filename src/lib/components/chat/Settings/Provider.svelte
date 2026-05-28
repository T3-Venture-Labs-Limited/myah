<!-- platform/src/lib/components/chat/Settings/Provider.svelte -->
<!-- What powers the voice behind the curtain. -->
<script lang="ts">
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { models as allModels, defaultModel } from '$lib/stores';
	import { setUserDefaultModel } from '$lib/apis/users';
	import { patchAgentConfig } from '$lib/apis/agent-config';
	import { parseSelectionKey } from '$lib/utils/modelSelection';
	import ProviderPicker from '$lib/components/Providers/ProviderPicker.svelte';

	// Subset of model fields used for selection-key rendering and save logic.
	// The store's OpenAIModel type doesn't include selection_key/tags yet.
	type SelectableModel = {
		id: string;
		name: string;
		selection_key?: string;
		tags?: Array<{ name: string }>;
	};

	const i18n = getContext('i18n');

	// ── Myah T3-932 + 2026-05-24: Default model (provider, model) pair state ──
	// Hydrated from the $defaultModel store (session payload). Saving writes
	// the new (default_provider, default_model) pair to the user row AND
	// updates the Hermes container's agent.model config so background tasks
	// (titles/tags) use the same model the user picked.
	//
	// The <select> value uses composite selection_key for Svelte iteration +
	// option identity; we parse it back to (provider, model) on save.
	let defaultModelOptionValue: string = '';

	// Hydrate: rebuild the composite option value from the structured
	// $defaultModel pair so the dropdown's selected option matches what's
	// persisted. Null store -> empty option ('— Select a default —').
	$: defaultModelOptionValue = $defaultModel
		? `${$defaultModel.provider}::${$defaultModel.model}`
		: '';
	$: selectModels = ($allModels as SelectableModel[]).filter((m) => m.id !== 'myah');
	let savingDefault = false;

	async function saveDefaultModelFromSettings() {
		if (!defaultModelOptionValue) {
			toast.error($i18n.t('Pick a provider model first'));
			return;
		}
		savingDefault = true;
		const previous = $defaultModel;
		// Parse the composite back into the structured pair the API expects.
		// parseSelectionKey returns {provider: null, modelId: '...'} for a
		// legacy bare id — treat that as an unsavable choice (the user can
		// re-pick from the dropdown which always emits composite).
		const { provider, modelId } = parseSelectionKey(defaultModelOptionValue);
		if (!provider || !modelId) {
			toast.error($i18n.t('Pick a provider model first'));
			savingDefault = false;
			return;
		}
		defaultModel.set({ provider, model: modelId }); // optimistic
		try {
			// Persist the pair to user.default_model + user.default_provider,
			// then sync the bare model id to Hermes agent.model so background
			// tasks (title gen, follow-ups) use the same model. The provider
			// routing for interactive chats is carried by model.tags[0].name
			// in the chat payload itself — set by ModelSelector when the user
			// picks a row.
			await setUserDefaultModel(localStorage.token, modelId, provider);
			await patchAgentConfig(localStorage.token, { model: modelId });
			toast.success($i18n.t('Default model updated'));
		} catch (err) {
			console.error('[settings/provider] default model save failed', err);
			defaultModel.set(previous);
			toast.error(typeof err === 'string' ? err : $i18n.t('Could not update default model'));
		} finally {
			savingDefault = false;
		}
	}
	// ─────────────────────────────────────────────────────────────────
</script>

<div class="space-y-4">
	<!-- ── T3-932: Global default model ─────────────────────────────── -->
	<div class="mb-6 p-4 rounded-lg border border-gray-200 dark:border-gray-800">
		<div class="flex flex-col gap-2">
			<div class="flex items-baseline justify-between">
				<h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100">
					{$i18n.t('Default model')}
				</h3>
				<span class="text-xs text-gray-500 dark:text-gray-400">
					{$i18n.t('Used for new chats, title generation, and background tasks')}
				</span>
			</div>

			<div class="flex gap-2 items-center">
				<select
					bind:value={defaultModelOptionValue}
					class="flex-1 px-3 py-1.5 rounded-md border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 text-sm"
					aria-label={$i18n.t('Default model')}
				>
					<option value="">{$i18n.t('— Select a default —')}</option>
					{#each selectModels as m (m.selection_key ?? m.id)}
						<option value={m.selection_key ?? m.id}>
							{m.name ?? m.id}{m.tags?.[0]?.name ? ` — ${m.tags[0].name}` : ''}
						</option>
					{/each}
				</select>
				<button
					class="px-3 py-1.5 rounded-md bg-gray-900 dark:bg-white text-white dark:text-gray-900 text-sm font-medium disabled:opacity-50"
					on:click={saveDefaultModelFromSettings}
					disabled={savingDefault || !defaultModelOptionValue}
				>
					{savingDefault ? $i18n.t('Saving…') : $i18n.t('Save')}
				</button>
			</div>
		</div>
	</div>
	<!-- ──────────────────────────────────────────────────────────────── -->

	<ProviderPicker mode="settings" />
</div>
