<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { onMount, tick, getContext } from 'svelte';
	import { openDB, deleteDB } from 'idb';
	import fileSaver from 'file-saver';
	const { saveAs } = fileSaver;

	import { browser } from '$app/environment';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { fade } from 'svelte/transition';

	import { getModelsWithProviders } from '$lib/apis';
	import { getAgentToolsets } from '$lib/apis/agent';
	import { getBanners } from '$lib/apis/configs';
	import { getUserSettings } from '$lib/apis/users';

	import { WEBUI_VERSION, WEBUI_API_BASE_URL } from '$lib/constants';

	import {
		config,
		user,
		settings,
		models,
		agentToolsets,
		tags,
		banners,
		showSettings,
		showShortcuts,
		showChangelog,
		temporaryChatEnabled,
		showSearch,
		showSidebar,
		artifactPaneOpen,
		mobile
	} from '$lib/stores';

	import Sidebar from '$lib/components/layout/Sidebar.svelte';
	import SettingsModal from '$lib/components/chat/SettingsModal.svelte';
	import ChangelogModal from '$lib/components/ChangelogModal.svelte';
	import AccountPending from '$lib/components/layout/Overlay/AccountPending.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import ProviderPicker from '$lib/components/Providers/ProviderPicker.svelte';
	import ReconnectBanner from '$lib/components/Providers/ReconnectBanner.svelte';
	import {
		refreshCatalog,
		refreshProviderStatus,
		providerStatusV2,
		connectedValidProvidersV2
	} from '$lib/stores/providers';
	import { getModelsUnified } from '$lib/apis/providers';
	import { Shortcut, shortcuts } from '$lib/shortcuts';

	const i18n = getContext('i18n');

	let loaded = false;

	// Show the provider onboarding picker when the store has been hydrated (non-null)
	// but no valid provider is connected. The reactive gate guards against the initial
	// null state so the picker never flashes before refreshProviderStatus() returns.
	$: showProviderSetup = $providerStatusV2 !== null && $connectedValidProvidersV2.length === 0;
	let DB = null;
	let localDBChats = [];

	// Enrich Sentry scope with the current user so feedback is attributed correctly.
	// Dynamic import keeps the SDK out of SSR and respects the PUBLIC_SENTRY_DSN gate.
	$: if (browser && $user) {
		import('@sentry/sveltekit').then((Sentry) => {
			Sentry.setUser({
				id: $user.id,
				email: $user.email,
				username: $user.name
			});
		});
	}

	// Clear Sentry user context on sign-out so the next session starts clean.
	$: if (browser && $user === null) {
		import('@sentry/sveltekit').then((Sentry) => Sentry.setUser(null));
	}

	const clearChatInputStorage = () => {
		const chatInputKeys = Object.keys(localStorage).filter((key) => key.startsWith('chat-input'));
		if (chatInputKeys.length > 0) {
			chatInputKeys.forEach((key) => {
				localStorage.removeItem(key);
			});
		}
	};

	const checkLocalDBChats = async () => {
		try {
			// Check if IndexedDB exists
			DB = await openDB('Chats', 1);

			if (!DB) {
				return;
			}

			const chats = await DB.getAllFromIndex('chats', 'timestamp');
			localDBChats = chats.map((item, idx) => chats[chats.length - 1 - idx]);

			if (localDBChats.length === 0) {
				await deleteDB('Chats');
			}
		} catch (error) {
			// IndexedDB Not Found
		}
	};

	const setUserSettings = async (cb: () => Promise<void>) => {
		let userSettings = await getUserSettings(localStorage.token).catch((error) => {
			console.error(error);
			return null;
		});

		if (!userSettings) {
			try {
				userSettings = JSON.parse(localStorage.getItem('settings') ?? '{}');
			} catch (e: unknown) {
				console.error('Failed to parse settings from localStorage', e);
				userSettings = {};
			}
		}

		if (userSettings?.ui) {
			settings.set(userSettings.ui);
		}

		if (cb) {
			await cb();
		}
	};

	const setModels = async () => {
		// Merge standard Open WebUI model routing (OpenAI/Ollama connections) with
		// the Hermes-native provider models from /api/v1/providers/models so the
		// picker shows all available models in one list.
		const legacy =
			(await getModelsWithProviders(
				localStorage.token,
				$config?.features?.enable_direct_connections ? ($settings?.directConnections ?? null) : null
			).catch(() => [])) ?? [];

		const unified = await getModelsUnified(localStorage.token).catch(() => []);

		const seen = new Set(legacy.map((m: any) => m.id));
		const merged = [...legacy];
		for (const m of unified) {
			if (!seen.has(m.id)) {
				merged.push(m);
				seen.add(m.id);
			}
		}
		models.set(merged);
	};

	const setBanners = async () => {
		const bannersData = await getBanners(localStorage.token);
		banners.set(bannersData);
	};

	const setTools = async () => {
		const data = await getAgentToolsets(localStorage.token);
		agentToolsets.set(data);
	};

	onMount(async () => {
		// $user starts as `undefined` while the root layout is still validating
		// the session asynchronously. Wait up to 10 seconds for it to resolve
		// before deciding whether to redirect. Only redirect on explicit null
		// (signed-out), never on undefined (still loading).
		if ($user === undefined) {
			await new Promise<void>((resolve) => {
				const unsub = user.subscribe((v) => {
					if (v !== undefined) {
						unsub();
						resolve();
					}
				});
				// Safety timeout — if still undefined after 10s, treat as unauthenticated
				setTimeout(() => {
					unsub();
					resolve();
				}, 10000);
			});
		}
		// T3-1001 dogfooding 2026-04-24: when SvelteKit's beforeNavigate guard
		// hard-reloads on version-update detection (root +layout.svelte:84),
		// the (app) layout can race ahead of the root layout's getSessionUser
		// call. The root layout will eventually resolve $user from the
		// existing localStorage.token; if we redirect to /auth on the first
		// transient null we lose the user's in-flight chat send. Only redirect
		// when there's no token AT ALL — token-but-null is a race we can wait
		// on, with one extra retry.
		if ($user === null && localStorage.token) {
			await new Promise<void>((resolve) => {
				const unsub = user.subscribe((v) => {
					if (v) {
						unsub();
						resolve();
					}
				});
				setTimeout(() => {
					unsub();
					resolve();
				}, 5000);
			});
		}
		if ($user === null) {
			await goto('/auth');
			return;
		}
		if (!['user', 'admin'].includes($user?.role)) {
			return;
		}

		// Hydrate the catalog + V2 provider status from /api/v1/providers/*.
		// The reactive $: showProviderSetup above will gate the onboarding picker
		// once providerStatusV2 is non-null and has no valid entries.
		await refreshCatalog(localStorage.token).catch(() => {});
		await refreshProviderStatus(localStorage.token).catch(() => null);

		clearChatInputStorage();
		await Promise.all([
			checkLocalDBChats(),
			setBanners().catch((e) => console.error('Failed to load banners:', e)),
			setTools().catch((e) => console.error('Failed to load tools:', e)),
			setUserSettings(async () => {
				await Promise.all([setModels().catch((e) => console.error('Failed to load models:', e))]);
			}).catch((e) => console.error('Failed to load user settings:', e))
		]);

		// Helper function to check if the pressed keys match the shortcut definition
		const isShortcutMatch = (event: KeyboardEvent, shortcut): boolean => {
			const keys = shortcut?.keys || [];

			const normalized = keys.map((k) => k.toLowerCase());
			const needCtrl = normalized.includes('ctrl') || normalized.includes('mod');
			const needShift = normalized.includes('shift');
			const needAlt = normalized.includes('alt');

			const mainKeys = normalized.filter((k) => !['ctrl', 'shift', 'alt', 'mod'].includes(k));

			// Get the main key pressed
			const keyPressed = event.key.toLowerCase();

			// Check modifiers
			if (needShift && !event.shiftKey) return false;

			if (needCtrl && !(event.ctrlKey || event.metaKey)) return false;
			if (!needCtrl && (event.ctrlKey || event.metaKey)) return false;
			if (needAlt && !event.altKey) return false;
			if (!needAlt && event.altKey) return false;

			if (mainKeys.length && !mainKeys.includes(keyPressed)) return false;

			return true;
		};

		const setupKeyboardShortcuts = () => {
			document.addEventListener('keydown', async (event) => {
				if (isShortcutMatch(event, shortcuts[Shortcut.SEARCH])) {
					console.log('Shortcut triggered: SEARCH');
					event.preventDefault();
					showSearch.set(!$showSearch);
				} else if (isShortcutMatch(event, shortcuts[Shortcut.NEW_CHAT])) {
					console.log('Shortcut triggered: NEW_CHAT');
					event.preventDefault();
					document.getElementById('sidebar-new-chat-button')?.click();
				} else if (isShortcutMatch(event, shortcuts[Shortcut.FOCUS_INPUT])) {
					console.log('Shortcut triggered: FOCUS_INPUT');
					event.preventDefault();
					document.getElementById('chat-input')?.focus();
				} else if (isShortcutMatch(event, shortcuts[Shortcut.COPY_LAST_CODE_BLOCK])) {
					console.log('Shortcut triggered: COPY_LAST_CODE_BLOCK');
					event.preventDefault();
					[...document.getElementsByClassName('copy-code-button')]?.at(-1)?.click();
				} else if (isShortcutMatch(event, shortcuts[Shortcut.COPY_LAST_RESPONSE])) {
					console.log('Shortcut triggered: COPY_LAST_RESPONSE');
					event.preventDefault();
					[...document.getElementsByClassName('copy-response-button')]?.at(-1)?.click();
				} else if (isShortcutMatch(event, shortcuts[Shortcut.TOGGLE_SIDEBAR])) {
					if ($mobile) {
						console.log('Shortcut triggered: TOGGLE_SIDEBAR');
						event.preventDefault();
						showSidebar.set(!$showSidebar);
					}
				} else if (isShortcutMatch(event, shortcuts[Shortcut.DELETE_CHAT])) {
					console.log('Shortcut triggered: DELETE_CHAT');
					event.preventDefault();
					document.getElementById('delete-chat-button')?.click();
				} else if (isShortcutMatch(event, shortcuts[Shortcut.OPEN_SETTINGS])) {
					console.log('Shortcut triggered: OPEN_SETTINGS');
					event.preventDefault();
					showSettings.set(!$showSettings);
				} else if (isShortcutMatch(event, shortcuts[Shortcut.SHOW_SHORTCUTS])) {
					console.log('Shortcut triggered: SHOW_SHORTCUTS');
					event.preventDefault();
					showShortcuts.set(!$showShortcuts);
				} else if (isShortcutMatch(event, shortcuts[Shortcut.CLOSE_MODAL])) {
					console.log('Shortcut triggered: CLOSE_MODAL');
					event.preventDefault();
					showSettings.set(false);
					showShortcuts.set(false);
				} else if (isShortcutMatch(event, shortcuts[Shortcut.OPEN_MODEL_SELECTOR])) {
					console.log('Shortcut triggered: OPEN_MODEL_SELECTOR');
					event.preventDefault();
					document.getElementById('model-selector-0-button')?.click();
				} else if (isShortcutMatch(event, shortcuts[Shortcut.NEW_TEMPORARY_CHAT])) {
					console.log('Shortcut triggered: NEW_TEMPORARY_CHAT');
					event.preventDefault();
					if ($user?.role !== 'admin' && $user?.permissions?.chat?.temporary_enforced) {
						temporaryChatEnabled.set(true);
					} else {
						temporaryChatEnabled.set(!$temporaryChatEnabled);
					}
					await goto('/');
					setTimeout(() => {
						document.getElementById('new-chat-button')?.click();
					}, 0);
				} else if (isShortcutMatch(event, shortcuts[Shortcut.GENERATE_MESSAGE_PAIR])) {
					console.log('Shortcut triggered: GENERATE_MESSAGE_PAIR');
					event.preventDefault();
					document.getElementById('generate-message-pair-button')?.click();
				}
			});
		};
		setupKeyboardShortcuts();

		if ($user?.role === 'admin' && ($settings?.showChangelog ?? true)) {
			showChangelog.set($settings?.version !== $config.version);
		}

		if ($user?.role === 'admin' || ($user?.permissions?.chat?.temporary ?? true)) {
			if ($page.url.searchParams.get('temporary-chat') === 'true') {
				temporaryChatEnabled.set(true);
			}

			if ($user?.role !== 'admin' && $user?.permissions?.chat?.temporary_enforced) {
				temporaryChatEnabled.set(true);
			}
		}

		// Persist artifact pane open state across reloads.
		// (artifactPaneSize will track the resized pixel width once the
		// PaneResizer wires up persistence.)
		await artifactPaneOpen.set(!$mobile ? localStorage.showArtifactPane === 'true' : false);
		artifactPaneOpen.subscribe((value) => {
			localStorage.showArtifactPane = value ? 'true' : 'false';
		});

		await tick();

		loaded = true;
	});

	// When the V2 provider-status store updates (user connected/disconnected a
	// provider via onboarding or Settings), re-fetch the models list so the
	// switcher reflects the new provider without requiring a page refresh.
	$: if ($providerStatusV2 && $providerStatusV2.length > 0) {
		void setModels().catch((e) =>
			console.error('[layout] setModels() after providerStatusV2 change failed:', e)
		);
	}
</script>

<SettingsModal bind:show={$showSettings} />
<ChangelogModal bind:show={$showChangelog} />

{#if $user}
	<div class="app relative app-authenticated">
		<div
			class="text-gray-700 dark:text-gray-100 bg-white dark:bg-gray-900 h-screen max-h-[100dvh] overflow-hidden flex flex-col"
		>
			<!-- Full-width top banner. Renders null when no providers need reconnecting. -->
			<ReconnectBanner />
			<div class="flex-1 min-h-0 overflow-auto flex flex-row">
				{#if !['user', 'admin'].includes($user?.role)}
					<AccountPending />
				{:else if showProviderSetup}
					<ProviderPicker
						mode="onboarding"
						onComplete={() => {
							showProviderSetup = false;
						}}
					/>
				{:else}
					{#if localDBChats.length > 0}
						<div class="fixed w-full h-full flex z-50">
							<div
								class="absolute w-full h-full backdrop-blur-md bg-white/20 dark:bg-gray-900/50 flex justify-center"
							>
								<div class="m-auto pb-44 flex flex-col justify-center">
									<div class="max-w-md">
										<div class="text-center dark:text-white text-2xl font-medium z-50">
											{$i18n.t('Important Update')}<br />
											{$i18n.t('Action Required for Chat Log Storage')}
										</div>

										<div class=" mt-4 text-center text-sm dark:text-gray-200 w-full">
											{$i18n.t(
												"Saving chat logs directly to your browser's storage is no longer supported. Please take a moment to download and delete your chat logs by clicking the button below. Don't worry, you can easily re-import your chat logs to the backend through"
											)}
											<span class="font-medium dark:text-white"
												>{$i18n.t('Settings')} > {$i18n.t('Chats')} > {$i18n.t(
													'Import Chats'
												)}</span
											>. {$i18n.t(
												'This ensures that your valuable conversations are securely saved to your backend database. Thank you!'
											)}
										</div>

										<div class=" mt-6 mx-auto relative group w-fit">
											<button
												class="relative z-20 flex px-5 py-2 rounded-full bg-white border border-gray-100 dark:border-none hover:bg-gray-100 transition font-medium text-sm"
												on:click={async () => {
													let blob = new Blob([JSON.stringify(localDBChats)], {
														type: 'application/json'
													});
													saveAs(blob, `chat-export-${Date.now()}.json`);

													const tx = DB.transaction('chats', 'readwrite');
													await Promise.all([tx.store.clear(), tx.done]);
													await deleteDB('Chats');

													localDBChats = [];
												}}
											>
												{$i18n.t('Download & Delete')}
											</button>

											<button
												class="text-xs text-center w-full mt-2 text-gray-400 underline"
												on:click={async () => {
													localDBChats = [];
												}}>{$i18n.t('Close')}</button
											>
										</div>
									</div>
								</div>
							</div>
						</div>
					{/if}

					<Sidebar />

					{#if loaded}
						<div class="flex-1 min-w-0 h-full {!$showSidebar && !$mobile ? 'pl-[52px]' : ''}">
							<slot />
						</div>
					{:else}
						<div
							class="flex-1 h-full flex items-center justify-center {!$showSidebar && !$mobile
								? 'pl-[52px]'
								: ''}"
						>
							<Spinner className="size-5" />
						</div>
					{/if}
				{/if}
			</div>
		</div>
	</div>
{/if}

<style>
	.loading {
		display: inline-block;
		clip-path: inset(0 1ch 0 0);
		animation: l 1s steps(3) infinite;
		letter-spacing: -0.5px;
	}

	@keyframes l {
		to {
			clip-path: inset(0 -1ch 0 0);
		}
	}

	pre[class*='language-'] {
		position: relative;
		overflow: auto;

		/* make space  */
		margin: 5px 0;
		padding: 1.75rem 0 1.75rem 1rem;
		border-radius: 10px;
	}

	pre[class*='language-'] button {
		position: absolute;
		top: 5px;
		right: 5px;

		font-size: 0.9rem;
		padding: 0.15rem;
		background-color: #828282;

		border: ridge 1px #7b7b7c;
		border-radius: 5px;
		text-shadow: #c4c4c4 0 0 2px;
	}

	pre[class*='language-'] button:hover {
		cursor: pointer;
		background-color: #bcbabb;
	}
</style>
