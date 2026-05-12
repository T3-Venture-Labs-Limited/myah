<script lang="ts">
	import { DropdownMenu } from 'bits-ui';
	import { marked } from 'marked';
	import Fuse from 'fuse.js';

	import dayjs from '$lib/dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';
	dayjs.extend(relativeTime);

	import Spinner from '$lib/components/common/Spinner.svelte';
	import { flyAndScale } from '$lib/utils/transitions';

	import { createEventDispatcher, onMount, getContext, tick } from 'svelte';
	import { goto } from '$app/navigation';

	import {
		user,
		MODEL_DOWNLOAD_POOL,
		models,
		mobile,
		temporaryChatEnabled,
		settings,
		config,
		chatId,
		defaultModel
	} from '$lib/stores';
	import { setChatSessionModel } from '$lib/apis/agent';
	import { patchAgentConfig } from '$lib/apis/agent-config';
	import { setUserDefaultModel } from '$lib/apis/users';
	import { toast } from 'svelte-sonner';
	import { capitalizeFirstLetter, sanitizeResponseContent, splitStream } from '$lib/utils';
	import { providerStatusV2, connectedValidProvidersV2 } from '$lib/stores/providers';

	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import Check from '$lib/components/icons/Check.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Switch from '$lib/components/common/Switch.svelte';
	import ChatBubbleOval from '$lib/components/icons/ChatBubbleOval.svelte';

	import ModelItem from './ModelItem.svelte';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let id = '';
	export let value = '';
	export let placeholder = $i18n.t('Select a model');
	export let searchEnabled = true;
	export let searchPlaceholder = $i18n.t('Search a model');

	export let items: {
		label: string;
		value: string;
		model: Model;
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		[key: string]: any;
	}[] = [];

	export let className = 'w-[32rem]';
	export let triggerClassName = 'text-lg';

	export let pinModelHandler: (modelId: string) => void = () => {};

	// ── Myah T3-932: promote a model to the user's global default ─────────────
	// Called from ModelItem (inline button) and ModelItemMenu (kebab entry).
	// Optimistically updates the store, then writes to the backend; rolls back
	// on failure so the badge doesn't lie.
	const setDefaultHandler = async (modelId: string) => {
		if (!modelId || modelId === 'myah') return;
		const previous = $defaultModel;
		defaultModel.set(modelId);
		try {
			await setUserDefaultModel(localStorage.token, modelId);
		// Keep the Hermes container's agent.model in sync so
		// background tasks (title/tag/follow-up) use the same model.
		// Fire-and-forget — the platform-side default has already
		// persisted; a Hermes sync failure shouldn't block the toast.
		patchAgentConfig(localStorage.token, { model: modelId }).catch((err) =>
			console.warn('[model-selector] patchAgentConfig sync failed', err)
		);
			const name = items.find((i) => i.value === modelId)?.label ?? modelId;
			toast.success($i18n.t('Default model set to {{modelName}}', { modelName: name }));
		} catch (err) {
			console.error('[model-selector] setUserDefaultModel failed', err);
			defaultModel.set(previous);
			toast.error(typeof err === 'string' ? err : $i18n.t('Could not update default model'));
		}
	};
	// ──────────────────────────────────────────────────────────────────────────

	let tagsContainerElement;

	let show = false;
	let tags = [];

	let selectedModel = '';
	$: selectedModel = items.find((item) => item.value === value) ?? '';

	let searchValue = '';

	let selectedTag = '';
	let selectedConnectionType = '';
	let selectedProvider = '';

	let selectedModelIdx = 0;

	const fuse = new Fuse(
		items.map((item) => {
			const _item = {
				...item,
				modelName: item.model?.name,
				tags: (item.model?.tags ?? []).map((tag) => tag.name).join(' '),
				desc: item.model?.info?.meta?.description
			};
			return _item;
		}),
		{
			keys: ['value', 'tags', 'modelName'],
			threshold: 0.4
		}
	);

	const updateFuse = () => {
		if (fuse) {
			fuse.setCollection(
				items.map((item) => {
					const _item = {
						...item,
						modelName: item.model?.name,
						tags: (item.model?.tags ?? []).map((tag) => tag.name).join(' '),
						desc: item.model?.info?.meta?.description
					};
					return _item;
				})
			);
		}
	};

	$: if (items) {
		updateFuse();
	}

	$: filteredItems = (
		searchValue
			? fuse
					.search(searchValue)
					.map((e) => {
						return e.item;
					})
					.filter((item) => {
						if (selectedTag === '') {
							return true;
						}

						return (item.model?.tags ?? [])
							.map((tag) => tag.name.toLowerCase())
							.includes(selectedTag.toLowerCase());
					})
					.filter((item) => {
						if (selectedConnectionType === '') {
							return true;
						} else if (selectedConnectionType === 'local') {
							return item.model?.connection_type === 'local';
						} else if (selectedConnectionType === 'external') {
							return item.model?.connection_type === 'external';
						} else if (selectedConnectionType === 'direct') {
							return item.model?.direct;
						}
					})
			: items
					.filter((item) => {
						if (selectedTag === '') {
							return true;
						}
						return (item.model?.tags ?? [])
							.map((tag) => tag.name.toLowerCase())
							.includes(selectedTag.toLowerCase());
					})
					.filter((item) => {
						if (selectedConnectionType === '') {
							return true;
						} else if (selectedConnectionType === 'local') {
							return item.model?.connection_type === 'local';
						} else if (selectedConnectionType === 'external') {
							return item.model?.connection_type === 'external';
						} else if (selectedConnectionType === 'direct') {
							return item.model?.direct;
						}
					})
	).filter((item) => !(item.model?.info?.meta?.hidden ?? false));

	$: if (
		selectedTag !== undefined ||
		selectedConnectionType !== undefined ||
		searchValue !== undefined
	) {
		resetView();
	}

	const resetView = async () => {
		await tick();

		const selectedInFiltered = filteredItems.findIndex((item) => item.value === value);

		if (selectedInFiltered >= 0) {
			// The selected model is visible in the current filter
			selectedModelIdx = selectedInFiltered;
		} else {
			// The selected model is not visible, default to first item in filtered list
			selectedModelIdx = 0;
		}

		// Set the virtual scroll position so the selected item is rendered and centered
		const targetScrollTop = Math.max(0, selectedModelIdx * ITEM_HEIGHT - 128 + ITEM_HEIGHT / 2);
		listScrollTop = targetScrollTop;

		await tick();

		if (listContainer) {
			listContainer.scrollTop = targetScrollTop;
		}

		await tick();
		const item = document.querySelector(`[data-arrow-selected="true"]`);
		item?.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' });
	};

	onMount(async () => {
		if (items) {
			tags = items
				.filter((item) => !(item.model?.info?.meta?.hidden ?? false))
				.flatMap((item) => item.model?.tags ?? [])
				.map((tag) => tag.name.toLowerCase());
			// Remove duplicates and sort
			tags = Array.from(new Set(tags)).sort((a, b) => a.localeCompare(b));
		}
	});

	const ITEM_HEIGHT = 42;
	const OVERSCAN = 10;

	let listScrollTop = 0;
	let listContainer;

	$: visibleStart = Math.max(0, Math.floor(listScrollTop / ITEM_HEIGHT) - OVERSCAN);
	$: visibleEnd = Math.min(
		filteredItems.length,
		Math.ceil((listScrollTop + 256) / ITEM_HEIGHT) + OVERSCAN
	);
</script>

<DropdownMenu.Root
	bind:open={show}
	onOpenChange={async () => {
		searchValue = '';
		listScrollTop = 0;
		window.setTimeout(() => document.getElementById('model-search-input')?.focus(), 0);

		resetView();
	}}
	onOpenChangeComplete={(open) => {
		if (!open) {
			// Replaces the old closeFocus={false} behavior - prevent focus jump back to trigger
			document.getElementById(`model-selector-${id}-button`)?.blur();
		}
	}}
>
	<DropdownMenu.Trigger
		class="relative w-full {($settings?.highContrastMode ?? false)
			? ''
			: 'outline-hidden focus:outline-hidden'}"
		aria-label={selectedModel
			? $i18n.t('Selected model: {{modelName}}', { modelName: selectedModel.label })
			: placeholder}
		id="model-selector-{id}-button"
	>
		<div
			class="flex w-full text-left px-0.5 bg-transparent truncate {triggerClassName} justify-between {($settings?.highContrastMode ??
			false)
				? 'dark:placeholder-gray-100 placeholder-gray-800'
				: 'placeholder-gray-400'}"
		>
			{#if selectedModel}
				{selectedModel.label}
			{:else}
				{placeholder}
			{/if}
			<ChevronDown className=" self-center ml-2 size-3" strokeWidth="2.5" />
		</div>
	</DropdownMenu.Trigger>

	<DropdownMenu.Portal>
		<DropdownMenu.Content
			forceMount
			trapFocus={false}
			preventScroll={false}
			side="bottom"
			align={$mobile ? 'center' : 'start'}
			sideOffset={2}
			alignOffset={-1}
		>
			{#snippet child({ wrapperProps, props, open })}
				{#if open}
					<div {...wrapperProps}>
						<div
							{...props}
							class="{props.class} z-40 {$mobile
								? `w-full`
								: `${className}`} max-w-[calc(100vw-1rem)] justify-start rounded-2xl bg-white dark:bg-gray-850 dark:text-white shadow-lg outline-hidden"
							transition:flyAndScale
						>
							<slot>
								{#if searchEnabled}
									<div class="flex items-center gap-2.5 px-4.5 pt-3.5 mb-1.5">
										<Search className="size-4" strokeWidth="2.5" />

										<input
											id="model-search-input"
											bind:value={searchValue}
											class="w-full text-sm bg-transparent outline-hidden"
											placeholder={searchPlaceholder}
											autocomplete="off"
											aria-label={$i18n.t('Search In Models')}
											on:keydown={(e) => {
												if (e.code === 'Enter' && filteredItems.length > 0) {
													value = filteredItems[selectedModelIdx].value;
													show = false;
													return; // dont need to scroll on selection
												} else if (e.code === 'ArrowDown') {
													e.stopPropagation();
													selectedModelIdx = Math.min(
														selectedModelIdx + 1,
														filteredItems.length - 1
													);
												} else if (e.code === 'ArrowUp') {
													e.stopPropagation();
													selectedModelIdx = Math.max(selectedModelIdx - 1, 0);
												} else {
													// if the user types something, reset to the top selection.
													selectedModelIdx = 0;
												}

												const item = document.querySelector(`[data-arrow-selected="true"]`);
												item?.scrollIntoView({
													block: 'center',
													inline: 'nearest',
													behavior: 'instant'
												});
											}}
										/>
									</div>
								{/if}

								<div class="px-2">
									{#if (tags && items.filter((item) => !(item.model?.info?.meta?.hidden ?? false)).length > 0) || $connectedValidProvidersV2.length > 0}
										<div
											class=" flex w-full bg-white dark:bg-gray-850 overflow-x-auto scrollbar-none font-[450] mb-0.5"
											on:wheel={(e) => {
												if (e.deltaY !== 0) {
													e.preventDefault();
													e.currentTarget.scrollLeft += e.deltaY;
												}
											}}
										>
											<div
												class="flex gap-1 w-fit text-center text-sm rounded-full bg-transparent px-1.5 whitespace-nowrap"
												bind:this={tagsContainerElement}
											>
												{#if items.find((item) => item.model?.connection_type === 'local') || items.find((item) => item.model?.connection_type === 'external') || items.find((item) => item.model?.direct) || tags.length > 0 || $connectedValidProvidersV2.length > 0}
													<button
														class="min-w-fit outline-none px-1.5 py-0.5 {selectedTag === '' &&
														selectedConnectionType === '' &&
														selectedProvider === ''
															? ''
															: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition capitalize"
														aria-pressed={selectedTag === '' &&
															selectedConnectionType === '' &&
															selectedProvider === ''}
														on:click={() => {
															selectedConnectionType = '';
															selectedTag = '';
															selectedProvider = '';
														}}
													>
														{$i18n.t('All')}
													</button>
												{/if}

												<!-- Dynamic provider tabs — one per connected provider -->
												{#each $connectedValidProvidersV2 as provider}
													<button
														class="min-w-fit outline-none px-1.5 py-0.5 {selectedProvider ===
														provider
															? ''
															: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition capitalize"
														aria-pressed={selectedProvider === provider}
														on:click={() => {
															selectedProvider = provider;
															selectedTag = provider;
															selectedConnectionType = '';
														}}
													>
														{provider}
													</button>
												{/each}

												{#if items.find((item) => item.model?.connection_type === 'local')}
													<button
														class="min-w-fit outline-none px-1.5 py-0.5 {selectedConnectionType ===
														'local'
															? ''
															: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition capitalize"
														aria-pressed={selectedConnectionType === 'local'}
														on:click={() => {
															selectedTag = '';
															selectedConnectionType = 'local';
															selectedProvider = '';
														}}
													>
														{$i18n.t('Local')}
													</button>
												{/if}

												{#if items.find((item) => item.model?.connection_type === 'external')}
													<button
														class="min-w-fit outline-none px-1.5 py-0.5 {selectedConnectionType ===
														'external'
															? ''
															: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition capitalize"
														aria-pressed={selectedConnectionType === 'external'}
														on:click={() => {
															selectedTag = '';
															selectedConnectionType = 'external';
															selectedProvider = '';
														}}
													>
														{$i18n.t('External')}
													</button>
												{/if}

												{#if items.find((item) => item.model?.direct)}
													<button
														class="min-w-fit outline-none px-1.5 py-0.5 {selectedConnectionType ===
														'direct'
															? ''
															: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition capitalize"
														aria-pressed={selectedConnectionType === 'direct'}
														on:click={() => {
															selectedTag = '';
															selectedConnectionType = 'direct';
															selectedProvider = '';
														}}
													>
														{$i18n.t('Direct')}
													</button>
												{/if}

												{#each tags.filter((t) => !$connectedValidProvidersV2.includes(t)) as tag}
													<Tooltip content={tag}>
														<button
															class="min-w-fit outline-none px-1.5 py-0.5 {selectedTag === tag &&
															selectedProvider === ''
																? ''
																: 'text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition capitalize"
															aria-pressed={selectedTag === tag && selectedProvider === ''}
															on:click={() => {
																selectedConnectionType = '';
																selectedTag = tag;
																selectedProvider = '';
															}}
														>
															{tag.length > 16 ? `${tag.slice(0, 16)}...` : tag}
														</button>
													</Tooltip>
												{/each}
											</div>
										</div>
									{/if}
								</div>

								{#if $providerStatusV2 !== null && $connectedValidProvidersV2.length === 0}
									<div class="flex flex-col items-start justify-center py-4 px-4">
										<div class="text-sm font-medium text-gray-900 dark:text-gray-100 mb-1">
											{$i18n.t('No providers connected')}
										</div>
										<div class="text-xs text-gray-500 dark:text-gray-400 mb-3">
											{$i18n.t('Connect an AI provider to access models')}
										</div>
										<a
											href="/?settings=true"
											class="px-4 py-1.5 rounded-xl text-xs font-medium bg-gray-900 dark:bg-white text-white dark:text-gray-900 hover:bg-gray-800 dark:hover:bg-gray-100 transition"
											on:click={() => {
												show = false;
											}}
										>
											{$i18n.t('Connect a provider')}
										</a>
									</div>
								{/if}

								<div class="px-2.5 group relative">
									{#if filteredItems.length === 0}
										{#if items.length === 0 && $user?.role === 'admin'}
											<div class="flex flex-col items-start justify-center py-6 px-4 text-start">
												<div class="text-sm font-medium text-gray-900 dark:text-gray-100 mb-1">
													{$i18n.t('No models available')}
												</div>
												<div class="text-xs text-gray-500 dark:text-gray-400 mb-4">
													{$i18n.t('Connect to an AI provider to start chatting')}
												</div>
												<a
													href="/admin/settings/connections"
													class="px-4 py-1.5 rounded-xl text-xs font-medium bg-gray-900 dark:bg-white text-white dark:text-gray-900 hover:bg-gray-800 dark:hover:bg-gray-100 transition"
													on:click={() => {
														show = false;
													}}
												>
													{$i18n.t('Manage Connections')}
												</a>
											</div>
										{:else}
											<div class="">
												<div class="block px-3 py-2 text-sm text-gray-700 dark:text-gray-100">
													{$i18n.t('No results found')}
												</div>
											</div>
										{/if}
									{:else}
										<!-- svelte-ignore a11y-no-static-element-interactions -->
										<div
											class="max-h-64 overflow-y-auto"
											role="listbox"
											aria-label={$i18n.t('Available models')}
											bind:this={listContainer}
											on:scroll={() => {
												listScrollTop = listContainer.scrollTop;
											}}
										>
											<div style="height: {visibleStart * ITEM_HEIGHT}px;" />
											{#each filteredItems.slice(visibleStart, visibleEnd) as item, i (item.value)}
												{@const index = visibleStart + i}
												<ModelItem
													{selectedModelIdx}
													{item}
													{index}
													{value}
													{pinModelHandler}
													{setDefaultHandler}
													onClick={async () => {
														value = item.value;
														selectedModelIdx = index;
														show = false;

														// ── T3-932: per-session model override ──
														// Tell the agent container to use this model
														// for this chat session only. Does NOT write
														// to $settings or config.yaml (that lives in
														// Settings → Default model + "Set as default").
														if ($chatId && item.value && item.value !== 'myah') {
															try {
																const provider = item.model?.tags?.[0]?.name;
																await setChatSessionModel(
																	localStorage.token,
																	$chatId,
																	item.value,
																	provider
																);
															} catch (err) {
																console.error('[model-selector] setChatSessionModel failed', err);
																toast.error(
																	typeof err === 'string'
																		? err
																		: 'Could not switch model for this chat'
																);
															}
														}
													}}
												/>
											{/each}
											<div style="height: {(filteredItems.length - visibleEnd) * ITEM_HEIGHT}px;" />
										</div>
									{/if}
								</div>

								<div class="pb-2.5"></div>

								<div class="hidden w-[42rem]" />
								<div class="hidden w-[32rem]" />
							</slot>
						</div>
					</div>
				{/if}
			{/snippet}
		</DropdownMenu.Content>
	</DropdownMenu.Portal>
</DropdownMenu.Root>
