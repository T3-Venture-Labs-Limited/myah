<!-- platform/src/lib/components/chat/Settings/Provider.svelte -->
<!-- What powers the voice behind the curtain. -->
<script lang="ts">
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { models as allModels, defaultModel } from '$lib/stores';
	import { setUserDefaultModel } from '$lib/apis/users';
	import { patchAgentConfig } from '$lib/apis/agent-config';
	import ProviderPicker from '$lib/components/Providers/ProviderPicker.svelte';

	const i18n = getContext('i18n');

	// ── Myah T3-932: Default model state ─────────────────────────────────
	// Hydrated from the $defaultModel store (session payload). Saving writes
	// the new user.default_model column AND updates the Hermes container's
	// agent.model config so background tasks (titles/tags) use the same
	// model the user picked.
	let defaultModelId: string = $defaultModel ?? '';
	$: defaultModelId = $defaultModel ?? defaultModelId;
	let savingDefault = false;

	async function saveDefaultModelFromSettings() {
		if (!defaultModelId || defaultModelId === 'myah') {
			toast.error($i18n.t('Pick a provider model first'));
			return;
		}
		savingDefault = true;
		const previous = $defaultModel;
		defaultModel.set(defaultModelId); // optimistic
		try {
			await setUserDefaultModel(localStorage.token, defaultModelId);
			// Keep the Hermes container's agent.model in sync so
			// title/tag/follow-up tasks use the same model by default.
			await patchAgentConfig(localStorage.token, { model: defaultModelId });
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
					bind:value={defaultModelId}
					class="flex-1 px-3 py-1.5 rounded-md border border-gray-300 dark:border-gray-700 bg-white dark:bg-gray-900 text-sm"
					aria-label={$i18n.t('Default model')}
				>
					<option value="">{$i18n.t('— Select a default —')}</option>
					{#each $allModels.filter((m) => m.id !== 'myah') as m (m.id)}
						<option value={m.id}>{m.name ?? m.id}</option>
					{/each}
				</select>
				<button
					class="px-3 py-1.5 rounded-md bg-gray-900 dark:bg-white text-white dark:text-gray-900 text-sm font-medium disabled:opacity-50"
					on:click={saveDefaultModelFromSettings}
					disabled={savingDefault || !defaultModelId}
				>
					{savingDefault ? $i18n.t('Saving…') : $i18n.t('Save')}
				</button>
			</div>
		</div>
	</div>
	<!-- ──────────────────────────────────────────────────────────────── -->

	<ProviderPicker mode="settings" />
</div>
