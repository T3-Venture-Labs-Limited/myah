<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import {
		user,
		chatId,
		showSidebar,
		showSearch,
		mobile,
		showArchivedChats,
		config,
		isApp,
		MYAH_NAME,
		temporaryChatEnabled,
		selectedFolder
	} from '$lib/stores';
	import { onMount, getContext, tick } from 'svelte';

	const i18n = getContext('i18n');

	import { MYAH_API_BASE_URL } from '$lib/constants';

	import ArchivedChatsModal from './ArchivedChatsModal.svelte';
	import UserMenu from './Sidebar/UserMenu.svelte';
	import Tooltip from '../common/Tooltip.svelte';
	import PencilSquare from '../icons/PencilSquare.svelte';
	import Search from '../icons/Search.svelte';
	import SearchModal from './SearchModal.svelte';
	import Sidebar from '../icons/Sidebar.svelte';
	import Note from '../icons/Note.svelte';
	import Tasks from '../icons/Tasks.svelte';
	import Spaces from '../icons/Spaces.svelte';
	import AgentIcon from '../icons/AgentIcon.svelte';
	import SentryFeedbackButton from '../SentryFeedbackButton.svelte';
	import SidebarHostedNav from './SidebarHostedNav.svelte';

	let touchstart: Touch | null = null;
	let touchend: Touch | null = null;

	function checkDirection() {
		if (!touchstart || !touchend) return;
		const screenWidth = window.innerWidth;
		const swipeDistance = Math.abs(touchend.screenX - touchstart.screenX);
		if (touchstart.clientX < 40 && swipeDistance >= screenWidth / 8) {
			if (touchend.screenX < touchstart.screenX) {
				showSidebar.set(false);
			}
			if (touchend.screenX > touchstart.screenX) {
				showSidebar.set(true);
			}
		}
	}

	const onTouchStart = (e: TouchEvent) => {
		touchstart = e.changedTouches[0];
	};

	const onTouchEnd = (e: TouchEvent) => {
		touchend = e.changedTouches[0];
		checkDirection();
	};

	onMount(() => {
		showSidebar.set($mobile ? (localStorage.sidebar === 'true') : false);

		const unsubscribers = [
			mobile.subscribe((value) => {
				if ($showSidebar && value) {
					showSidebar.set(false);
				}

				if ($showSidebar && !value) {
					const navElement = document.getElementsByTagName('nav')[0];
					if (navElement) {
						navElement.style['-webkit-app-region'] = 'drag';
					}
				}
			}),
			showSidebar.subscribe(async (value) => {
				localStorage.sidebar = value;

				const navElement = document.getElementsByTagName('nav')[0];

				if (navElement) {
					if ($mobile) {
						if (!value) {
							navElement.style['-webkit-app-region'] = 'drag';
						} else {
							navElement.style['-webkit-app-region'] = 'no-drag';
						}
					} else {
						navElement.style['-webkit-app-region'] = 'drag';
					}
				}
			})
		];

		window.addEventListener('touchstart', onTouchStart);
		window.addEventListener('touchend', onTouchEnd);

		return () => {
			unsubscribers.forEach((unsubscriber) => unsubscriber());

			window.removeEventListener('touchstart', onTouchStart);
			window.removeEventListener('touchend', onTouchEnd);
		};
	});

	const newTaskHandler = async () => {
		selectedFolder.set(null);

		if ($user?.role !== 'admin' && $user?.permissions?.chat?.temporary_enforced) {
			await temporaryChatEnabled.set(true);
		} else {
			await temporaryChatEnabled.set(false);
		}

		setTimeout(() => {
			if ($mobile) {
				showSidebar.set(false);
			}
		}, 0);
	};

	const itemClickHandler = async () => {
		chatId.set('');

		if ($mobile) {
			showSidebar.set(false);
		}

		await tick();
	};
</script>

<ArchivedChatsModal
	bind:show={$showArchivedChats}
	onDelete={(id) => {
		if ($chatId === id) {
			goto('/');
			chatId.set('');
		}
	}}
/>

<!-- svelte-ignore a11y-no-static-element-interactions -->

{#if $showSidebar}
	<div
		class=" {$isApp
			? ' ml-[4.5rem] md:ml-0'
			: ''} fixed md:hidden z-40 top-0 right-0 left-0 bottom-0 bg-black/60 w-full min-h-screen h-screen flex justify-center overflow-hidden overscroll-contain"
		on:mousedown={() => {
			showSidebar.set(!$showSidebar);
		}}
	/>
{/if}

<SearchModal
	bind:show={$showSearch}
	onClose={() => {
		if ($mobile) {
			showSidebar.set(false);
		}
	}}
/>

<button
	id="sidebar-new-chat-button"
	class="hidden"
	on:click={() => {
		goto('/');
		newTaskHandler();
	}}
/>

<!-- Collapsed sidebar: navigation icons only -->
{#if !$mobile}
	<div
		class="fixed start-0 top-0 bottom-0 z-50 flex flex-col justify-between bg-gray-50 dark:bg-gray-950 py-2 px-1 transition-transform duration-200"
	>
		<div class="flex flex-col items-center gap-0.5">
			<!-- Logo -->
			<div class="flex rounded-xl p-1">
				<div class="self-center flex items-center justify-center size-9">
					<img
						crossorigin="anonymous"
						src="/static/favicon.png"
						class="size-6 rounded-full"
						alt="logo"
					/>
				</div>
			</div>

			<!-- New Task -->
			<Tooltip content={$i18n.t('New Task')} placement="right">
				<a
					class="cursor-pointer flex rounded-xl hover:bg-gray-100 dark:hover:bg-gray-850 transition group"
					href="/"
					draggable="false"
					on:click={async (e) => {
						e.stopImmediatePropagation();
						e.preventDefault();
						goto('/');
						newTaskHandler();
					}}
					aria-label={$i18n.t('New Task')}
				>
					<div class="self-center flex items-center justify-center size-9">
						<PencilSquare className="size-4.5" />
					</div>
				</a>
			</Tooltip>

			<!-- Tasks -->
			<Tooltip content={$i18n.t('Tasks')} placement="right">
				<a
					class="cursor-pointer flex rounded-xl transition group {$page?.url?.pathname?.startsWith(
						'/c'
					)
						? 'bg-gray-100 dark:bg-gray-850'
						: 'hover:bg-gray-100 dark:hover:bg-gray-850'}"
					href="/c"
					on:click={async (e) => {
						e.stopImmediatePropagation();
						e.preventDefault();
						goto('/c');
						itemClickHandler();
					}}
					draggable="false"
					aria-label={$i18n.t('Tasks')}
				>
					<div class="self-center flex items-center justify-center size-9">
						<Tasks className="size-4.5" />
					</div>
				</a>
			</Tooltip>

			<!-- Spaces -->
			<Tooltip content={$i18n.t('Spaces')} placement="right">
				<a
					class="cursor-pointer flex rounded-xl transition group {$page?.url?.pathname?.startsWith(
						'/spaces'
					)
						? 'bg-gray-100 dark:bg-gray-850'
						: 'hover:bg-gray-100 dark:hover:bg-gray-850'}"
					href="/spaces"
					on:click={async (e) => {
						e.stopImmediatePropagation();
						e.preventDefault();
						goto('/spaces');
						itemClickHandler();
					}}
					draggable="false"
					aria-label={$i18n.t('Spaces')}
				>
					<div class="self-center flex items-center justify-center size-9">
						<Spaces className="size-4.5" />
					</div>
				</a>
			</Tooltip>

			<SidebarHostedNav variant="collapsed" />

			<!-- Notes (feature-flagged) -->
			{#if ($config?.features?.enable_notes ?? false) && ($user?.role === 'admin' || ($user?.permissions?.features?.notes ?? true))}
				<Tooltip content={$i18n.t('Notes')} placement="right">
					<a
						class="cursor-pointer flex rounded-xl hover:bg-gray-100 dark:hover:bg-gray-850 transition group"
						href="/notes"
						on:click={async (e) => {
							e.stopImmediatePropagation();
							e.preventDefault();
							goto('/notes');
							itemClickHandler();
						}}
						draggable="false"
						aria-label={$i18n.t('Notes')}
					>
						<div class="self-center flex items-center justify-center size-9">
							<Note className="size-4.5" />
						</div>
					</a>
				</Tooltip>
			{/if}

			<!-- Agent -->
			<Tooltip content={$i18n.t('Agent')} placement="right">
				<a
					class="cursor-pointer flex rounded-xl transition group {$page?.url?.pathname?.startsWith(
						'/agent'
					)
						? 'bg-gray-100 dark:bg-gray-850'
						: 'hover:bg-gray-100 dark:hover:bg-gray-850'}"
					href="/agent"
					on:click={async (e) => {
						e.stopImmediatePropagation();
						e.preventDefault();
						goto('/agent');
						itemClickHandler();
					}}
					draggable="false"
					aria-label={$i18n.t('Agent')}
				>
					<div class="self-center flex items-center justify-center size-9">
						<AgentIcon className="size-4.5" />
					</div>
				</a>
			</Tooltip>

			<!-- Search -->
			<Tooltip content={$i18n.t('Search')} placement="right">
				<button
					class="cursor-pointer flex rounded-xl hover:bg-gray-100 dark:hover:bg-gray-850 transition group"
					on:click={(e) => {
						e.stopImmediatePropagation();
						e.preventDefault();
						showSearch.set(true);
					}}
					draggable="false"
					aria-label={$i18n.t('Search')}
				>
					<div class="self-center flex items-center justify-center size-9">
						<Search className="size-4.5" />
					</div>
				</button>
			</Tooltip>
		</div>

		<div class="flex flex-col items-center">
			<Tooltip content={$i18n.t('Report a bug')} placement="right">
				<SentryFeedbackButton variant="collapsed" />
			</Tooltip>
			<UserMenu
				className="w-56"
				role={$user?.role}
				help={true}
				side="top"
				align="start"
				on:show={(e) => {
					if (e.detail === 'archived-chat') {
						showArchivedChats.set(true);
					}
				}}
			>
				<button
					type="button"
					class="select-none cursor-pointer flex items-center justify-center rounded-xl size-9 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
					aria-label={$i18n.t('Profile')}
				>
					<img
						src={`${MYAH_API_BASE_URL}/users/${$user?.id}/profile/image`}
						class="size-6 object-cover rounded-full"
						alt=""
						draggable="false"
					/>
				</button>
			</UserMenu>
		</div>
	</div>
{/if}

{#if $showSidebar && $mobile}
	<div
		class="h-screen max-h-[100dvh] min-h-screen select-none md:relative bg-gray-50 text-gray-900 dark:bg-gray-950 dark:text-gray-200 text-sm transition fixed z-50 top-0 left-0 overflow-x-hidden flex-shrink-0"
		style="width: 260px"
	>
		<div class="py-2 flex flex-col h-full">
			<!-- Header -->
			<div class="px-2.5 flex justify-between items-center mb-1">
				<div class="flex items-center gap-1">
					<img
						crossorigin="anonymous"
						src="/static/favicon.png"
						class="size-6 rounded-full"
						alt="logo"
					/>
					<span class="text-base font-semibold font-primary">{$MYAH_NAME}</span>
				</div>
				<button
					class="cursor-pointer p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850"
					on:click={() => showSidebar.set(false)}
				>
					<Sidebar className="size-4" />
				</button>
			</div>

			<!-- Navigation items -->
			<div class="flex flex-col gap-0.5 px-[0.4375rem]">
				<!-- New Task -->
				<div class="flex justify-center text-gray-800 dark:text-gray-200">
					<a
						id="sidebar-new-task-button"
						class="group grow flex items-center space-x-3 rounded-2xl px-2.5 py-2 hover:bg-gray-100 dark:hover:bg-gray-900 transition outline-none"
						href="/"
						draggable="false"
						on:click={newTaskHandler}
						aria-label={$i18n.t('New Task')}
					>
						<div class="self-center">
							<PencilSquare className="size-4.5" strokeWidth="2" />
						</div>
						<div class="flex flex-1 self-center translate-y-[0.5px]">
							<div class="self-center text-sm font-primary">{$i18n.t('New Task')}</div>
						</div>
					</a>
				</div>

				<!-- Tasks -->
				<div class="flex justify-center text-gray-800 dark:text-gray-200">
					<a
						id="sidebar-tasks-button"
						class="grow flex items-center space-x-3 rounded-2xl px-2.5 py-2 transition {$page?.url?.pathname?.startsWith(
							'/c'
						)
							? 'bg-gray-100 dark:bg-gray-900 font-semibold'
							: 'hover:bg-gray-100 dark:hover:bg-gray-900'}"
						href="/c"
						on:click={itemClickHandler}
						draggable="false"
						aria-label={$i18n.t('Tasks')}
					>
						<div class="self-center">
							<Tasks className="size-4.5" strokeWidth="2" />
						</div>
						<div class="flex self-center translate-y-[0.5px]">
							<div class="self-center text-sm font-primary">{$i18n.t('Tasks')}</div>
						</div>
					</a>
				</div>

				<!-- Spaces -->
				<div class="flex justify-center text-gray-800 dark:text-gray-200">
					<a
						id="sidebar-spaces-button"
						class="grow flex items-center space-x-3 rounded-2xl px-2.5 py-2 transition {$page?.url?.pathname?.startsWith(
							'/spaces'
						)
							? 'bg-gray-100 dark:bg-gray-900 font-semibold'
							: 'hover:bg-gray-100 dark:hover:bg-gray-900'}"
						href="/spaces"
						on:click={itemClickHandler}
						draggable="false"
						aria-label={$i18n.t('Spaces')}
					>
						<div class="self-center">
							<Spaces className="size-4.5" strokeWidth="2" />
						</div>
						<div class="flex self-center translate-y-[0.5px]">
							<div class="self-center text-sm font-primary">{$i18n.t('Spaces')}</div>
						</div>
					</a>
				</div>

				<SidebarHostedNav variant="expanded" />

				<!-- Notes (feature-flagged) -->
				{#if ($config?.features?.enable_notes ?? false) && ($user?.role === 'admin' || ($user?.permissions?.features?.notes ?? true))}
					<div class="flex justify-center text-gray-800 dark:text-gray-200">
						<a
							id="sidebar-notes-button"
							class="grow flex items-center space-x-3 rounded-2xl px-2.5 py-2 hover:bg-gray-100 dark:hover:bg-gray-900 transition"
							href="/notes"
							on:click={itemClickHandler}
							draggable="false"
							aria-label={$i18n.t('Notes')}
						>
							<div class="self-center">
								<Note className="size-4.5" strokeWidth="2" />
							</div>
							<div class="flex self-center translate-y-[0.5px]">
								<div class="self-center text-sm font-primary">{$i18n.t('Notes')}</div>
							</div>
						</a>
					</div>
				{/if}

				<!-- Agent -->
				<div class="flex justify-center text-gray-800 dark:text-gray-200">
					<a
						id="sidebar-agent-button"
						class="grow flex items-center space-x-3 rounded-2xl px-2.5 py-2 transition {$page?.url?.pathname?.startsWith(
							'/agent'
						)
							? 'bg-gray-100 dark:bg-gray-900 font-semibold'
							: 'hover:bg-gray-100 dark:hover:bg-gray-900'}"
						href="/agent"
						on:click={itemClickHandler}
						draggable="false"
						aria-label={$i18n.t('Agent')}
					>
						<div class="self-center">
							<AgentIcon className="size-4.5" strokeWidth="2" />
						</div>
						<div class="flex self-center translate-y-[0.5px]">
							<div class="self-center text-sm font-primary">{$i18n.t('Agent')}</div>
						</div>
					</a>
				</div>

				<!-- Search -->
				<div class="flex justify-center text-gray-800 dark:text-gray-200">
					<button
						id="sidebar-search-button"
						class="group grow flex items-center space-x-3 rounded-2xl px-2.5 py-2 hover:bg-gray-100 dark:hover:bg-gray-900 transition outline-none"
						on:click={() => showSearch.set(true)}
						draggable="false"
						aria-label={$i18n.t('Search')}
					>
						<div class="self-center">
							<Search strokeWidth="2" className="size-4.5" />
						</div>
						<div class="flex flex-1 self-center translate-y-[0.5px]">
							<div class="self-center text-sm font-primary">{$i18n.t('Search')}</div>
						</div>
					</button>
				</div>
			</div>

			<div class="flex-1" />

			<div class="px-[0.4375rem]">
				<SentryFeedbackButton variant="expanded" />
			</div>

			<div class="px-[0.4375rem] pb-1">
				<UserMenu
					role={$user?.role}
					help={true}
					on:show={(e) => {
						if (e.detail === 'archived-chat') {
							showArchivedChats.set(true);
						}
					}}
				>
					<button
						type="button"
						class="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-2xl hover:bg-gray-100 dark:hover:bg-gray-900 transition"
						aria-label={$i18n.t('Profile')}
					>
						<img
							src={`${MYAH_API_BASE_URL}/users/${$user?.id}/profile/image`}
							class="size-6 object-cover rounded-full flex-shrink-0"
							alt=""
							draggable="false"
						/>
						<span class="text-sm font-primary text-gray-800 dark:text-gray-200 truncate">
							{$user?.name}
						</span>
					</button>
				</UserMenu>
			</div>
		</div>
	</div>
{/if}
