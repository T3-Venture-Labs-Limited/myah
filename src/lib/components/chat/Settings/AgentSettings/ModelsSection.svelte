<script lang="ts">
	import { createEventDispatcher, getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { getAuxResolved, resetAgentConfigSection } from '$lib/apis/agent-config';
	import type { AuxResolvedEntry } from '$lib/apis/agent-config';
	import { getCatalog } from '$lib/apis/providers';
	import type { CatalogEntry } from '$lib/apis/providers';
	import { AUX_DEFAULT_TASKS } from '$lib/utils/aux-capabilities';
	import { settings } from '$lib/stores';
	import {
		connectedValidProvidersV2,
		refreshProviderStatus
	} from '$lib/stores/providers';
	import Switch from '$lib/components/common/Switch.svelte';
	import ProviderDropdown from './ProviderDropdown.svelte';
	import ModelDropdown from './ModelDropdown.svelte';

	export let config: Record<string, any> = {};
	export let schema: Record<string, any> = {};
	export let onPatch: (body: Record<string, unknown>) => Promise<void>;
	export let saveSettings: (updated: Record<string, unknown>) => Promise<void> = async () => {};

	const i18n = getContext<any>('i18n');
	const dispatch = createEventDispatcher<{ reload: void }>();

	// ---------------------------------------------------------------------------
	// Catalog — loaded once on mount; drives provider/model dropdowns
	// ---------------------------------------------------------------------------

	let catalog: CatalogEntry[] = [];
	let auxResolved: Record<string, AuxResolvedEntry> = {};

	onMount(async () => {
		try {
			const raw = await getCatalog(localStorage.token);
			catalog = Object.values(raw);
		} catch (err) {
			console.warn('Could not load provider catalog for ModelsSection:', err);
		}
		try {
			await refreshProviderStatus(localStorage.token);
		} catch (err) {
			console.warn('Could not load provider status for ModelsSection:', err);
		}
		try {
			auxResolved = await getAuxResolved(localStorage.token);
		} catch (err) {
			console.warn('Could not load aux-resolved for ModelsSection:', err);
		}
	});

	// Filter providers to only connected ones. $connectedValidProvidersV2 is a derived store
	// listing provider IDs where the user has a valid credential.
	$: providerFilter = (p: CatalogEntry) => $connectedValidProvidersV2.includes(p.id);

	// ---------------------------------------------------------------------------
	// AdvancedTaskOverrides task definitions (same as former auxTasks)
	// ---------------------------------------------------------------------------

	type AuxTask = {
		key: string;
		label: string;
		section: string;
		toggle?: { read: () => boolean; write: (next: boolean) => Promise<void> };
	};

	// Toggles for title/follow-up generation. The Agent tab is the sole
	// control surface for these settings (legacy Interface tab duplicates
	// removed in T3-982).
	const auxTasks: AuxTask[] = [
		{ key: 'vision', label: 'Vision analysis', section: 'aux_vision' },
		{ key: 'web_extract', label: 'Web page extraction', section: 'aux_web_extract' },
		{ key: 'compression', label: 'Context compression', section: 'aux_compression' },
		{ key: 'session_search', label: 'Session search', section: 'aux_session_search' },
		{ key: 'skills_hub', label: 'Skills hub', section: 'aux_skills_hub' },
		{ key: 'approval', label: 'Approval classification', section: 'aux_approval' },
		{ key: 'mcp', label: 'MCP server inspection', section: 'aux_mcp' },
		{ key: 'flush_memories', label: 'Memory flush', section: 'aux_flush_memories' },
		{
			key: 'title_generation',
			label: 'Chat title generation',
			section: 'aux_title_generation',
			toggle: {
				read: () => $settings?.title?.auto ?? true,
				write: async (next) =>
					saveSettings({ title: { ...($settings?.title ?? {}), auto: next } })
			}
		},
		{
			key: 'follow_up_generation',
			label: 'Follow-up suggestions',
			section: 'aux_follow_up_generation',
			toggle: {
				read: () => $settings?.autoFollowUps ?? true,
				write: async (next) => saveSettings({ autoFollowUps: next })
			}
		}
	];

	// ---------------------------------------------------------------------------
	// Helpers
	// ---------------------------------------------------------------------------

	async function setAux(key: string, field: 'provider' | 'model', value: string) {
		// Empty provider becomes "auto" so the aux router runs the
		// auto-detection chain instead of failing silently.
		// See e2e-output/report.md ISSUE-011.
		const finalValue = field === 'provider' && value.trim() === '' ? 'auto' : value;
		await onPatch({ [`auxiliary.${key}.${field}`]: finalValue });
	}

	async function setMainModel(value: string) {
		await onPatch({ model: value });
	}

	async function resetSection(section: string) {
		try {
			await resetAgentConfigSection(localStorage.token, section);
			toast.success(`${section} reset`);
			dispatch('reload');
		} catch (err) {
			toast.error(`${err}`);
		}
	}

	async function onToggle(task: AuxTask, next: boolean) {
		if (!task.toggle) return;
		try {
			await task.toggle.write(next);
		} catch (err) {
			toast.error(`${err}`);
		}
	}

	// AuxDefault — a single provider+model pair written to all 8 non-vision tasks.
	// title_generation is the representative task used for reading the current value.
	let auxDefaultProvider: string = config.auxiliary?.title_generation?.provider ?? '';
	let auxDefaultModel: string = config.auxiliary?.title_generation?.model ?? '';

	// Sync local vars when config is refreshed externally (e.g. after reload dispatch)
	$: auxDefaultProvider = config.auxiliary?.title_generation?.provider ?? '';
	$: auxDefaultModel = config.auxiliary?.title_generation?.model ?? '';

	async function setAllAuxDefaultTasks(provider: string, model: string) {
		const patch: Record<string, string> = {};
		for (const task of AUX_DEFAULT_TASKS) {
			patch[`auxiliary.${task}.provider`] = provider;
			patch[`auxiliary.${task}.model`] = model;
		}
		await onPatch(patch);
	}

	// Vision row
	let visionProvider: string = config.auxiliary?.vision?.provider ?? '';
	let visionModel: string = config.auxiliary?.vision?.model ?? '';

	$: visionProvider = config.auxiliary?.vision?.provider ?? '';
	$: visionModel = config.auxiliary?.vision?.model ?? '';
</script>

<section
	class="py-2 bg-white dark:bg-gray-900 rounded-3xl border border-gray-100/30 dark:border-gray-850/30"
>
	<div class="flex items-center justify-between px-4 mb-2">
		<div class="text-sm font-medium">{$i18n.t('Models')}</div>
	</div>

	<!-- Main chat model -->
	<div class="px-3.5 mb-3">
		<label for="agent-main-model" class="mb-1 block text-xs text-gray-500">
			{$i18n.t('Main chat model')}
		</label>
		<div class="flex items-center gap-2">
			<input
				id="agent-main-model"
				type="text"
				class="flex-1 text-sm rounded-xl py-1.5 px-4 bg-transparent border border-gray-100 dark:border-gray-850 outline-none"
				value={config.model ?? ''}
				on:blur={(e) => setMainModel((e.target as HTMLInputElement).value)}
				placeholder="anthropic/claude-opus-4.6"
			/>
			<button
				type="button"
				class="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
				on:click={() => resetSection('model')}
			>
				{$i18n.t('Reset')}
			</button>
		</div>
	</div>

	<!-- ── Group 1: Aux default model (single row) ──────────────────────── -->
	<div class="px-3.5 text-xs text-gray-400 dark:text-gray-500 uppercase tracking-wider mt-2 mb-1">
		{$i18n.t('Aux default model')}
	</div>
	<p class="px-3.5 mb-2 text-xs text-gray-500">
		{$i18n.t('Used for titles, follow-ups, compression, and other background tasks.')}
	</p>

	<div
		class="flex flex-col gap-0.5 px-6 py-1.5 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-850/50 transition"
	>
		<div class="flex items-center gap-2">
			<ProviderDropdown
				bind:value={auxDefaultProvider}
				{catalog}
				filter={providerFilter}
				on:change={() => setAllAuxDefaultTasks(auxDefaultProvider, auxDefaultModel)}
			/>
			<ModelDropdown
				bind:value={auxDefaultModel}
				provider={auxDefaultProvider}
				task="compression"
				{catalog}
				showDefault={true}
				on:change={() => setAllAuxDefaultTasks(auxDefaultProvider, auxDefaultModel)}
			/>
		</div>
		{#if auxResolved.title_generation}
			<div class="text-xs text-gray-400 dark:text-gray-500 pl-1">
				{$i18n.t('Resolved')}: {auxResolved.title_generation.provider}/{auxResolved
					.title_generation.model ?? '(provider default)'}
				{#if auxResolved.title_generation.source !== 'config'}
					· <span class="italic">{auxResolved.title_generation.source}</span>
				{/if}
			</div>
		{/if}
	</div>

	<!-- ── Group 2: Vision row ───────────────────────────────────────────── -->
	<div class="px-3.5 text-xs text-gray-400 dark:text-gray-500 uppercase tracking-wider mt-4 mb-1">
		{$i18n.t('Vision')}
	</div>

	<div
		class="flex flex-col gap-0.5 px-6 py-1.5 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-850/50 transition"
	>
		<div class="flex items-center gap-2">
			<ProviderDropdown
				bind:value={visionProvider}
				{catalog}
				filter={providerFilter}
				on:change={() => setAux('vision', 'provider', visionProvider)}
			/>
			<ModelDropdown
				bind:value={visionModel}
				provider={visionProvider}
				task="vision"
				{catalog}
				showDefault={true}
				on:change={() => setAux('vision', 'model', visionModel)}
			/>
			<button
				type="button"
				class="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
				on:click={() => resetSection('aux_vision')}
			>
				{$i18n.t('Reset')}
			</button>
		</div>
		{#if auxResolved.vision}
			<div class="text-xs text-gray-400 dark:text-gray-500 pl-1">
				{$i18n.t('Resolved')}: {auxResolved.vision.provider}/{auxResolved.vision.model ??
					'(provider default)'}
				{#if auxResolved.vision.source !== 'config'}
					· <span class="italic">{auxResolved.vision.source}</span>
				{/if}
			</div>
		{/if}
	</div>

	<!-- ── Group 3: AdvancedTaskOverrides (collapsible) ──────────────────── -->
	<details class="mt-4 group">
		<summary
			class="cursor-pointer px-3.5 text-xs text-gray-400 dark:text-gray-500 uppercase tracking-wider select-none flex items-center gap-1 hover:text-gray-600 dark:hover:text-gray-300 transition"
		>
			<span
				class="inline-block transition-transform duration-150 group-open:rotate-90"
				aria-hidden="true">▶</span
			>
			{$i18n.t('Advanced task overrides')}
		</summary>

		<div class="flex flex-col gap-1 px-3.5 mt-2">
			{#each auxTasks as task (task.key)}
				{@const enabled = task.toggle ? task.toggle.read() : true}
				<div
					class="flex flex-col gap-1 px-3 py-2 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-850/50 transition"
				>
					<div class="flex items-center justify-between gap-2">
						<label
							for={`agent-aux-${task.key}-provider`}
							class="text-xs font-medium {task.toggle && !enabled
								? 'text-gray-400 dark:text-gray-600'
								: ''}"
						>
							{task.label}
						</label>
						{#if task.toggle}
							<Switch
								ariaLabelledbyId={`agent-aux-${task.key}-toggle`}
								tooltip={true}
								state={enabled}
								on:change={(e) => onToggle(task, e.detail)}
							/>
						{/if}
					</div>
					<div class="flex items-center gap-2">
						<input
							id={`agent-aux-${task.key}-provider`}
							type="text"
							class="w-32 text-xs rounded-lg py-1 px-3 bg-transparent border border-gray-100 dark:border-gray-850 outline-none disabled:opacity-50"
							placeholder="auto"
							value={config.auxiliary?.[task.key]?.provider ?? ''}
							disabled={task.toggle && !enabled}
							on:blur={(e) =>
								setAux(task.key, 'provider', (e.target as HTMLInputElement).value)}
						/>
						<input
							type="text"
							class="flex-1 text-xs rounded-lg py-1 px-3 bg-transparent border border-gray-100 dark:border-gray-850 outline-none disabled:opacity-50"
							placeholder="model"
							value={config.auxiliary?.[task.key]?.model ?? ''}
							disabled={task.toggle && !enabled}
							on:blur={(e) => setAux(task.key, 'model', (e.target as HTMLInputElement).value)}
						/>
						{#if auxResolved[task.key]}
							<span class="text-xs text-gray-400 dark:text-gray-500 whitespace-nowrap">
								→ {auxResolved[task.key].provider}/{auxResolved[task.key].model ?? '(default)'}
							</span>
						{/if}
						<button
							type="button"
							class="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
							on:click={() => resetSection(task.section)}
						>
							{$i18n.t('Reset')}
						</button>
					</div>
				</div>
			{/each}
		</div>
	</details>

	<p class="mt-2 px-4 text-xs text-gray-500">
		{$i18n.t(
			'Empty provider fields auto-detect from your main model. The "Resolved" hints above show the exact model that will be used.'
		)}
	</p>
</section>
