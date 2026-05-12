<script lang="ts">
	import { toast } from 'svelte-sonner';

	import { onMount, getContext, onDestroy } from 'svelte';
	const i18n = getContext('i18n');

	import { user } from '$lib/stores';
	import { goto } from '$app/navigation';
	import {
		getAgentToolsets,
		toggleAgentToolset,
		getAgentPlugins,
		deleteAgentPlugin,
		type AgentToolset,
		type AgentPlugin
	} from '$lib/apis/agent';

	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import DeleteConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import EllipsisHorizontal from '$lib/components/icons/EllipsisHorizontal.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import ChevronRight from '$lib/components/icons/ChevronRight.svelte';
	import Wrench from '$lib/components/icons/Wrench.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import ToolMenu from '$lib/components/workspace/Tools/ToolMenu.svelte';

	let shiftKey = false;
	let loading = false;

	let query = '';
	let searchDebounceTimer: ReturnType<typeof setTimeout>;

	let toolsets: AgentToolset[] = [];
	let plugins: AgentPlugin[] = [];

	let selectedPlugin: AgentPlugin | null = null;
	let showDeleteConfirm = false;

	let expanded: Record<string, boolean> = {};

	$: filteredToolsets = toolsets.filter(
		(t) =>
			!query ||
			t.name.toLowerCase().includes(query.toLowerCase()) ||
			t.label.toLowerCase().includes(query.toLowerCase())
	);

	$: filteredPlugins = plugins.filter(
		(p) =>
			!query ||
			p.name.toLowerCase().includes(query.toLowerCase()) ||
			p.description.toLowerCase().includes(query.toLowerCase())
	);

	$: if (query !== undefined) {
		clearTimeout(searchDebounceTimer);
		searchDebounceTimer = setTimeout(() => {}, 300);
	}

	const init = async () => {
		loading = true;
		try {
			[toolsets, plugins] = await Promise.all([
				getAgentToolsets(localStorage.token),
				getAgentPlugins(localStorage.token)
			]);
		} catch (err) {
			toast.error(`${err}`);
		} finally {
			loading = false;
		}
	};

	const toggleHandler = async (toolset: AgentToolset) => {
		try {
			const updated = await toggleAgentToolset(localStorage.token, toolset.name, !toolset.enabled);
			toolsets = toolsets.map((t) => (t.name === updated.name ? updated : t));
		} catch (err) {
			toast.error(typeof err === 'string' ? err : $i18n.t('Failed to toggle toolset'));
		}
	};

	const deletePluginHandler = async (plugin: AgentPlugin) => {
		const res = await deleteAgentPlugin(localStorage.token, plugin.name).catch((err) => {
			toast.error(`${err}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t('Tool deleted successfully'));
			await init();
		}
	};

	onMount(async () => {
		await init();

		const onKeyDown = (event: KeyboardEvent) => {
			if (event.key === 'Shift') shiftKey = true;
		};
		const onKeyUp = (event: KeyboardEvent) => {
			if (event.key === 'Shift') shiftKey = false;
		};
		const onBlur = () => {
			shiftKey = false;
		};

		window.addEventListener('keydown', onKeyDown);
		window.addEventListener('keyup', onKeyUp);
		window.addEventListener('blur-sm', onBlur);

		return () => {
			clearTimeout(searchDebounceTimer);
			window.removeEventListener('keydown', onKeyDown);
			window.removeEventListener('keyup', onKeyUp);
			window.removeEventListener('blur-sm', onBlur);
		};
	});

	onDestroy(() => {
		clearTimeout(searchDebounceTimer);
	});
</script>

<div
	class="py-2 bg-white dark:bg-gray-900 rounded-3xl"
>
	<div class="flex items-center gap-2 px-1 mb-2">
		<div class="flex flex-1 items-center space-x-2 py-0.5">
			<div class="self-center ml-1 mr-3">
				<Search className="size-3.5" />
			</div>
			<input
				class="w-full text-sm pr-4 py-1 rounded-r-xl outline-hidden bg-transparent"
				bind:value={query}
				aria-label={$i18n.t('Search Tools')}
				placeholder={$i18n.t('Search Tools')}
			/>
			{#if query}
				<div class="self-center pl-1.5 translate-y-[0.5px] rounded-l-xl bg-transparent">
					<button
						class="p-0.5 rounded-full hover:bg-gray-100 dark:hover:bg-gray-900 transition"
						aria-label={$i18n.t('Clear search')}
						on:click={() => {
							query = '';
						}}
					>
						<XMark className="size-3" strokeWidth="2" />
					</button>
				</div>
			{/if}
		</div>

		<div class="text-xs text-gray-500 dark:text-gray-400 shrink-0">
			{filteredToolsets.length + filteredPlugins.length}
			{$i18n.t('tools')}
		</div>

		{#if $user}
			<a
				class="px-2 py-1 rounded-xl bg-black text-white dark:bg-white dark:text-black transition font-medium text-xs flex items-center shrink-0"
				href="/agent/tools/create"
			>
				<Plus className="size-3" strokeWidth="2.5" />
				<div class="ml-1">{$i18n.t('New Tool')}</div>
			</a>
		{/if}
	</div>

	{#if loading}
		<div class="w-full h-full flex justify-center items-center my-16 mb-24">
			<Spinner className="size-5" />
		</div>
	{:else if filteredToolsets.length === 0 && filteredPlugins.length === 0}
		<div class="w-full h-full flex flex-col justify-center items-center my-16 mb-24">
			<div class="max-w-md text-center">
				<div class="mb-3">
					<Wrench className="size-8 text-gray-300 dark:text-gray-600 mx-auto" />
				</div>
				<div class="text-lg font-medium mb-1">{$i18n.t('No tools found')}</div>
				<div class="text-gray-500 text-center text-xs">
					{$i18n.t('Try adjusting your search or filter to find what you are looking for.')}
				</div>
			</div>
		</div>
	{:else}
		{#if filteredToolsets.length > 0}
			<div class="my-2 gap-2 grid px-3 lg:grid-cols-2">
				{#each filteredToolsets as toolset (toolset.name)}
					<div
						class="flex flex-col text-left w-full px-3 py-2.5 transition rounded-2xl dark:hover:bg-gray-850/50 hover:bg-gray-50"
					>
						<div class="flex space-x-4">
							<button
								class="flex flex-1 space-x-3.5 text-left"
								on:click={() => (expanded[toolset.name] = !expanded[toolset.name])}
							>
								<div class="flex items-center text-left">
									<div class="flex-1 self-center">
										<Tooltip content={toolset.name} placement="top-start">
											<div class="flex items-center gap-1.5">
												<div class="line-clamp-1 text-sm">
													{toolset.label || toolset.name}
												</div>
												<div class="text-gray-500 text-xs font-medium shrink-0">
													{toolset.tools.length}
													{$i18n.t('tools')}
												</div>
											</div>
										</Tooltip>
										<div class="px-0.5">
											<div class="flex items-center gap-1 text-xs text-gray-500 shrink-0">
												{#if expanded[toolset.name]}
													<ChevronDown className="size-2.5" />
													<span>{$i18n.t('Hide tools')}</span>
												{:else}
													<ChevronRight className="size-2.5" />
													<span>{$i18n.t('Show tools')}</span>
												{/if}
											</div>
										</div>
									</div>
								</div>
							</button>
							<div class="flex flex-row gap-0.5 self-center">
								<button
									class="flex h-[1.125rem] min-h-[1.125rem] w-8 shrink-0 items-center rounded-full px-1 mx-[1px] transition outline outline-1 {toolset.enabled
										? 'bg-gray-700 dark:bg-gray-200 outline-gray-700 dark:outline-gray-200'
										: 'bg-gray-200 dark:bg-transparent outline-gray-100 dark:outline-gray-800'}"
									aria-label={toolset.enabled ? $i18n.t('Enabled') : $i18n.t('Disabled')}
									on:click={() => toggleHandler(toolset)}
								>
									<span
										class="pointer-events-none block size-3 shrink-0 rounded-full transition-transform {toolset.enabled
											? 'translate-x-3 bg-white dark:bg-gray-900'
											: 'translate-x-0 bg-white shadow-sm'}"
									></span>
								</button>
							</div>
						</div>

						{#if expanded[toolset.name]}
							<div class="mt-2 ml-1 space-y-0.5">
								{#each toolset.tools as tool}
									<div
										class="flex space-x-4 px-2 py-2 rounded-xl hover:bg-gray-100/50 dark:hover:bg-gray-800/50 transition"
									>
										<div class="self-center shrink-0">
											<Wrench className="size-3.5 text-gray-400 dark:text-gray-500" />
										</div>
										<div class="flex-1 min-w-0">
											<div
												class="text-xs font-medium text-gray-700 dark:text-gray-300 line-clamp-1"
											>
												{tool.name}
											</div>
											<div class="text-xs text-gray-400 dark:text-gray-500 line-clamp-2 mt-0.5">
												{tool.description}
											</div>
										</div>
									</div>
								{/each}
							</div>
						{/if}
					</div>
				{/each}
			</div>
		{/if}

		{#if filteredPlugins.length > 0 || !query}
			{#if filteredToolsets.length > 0}
				<hr class="border-gray-100 dark:border-gray-850 mx-3 my-1" />

				<div class="mt-0.5 mb-1 px-3">
					<div class="text-xs text-gray-500 dark:text-gray-500 font-medium px-0.5">
						{$i18n.t('Custom Tools')}
					</div>
				</div>
			{/if}

			{#if filteredPlugins.length > 0}
				<div class="my-2 gap-2 grid px-3 lg:grid-cols-2">
					{#each filteredPlugins as plugin (plugin.filename)}
						<Tooltip content={plugin?.description ?? plugin?.name}>
							<a
								class="flex space-x-3 text-left w-full px-3 py-2.5 transition rounded-2xl cursor-pointer dark:hover:bg-gray-850/50 hover:bg-gray-50 no-underline text-inherit"
								href={`/agent/tools/edit?id=${encodeURIComponent(plugin.name)}`}
							>
								<div class="self-center shrink-0">
									<Wrench className="size-4 text-gray-500 dark:text-gray-400" />
								</div>
								<div class="flex-1 min-w-0 self-center">
									<div class="flex items-center gap-2">
										<div class="line-clamp-1 text-sm font-medium">{plugin.name}</div>
									</div>
									<div class="text-xs text-gray-500 dark:text-gray-400 line-clamp-2 mt-0.5">
										{plugin.description || $i18n.t('Custom tool')}
									</div>
								</div>
								<div
									class="flex flex-row gap-0.5 self-center shrink-0"
									on:click|preventDefault|stopPropagation
									role="presentation"
								>
									{#if shiftKey}
										<Tooltip content={$i18n.t('Delete')}>
											<button
												class="self-center w-fit text-sm px-2 py-2 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
												type="button"
												aria-label={$i18n.t('Delete')}
												on:click={() => {
													deletePluginHandler(plugin);
												}}
											>
												<GarbageBin />
											</button>
										</Tooltip>
									{:else}
										<ToolMenu
											editHandler={() => {
												goto(`/agent/tools/edit?id=${encodeURIComponent(plugin.name)}`);
											}}
											cloneHandler={() => {
												sessionStorage.tool = JSON.stringify({
													id: `${plugin.name}-clone`,
													name: `${plugin.name}-clone`,
													meta: { description: plugin.description || '' },
													content: plugin.content || ''
												});
												goto('/agent/tools/create');
											}}
											exportHandler={() => {
												const blob = new Blob([plugin.content || ''], {
													type: 'text/x-python'
												});
												const url = URL.createObjectURL(blob);
												const a = document.createElement('a');
												a.href = url;
												a.download = `${plugin.name}.py`;
												a.click();
												URL.revokeObjectURL(url);
											}}
											deleteHandler={async () => {
												selectedPlugin = plugin;
												showDeleteConfirm = true;
											}}
											onClose={() => {}}
										>
											<button
												class="self-center w-fit text-sm p-1.5 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
												type="button"
											>
												<EllipsisHorizontal className="size-5" />
											</button>
										</ToolMenu>
									{/if}
								</div>
							</a>
						</Tooltip>
					{/each}
				</div>
			{:else}
				<div class="px-4 pb-4 pt-2 text-sm text-gray-400">
					{$i18n.t('No custom tools yet.')}
					{#if $user}
						<a
				href="/agent/tools/create"
							class="text-gray-500 dark:text-gray-400 underline ml-1">{$i18n.t('Create one')}</a
						>
					{/if}
				</div>
			{/if}
		{/if}
	{/if}
</div>

<DeleteConfirmDialog
	bind:show={showDeleteConfirm}
	title={$i18n.t('Delete tool?')}
	on:confirm={() => {
		if (selectedPlugin) deletePluginHandler(selectedPlugin);
	}}
>
	<div class="text-sm text-gray-500 truncate">
		{$i18n.t('This will delete')} <span class="font-medium">{selectedPlugin?.name}</span>.
	</div>
</DeleteConfirmDialog>
