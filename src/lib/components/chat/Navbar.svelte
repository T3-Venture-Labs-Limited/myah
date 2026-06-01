<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	const dispatch = createEventDispatcher();
	import { toast } from 'svelte-sonner';

	import {
		MYAH_NAME,
		banners,
		chatId,
		config,
		mobile,
		settings,
		showArchivedChats,
		showSidebar,
		temporaryChatEnabled,
		user,
		artifactPaneOpen,
		artifactActiveTabIdx,
		closeArtifactPane
	} from '$lib/stores';

	import { slide } from 'svelte/transition';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';

	import ModelSelector from '../chat/ModelSelector.svelte';
	import Tooltip from '../common/Tooltip.svelte';
	import Menu from '$lib/components/layout/Navbar/Menu.svelte';
	import AdjustmentsHorizontal from '../icons/AdjustmentsHorizontal.svelte';
	import SchedulePopover from '$lib/components/tasks/SchedulePopover.svelte';
	import type { Process } from '$lib/apis/processes';

	import PencilSquare from '../icons/PencilSquare.svelte';
	import Banner from '../common/Banner.svelte';
	import Sidebar from '../icons/Sidebar.svelte';

	import ChatBubbleDotted from '../icons/ChatBubbleDotted.svelte';
	import ChatBubbleDottedChecked from '../icons/ChatBubbleDottedChecked.svelte';

	import EllipsisHorizontal from '../icons/EllipsisHorizontal.svelte';
	import ChatPlus from '../icons/ChatPlus.svelte';
	import ChatCheck from '../icons/ChatCheck.svelte';
	import Folder from '../icons/Folder.svelte';
	const i18n = getContext('i18n');

	export let initNewChat: Function;
	export let scrollTop = 0;

	export let chat;
	export let history;
	export let selectedModels;
	export let showModelSelector = false;

	export let onSaveTempChat: () => {};
	export let archiveChatHandler: (id: string) => void;
	export let deleteChatHandler: (id: string) => void;
	export let moveChatHandler: (id: string, folderId: string) => void;

	export let embedded = false;
	export let linkedProcess: Process | null = null;

	let closedBannerIds = [];
	let showDownloadChatModal = false;
	let showSchedulePopover = false;
</script>

<button
	id="new-chat-button"
	class="hidden"
	on:click={() => {
		initNewChat();
	}}
	aria-label="New Chat"
/>

<nav
	class="sticky top-0 z-30 w-full {chat?.id
		? 'pt-0.5 pb-1'
		: 'pt-1 pb-1'} -mb-12 flex flex-col items-center drag-region"
>
	<div class="flex items-center w-full pl-1.5 pr-1">
		<div
			id="navbar-bg-gradient-to-b"
			class="{chat?.id
				? 'visible'
				: 'invisible'} bg-linear-to-b via-40% to-97% from-white/90 via-white/50 to-transparent dark:from-gray-900/90 dark:via-gray-900/50 dark:to-transparent pointer-events-none absolute inset-0 -bottom-10 z-[-1]"
		></div>

		<div class=" flex max-w-full w-full mx-auto px-1.5 md:px-2 pt-0.5 bg-transparent">
			<div class="flex items-center w-full max-w-full">
				{#if $mobile && !$showSidebar}
					<button
						class="flex-shrink-0 mr-1 p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 transition text-gray-600 dark:text-gray-400"
						on:click={() => {
							showSidebar.set(!$showSidebar);
						}}
						aria-label={$showSidebar ? $i18n.t('Close Sidebar') : $i18n.t('Open Sidebar')}
					>
						<Sidebar className="size-4" />
					</button>
				{/if}

				{#if embedded}
					<button
						class="flex-shrink-0 p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 transition mr-1"
						on:click={() => dispatch('expand')}
						aria-label="Toggle task list"
					>
						<svg
							class="size-4"
							fill="none"
							viewBox="0 0 24 24"
							stroke="currentColor"
							stroke-width="1.5"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="M3.75 6.75h16.5M3.75 12h16.5M3.75 17.25h16.5"
							/>
						</svg>
					</button>
				{/if}

				<div
					class="flex-1 overflow-hidden max-w-full mt-0.5 py-0.5
			{$showSidebar ? 'ml-1' : ''}
			"
				>
					{#if showModelSelector}
						<ModelSelector bind:selectedModels />
					{/if}
				</div>

				<div class="self-start flex flex-none items-center text-gray-600 dark:text-gray-400">
					<!-- <div class="md:hidden flex self-center w-[1px] h-5 mx-2 bg-gray-300 dark:bg-stone-700" /> -->

					{#if $user?.role === 'user' ? ($user?.permissions?.chat?.temporary ?? true) && !($user?.permissions?.chat?.temporary_enforced ?? false) : true}
						{#if !chat?.id}
							<Tooltip content={$i18n.t(`Temporary Chat`)}>
								<button
									class="flex cursor-pointer px-2 py-2 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-850 transition"
									id="temporary-chat-button"
									on:click={async () => {
										if (($settings?.temporaryChatByDefault ?? false) && $temporaryChatEnabled) {
											// for proper initNewChat handling
											await temporaryChatEnabled.set(null);
										} else {
											await temporaryChatEnabled.set(!$temporaryChatEnabled);
										}

										if ($page.url.pathname !== '/') {
											await goto('/');
										}

										// add 'temporary-chat=true' to the URL
										if ($temporaryChatEnabled) {
											window.history.replaceState(null, '', '?temporary-chat=true');
										} else {
											window.history.replaceState(null, '', location.pathname);
										}
									}}
								>
									<div class=" m-auto self-center">
										{#if $temporaryChatEnabled}
											<ChatBubbleDottedChecked className=" size-4.5" strokeWidth="1.5" />
										{:else}
											<ChatBubbleDotted className=" size-4.5" strokeWidth="1.5" />
										{/if}
									</div>
								</button>
							</Tooltip>
						{:else if $temporaryChatEnabled}
							<Tooltip content={$i18n.t(`Save Chat`)}>
								<button
									class="flex cursor-pointer px-2 py-2 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-850 transition"
									id="save-temporary-chat-button"
									on:click={async () => {
										onSaveTempChat();
									}}
								>
									<div class=" m-auto self-center">
										<ChatCheck className=" size-4.5" strokeWidth="1.5" />
									</div>
								</button>
							</Tooltip>
						{/if}
					{/if}

					{#if $mobile && !$temporaryChatEnabled && chat && chat.id}
						<Tooltip content={$i18n.t('New Chat')}>
							<button
								class=" flex {$showSidebar
									? 'md:hidden'
									: ''} cursor-pointer px-2 py-2 rounded-xl text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-850 transition"
								on:click={() => {
									initNewChat();
								}}
								aria-label="New Chat"
							>
								<div class=" m-auto self-center">
									<ChatPlus className=" size-4.5" strokeWidth="1.5" />
								</div>
							</button>
						</Tooltip>
					{/if}

					{#if chat && (chat.id || $temporaryChatEnabled)}
						<Menu
							{chat}
							archiveChatHandler={() => {
								archiveChatHandler(chat.id);
							}}
							deleteChatHandler={() => {
								deleteChatHandler(chat.id);
							}}
							{moveChatHandler}
						>
							<button
								class="flex cursor-pointer px-2 py-2 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-850 transition"
								id="chat-context-menu-button"
							>
								<div class=" m-auto self-center">
									<EllipsisHorizontal className=" size-5" strokeWidth="1.5" />
								</div>
							</button>
						</Menu>
					{/if}

					<Tooltip content={$i18n.t('Files')}>
						<button
							class=" flex cursor-pointer px-2 py-2 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-850 transition {$artifactPaneOpen
								? 'bg-gray-100 dark:bg-gray-800'
								: ''}"
							data-testid="chat-files-button"
							aria-pressed={$artifactPaneOpen}
							on:click={() => {
								// Toggle: if pane is closed, open into the explorer view.
								// If already open, close it (closeArtifactPane clears active idx + selection).
								if ($artifactPaneOpen) {
									closeArtifactPane();
								} else {
									artifactPaneOpen.set(true);
									artifactActiveTabIdx.set(-1);
								}
							}}
							aria-label="Files"
						>
							<div class=" m-auto self-center">
								<Folder className=" size-5" strokeWidth="1.5" />
							</div>
						</button>
					</Tooltip>

					{#if embedded && linkedProcess}
						<div class="relative flex-shrink-0 ml-1">
							<button
								class="px-3 py-1.5 text-xs rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-850 transition text-gray-700 dark:text-gray-300"
								on:click={() => (showSchedulePopover = !showSchedulePopover)}
							>
								Schedule
							</button>
							<SchedulePopover process={linkedProcess} bind:show={showSchedulePopover} />
						</div>
					{/if}

					{#if embedded}
						<button
							class="flex-shrink-0 p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 transition ml-1"
							on:click={() => dispatch('expand')}
							aria-label="Toggle full width"
						>
							<svg
								class="size-4"
								fill="none"
								viewBox="0 0 24 24"
								stroke="currentColor"
								stroke-width="1.5"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15"
								/>
							</svg>
						</button>
					{/if}
				</div>
			</div>
		</div>
	</div>

	{#if $temporaryChatEnabled && ($chatId ?? '').startsWith('local:')}
		<div class=" w-full z-30 text-center">
			<div class="text-xs text-gray-500">{$i18n.t('Temporary Chat')}</div>
		</div>
	{/if}

	<div class="absolute top-[100%] left-0 right-0 h-fit">
		{#if history && !history.currentId && !$chatId && ($banners.length > 0 || ($config?.license_metadata?.type ?? null) === 'trial' || (($config?.license_metadata?.seats ?? null) !== null && $config?.user_count > $config?.license_metadata?.seats))}
			<div class=" w-full z-30">
				<div class=" flex flex-col gap-1 w-full">
					{#if ($config?.license_metadata?.type ?? null) === 'trial'}
						<Banner
							banner={{
								type: 'info',
								title: 'Trial License',
								content: $i18n.t(
									'You are currently using a trial license. Please contact support to upgrade your license.'
								)
							}}
						/>
					{/if}

					{#if ($config?.license_metadata?.seats ?? null) !== null && $config?.user_count > $config?.license_metadata?.seats}
						<Banner
							banner={{
								type: 'error',
								title: 'License Error',
								content: $i18n.t(
									'Exceeded the number of seats in your license. Please contact support to increase the number of seats.'
								)
							}}
						/>
					{/if}

					{#each $banners.filter((b) => ![...JSON.parse(localStorage.getItem('dismissedBannerIds') ?? '[]'), ...closedBannerIds].includes(b.id)) as banner (banner.id)}
						<Banner
							{banner}
							on:dismiss={(e) => {
								const bannerId = e.detail;

								if (banner.dismissible) {
									localStorage.setItem(
										'dismissedBannerIds',
										JSON.stringify(
											[
												bannerId,
												...JSON.parse(localStorage.getItem('dismissedBannerIds') ?? '[]')
											].filter((id) => $banners.find((b) => b.id === id))
										)
									);
								} else {
									closedBannerIds = [...closedBannerIds, bannerId];
								}
							}}
						/>
					{/each}
				</div>
			</div>
		{/if}
	</div>
</nav>
