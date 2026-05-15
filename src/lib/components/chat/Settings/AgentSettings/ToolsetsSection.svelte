<script lang="ts">
	// Toolsets are the agent's permitted reach. Each toggle here narrows or
	// widens what it can do across every conversation. Saved per user, on
	// the agent's own config — no restart needed.
	import { createEventDispatcher, getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';

	import {
		getAgentToolsets,
		toggleAgentToolset,
		type AgentToolset
	} from '$lib/apis/agent';
	import Switch from '$lib/components/common/Switch.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';

	const i18n = getContext<any>('i18n');
	const dispatch = createEventDispatcher<{ reload: void }>();

	let loading = false;
	let saving: Record<string, boolean> = {};
	let toolsets: AgentToolset[] = [];
	let query = '';

	$: filtered = toolsets.filter((t) => {
		if (!query) return true;
		const q = query.toLowerCase();
		return (
			t.name.toLowerCase().includes(q) ||
			(t.label ?? '').toLowerCase().includes(q) ||
			t.tools.some((tool) => tool.name.toLowerCase().includes(q))
		);
	});

	async function load() {
		loading = true;
		try {
			toolsets = await getAgentToolsets(localStorage.token);
		} catch (err) {
			toast.error(`${$i18n.t('Failed to load toolsets')}: ${err}`);
		} finally {
			loading = false;
		}
	}

	async function toggle(name: string, enabled: boolean) {
		saving = { ...saving, [name]: true };
		try {
			await toggleAgentToolset(localStorage.token, name, enabled);
			toolsets = toolsets.map((t) => (t.name === name ? { ...t, enabled } : t));
			toast.success(`${name} ${enabled ? $i18n.t('enabled') : $i18n.t('disabled')}`);
			dispatch('reload');
		} catch (err) {
			// Revert visual state on failure
			toolsets = toolsets.map((t) => (t.name === name ? { ...t, enabled: !enabled } : t));
			toast.error(`${err}`);
		} finally {
			saving = { ...saving, [name]: false };
		}
	}

	onMount(load);
</script>

<section
	class="py-2 bg-white dark:bg-gray-900 rounded-3xl border border-gray-100/30 dark:border-gray-850/30"
>
	<div class="flex items-center justify-between px-4 mb-2">
		<div class="flex items-center gap-2">
			<div class="text-sm font-medium">{$i18n.t('Toolsets')}</div>
			<div class="text-xs text-gray-500">
				{toolsets.filter((t) => t.enabled).length} / {toolsets.length}
				{$i18n.t('enabled')}
			</div>
		</div>
	</div>

	<div class="flex w-full space-x-2 py-0.5 px-3.5 pb-2">
		<input
			class="w-full text-sm rounded-xl py-1.5 px-4 bg-transparent border border-gray-100 dark:border-gray-850 outline-none"
			placeholder={$i18n.t('Search toolsets...')}
			bind:value={query}
		/>
	</div>

	{#if loading}
		<div class="flex justify-center py-8">
			<Spinner className="size-5" />
		</div>
	{:else if filtered.length === 0}
		<div class="text-center text-gray-500 text-xs py-8">
			{query ? $i18n.t('No matching toolsets') : $i18n.t('No toolsets reported by the agent')}
		</div>
	{:else}
		<div class="flex flex-col gap-1 px-3.5 max-h-[28rem] overflow-y-auto">
			{#each filtered as ts (ts.name)}
				<div
					class="flex items-center justify-between px-3 py-2 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-850/50 transition group"
				>
					<div class="flex flex-col min-w-0 flex-1">
						<div class="flex items-center gap-2">
							<span class="font-mono text-xs truncate">{ts.name}</span>
							{#if ts.tools.length > 0}
								<span
									class="text-[10px] px-1.5 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-500"
								>
									{ts.tools.length}
									{$i18n.t('tools')}
								</span>
							{/if}
						</div>
						{#if ts.label && ts.label !== ts.name}
							<div class="text-xs text-gray-500 truncate mt-0.5">{ts.label}</div>
						{/if}
					</div>

					<div class="flex items-center gap-2 p-1">
						<Switch
							ariaLabelledbyId={`toolset-${ts.name}`}
							tooltip={true}
							state={ts.enabled}
							disabled={!!saving[ts.name]}
							on:change={(e) => toggle(ts.name, e.detail)}
						/>
					</div>
				</div>
			{/each}
		</div>
	{/if}
</section>
