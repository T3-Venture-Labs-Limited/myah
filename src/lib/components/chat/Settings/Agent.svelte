<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import { getAgentConfig, getAgentConfigSchema, patchAgentConfig } from '$lib/apis/agent-config';
	import { updateUserSettings } from '$lib/apis/users';
	import { settings } from '$lib/stores';

	import AdvancedSection from './AgentSettings/AdvancedSection.svelte';
	import BehaviorSection from './AgentSettings/BehaviorSection.svelte';
	import ModelsSection from './AgentSettings/ModelsSection.svelte';
	import ReseedToast from './AgentSettings/ReseedToast.svelte';
	import SoulEditor from './AgentSettings/SoulEditor.svelte';
	import ToolsetsSection from './AgentSettings/ToolsetsSection.svelte';

	const i18n = getContext<any>('i18n');

	// Toggles for title/follow-up generation live here in the Agent tab's
	// ModelsSection. They persist through the same updateUserSettings path
	// SettingsModal uses. The legacy Interface tab duplicates were removed
	// (T3-982).
	async function saveSettings(updated: Record<string, unknown>) {
		await settings.set({ ...$settings, ...updated } as any);
		await updateUserSettings(localStorage.token, { ui: $settings });
	}

	let loaded = false;
	let loadError: string | null = null;
	let config: Record<string, any> = {};
	let schema: Record<string, any> = {};

	async function loadAll() {
		loaded = false;
		loadError = null;
		try {
			config = await getAgentConfig(localStorage.token);
		} catch (err) {
			loadError = `${err}`;
			toast.error(`${err}`);
			return;
		}
		// Schema is non-fatal — older agent containers may not expose it yet.
		// Missing schema just disables dropdowns/validators that depend on it.
		try {
			schema = await getAgentConfigSchema(localStorage.token);
		} catch (err) {
			console.warn('Agent schema unavailable, continuing with config only:', err);
			schema = {};
		}
		loaded = true;
	}

	async function handlePatch(body: Record<string, unknown>) {
		try {
			const updated = await patchAgentConfig(localStorage.token, body);
			config = (updated as any).config ?? updated;
			toast.success($i18n.t('Saved'));
		} catch (err) {
			toast.error(`${err}`);
		}
	}

	onMount(loadAll);
</script>

<div
	id="tab-agent"
	role="tabpanel"
	aria-labelledby="settings-tab-agent"
	class="flex flex-col h-full text-sm"
>
	<div class="font-medium mb-3">{$i18n.t('Agent')}</div>

	<div class="overflow-y-auto scrollbar-hidden h-full flex flex-col gap-3 pr-1">
		<ReseedToast />

		{#if loadError}
			<div class="flex flex-col gap-2 text-sm">
				<div class="text-red-500">
					{$i18n.t('Could not load agent settings.')}
				</div>
				<div class="text-gray-500 font-mono text-xs break-words">{loadError}</div>
				<div>
					<button
						type="button"
						class="px-3 py-1 rounded-md bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-xs"
						on:click={loadAll}
					>
						{$i18n.t('Retry')}
					</button>
				</div>
			</div>
		{:else if !loaded}
			<div class="text-sm text-gray-500">{$i18n.t('Loading agent settings…')}</div>
		{:else}
			<ModelsSection
				{config}
				{schema}
				onPatch={handlePatch}
				{saveSettings}
				on:reload={loadAll}
			/>
			<ToolsetsSection on:reload={loadAll} />
			<SoulEditor />
			<BehaviorSection {config} {schema} onPatch={handlePatch} on:reload={loadAll} />
			<AdvancedSection {config} {schema} onPatch={handlePatch} on:reload={loadAll} />
		{/if}
	</div>
</div>
