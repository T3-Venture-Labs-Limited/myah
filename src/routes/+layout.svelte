<script>
	import { io } from 'socket.io-client';
	import { spring } from 'svelte/motion';
	import { Toaster, toast } from 'svelte-sonner';

	let loadingProgress = spring(0, {
		stiffness: 0.05
	});

	import { onMount, tick, setContext, onDestroy } from 'svelte';
	import { env } from '$env/dynamic/public';
	import {
		config,
		user,
		settings,
		theme,
		MYAH_NAME,
		MYAH_VERSION,
		MYAH_DEPLOYMENT_ID,
		mobile,
		socket,
		chatId,
		chats,
		currentChatPage,
		temporaryChatEnabled,
		isLastActiveTab,
		isApp,
		appInfo,
		playingNotificationSound,
		defaultModel,
		models,
		activeChatIds
	} from '$lib/stores';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { beforeNavigate } from '$app/navigation';
	import { updated } from '$app/state';

	// OSS first-run UX (Workstream C). When MYAH_DEPLOYMENT_MODE=oss the
	// frontend probes the host-side hermes on every page load and gates
	// the entire app shell on the result. In hosted mode this whole block
	// is a no-op (isOss=false), preserving the existing flow.
	//
	// NOTE: this file uses <script> (plain JS), not <script lang="ts">,
	// so we cannot use TypeScript type annotations or `import type`.
	// The OssProbe TypeScript type still exists in `$lib/apis/oss` for
	// callers that DO use lang="ts" (Welcome.svelte etc.); here we just
	// pass the runtime value through.
	import { getOssProbe, markFirstRunComplete } from '$lib/apis/oss';
	import Welcome from '$lib/components/oss/Welcome.svelte';
	import HermesDownError from '$lib/components/oss/HermesDownError.svelte';
	import PluginMissingError from '$lib/components/oss/PluginMissingError.svelte';

	const isOss = env.PUBLIC_DEPLOYMENT_MODE === 'oss';

	let ossProbe = null;
	let ossProbeLoaded = false; // becomes true after first probe attempt
	let ossProbeError = null;

	async function runOssProbe() {
		ossProbeError = null;
		try {
			ossProbe = await getOssProbe();
		} catch (err) {
			// Backend itself is unreachable — surface as a hermes-down
			// blocking error since that's the closest signal we have.
			ossProbeError = typeof err === 'string' ? err : 'Probe failed.';
			ossProbe = null;
		} finally {
			ossProbeLoaded = true;
		}
	}

	async function handleWelcomeContinue() {
		// VM-testing F3 fix happens here too: if the user clicks Continue,
		// we flip first_run regardless of providers_configured.
		try {
			await markFirstRunComplete();
		} catch (err) {
			console.error('first_run_complete failed:', err);
			// Non-fatal: re-render Welcome on the next page load. The
			// frontend will route to chat once the flag is persisted.
		}
		await runOssProbe(); // refresh state -> first_run now false -> chat
	}

	// Auto-skip-to-chat when first_run=true AND at least one provider is
	// already configured. Implements F3 from vm-testing-followups.md.
	$: if (
		isOss &&
		ossProbe &&
		ossProbe.hermes_reachable &&
		ossProbe.plugin_installed &&
		ossProbe.first_run &&
		ossProbe.providers_configured.length > 0
	) {
		// Don't block on this — fire-and-forget; if it fails the user
		// just sees Welcome on the next load.
		void handleWelcomeContinue();
	}

	import i18n, { initI18n, getLanguages, changeLanguage } from '$lib/i18n';

	import '../tailwind.css';
	import '../app.css';
	import 'tippy.js/dist/tippy.css';

	import { getBackendConfig, getModelsWithProviders, getVersion } from '$lib/apis';
	import { getSessionUser, userSignOut } from '$lib/apis/auths';
	import { getChatList } from '$lib/apis/chats';
	import { chatCompletion } from '$lib/apis/openai';
	import { addOpenAIConnection, removeOpenAIConnection } from '$lib/utils/connections';

	import { MYAH_API_BASE_URL, MYAH_BASE_URL, MYAH_HOSTNAME } from '$lib/constants';
	import { bestMatchingLanguage } from '$lib/utils';
	import { setTextScale } from '$lib/utils/text-scale';

	import NotificationToast from '$lib/components/NotificationToast.svelte';
	import AppSidebar from '$lib/components/app/AppSidebar.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import { getUserSettings } from '$lib/apis/users';
	import dayjs from 'dayjs';
	const unregisterServiceWorkers = async () => {
		if ('serviceWorker' in navigator) {
			try {
				const registrations = await navigator.serviceWorker.getRegistrations();
				await Promise.all(registrations.map((r) => r.unregister()));
				return true;
			} catch (error) {
				console.error('Error unregistering service workers:', error);
				return false;
			}
		}
		return false;
	};

	// handle frontend updates (https://svelte.dev/docs/kit/configuration#version)
	//
	// T3-1001 dogfooding 2026-04-24: Previous behaviour hard-reloaded via
	// `location.href = to.url.href` whenever `updated.current` was true AND
	// the user was navigating somewhere other than /auth. In dev (and in
	// production if SvelteKit's version poll picks up a new app revision
	// during a chat session) this fires on every in-chat URL change — most
	// notably the `/` → `/c/<id>` hop after a first message send — which
	// tears down the in-memory user store and races the (app) layout's
	// $user check into a spurious goto('/auth'), logging the user out
	// mid-send.
	//
	// The existing socket-reconnect path (line ~131) already shows a
	// non-disruptive refresh banner instead of force-reloading; do the same
	// here. A genuine stale-bundle problem will still surface on the next
	// full reload the user initiates, and the refresh banner tells them
	// exactly when to do that.
	beforeNavigate(async ({ willUnload, to }) => {
		if (updated.current && !willUnload && to?.url) {
			if (to.url.pathname === '/auth') return;
			showRefresh = true;
		}
	});

	setContext('i18n', i18n);

	const bc = new BroadcastChannel('active-tab-channel');

	let loaded = false;
	let tokenTimer = null;

	let showRefresh = false;

	let heartbeatInterval = null;

	const BREAKPOINT = 768;

	const setupSocket = async (enableWebsocket) => {
		const _socket = io(`${MYAH_BASE_URL}` || undefined, {
			reconnection: true,
			reconnectionDelay: 1000,
			reconnectionDelayMax: 5000,
			randomizationFactor: 0.5,
			path: '/ws/socket.io',
			transports: enableWebsocket ? ['polling', 'websocket'] : ['polling'],
			auth: { token: localStorage.token }
		});
		await socket.set(_socket);

		_socket.on('connect_error', (err) => {
			console.log('connect_error', err);
		});

		_socket.on('connect', async () => {
			console.log('connected', _socket.id);
			const res = await getVersion(localStorage.token);

			const deploymentId = res?.deployment_id ?? null;
			const version = res?.version ?? null;

			if (version !== null || deploymentId !== null) {
				if (
					($MYAH_VERSION !== null && version !== $MYAH_VERSION) ||
					($MYAH_DEPLOYMENT_ID !== null && deploymentId !== $MYAH_DEPLOYMENT_ID)
				) {
					// Show a non-disruptive refresh banner instead of force-reloading.
					// A force-reload here (on every socket reconnect) compounded with
					// SvelteKit's version polling to cause repeated logouts (T3-855).
					showRefresh = true;
				}
			}

			// Clear any existing heartbeat before starting a new one — the connect
			// event fires on every reconnect and without this we accumulate multiple
			// concurrent heartbeat intervals (T3-872).
			if (heartbeatInterval) {
				clearInterval(heartbeatInterval);
				heartbeatInterval = null;
			}

			// Send heartbeat every 30 seconds
			heartbeatInterval = setInterval(() => {
				if (_socket.connected) {
					console.log('Sending heartbeat');
					_socket.emit('heartbeat', {});
				}
			}, 30000);

			if (deploymentId !== null) {
				MYAH_DEPLOYMENT_ID.set(deploymentId);
			}

			if (version !== null) {
				MYAH_VERSION.set(version);
			}

			console.log('version', version);

			// Emit user-join. If the token isn't in localStorage yet (race between
			// socket connect and token being set after login), wait up to 3 seconds
			// for it to appear before giving up (T3-872).
			if (localStorage.getItem('token')) {
				_socket.emit('user-join', { auth: { token: localStorage.token } });
			} else {
				const waited = await new Promise<string | null>((resolve) => {
					let elapsed = 0;
					const interval = setInterval(() => {
						const token = localStorage.getItem('token');
						if (token) {
							clearInterval(interval);
							resolve(token);
						} else {
							elapsed += 100;
							if (elapsed >= 3000) {
								clearInterval(interval);
								resolve(null);
							}
						}
					}, 100);
				});
				if (waited) {
					_socket.emit('user-join', { auth: { token: waited } });
				} else {
					console.warn('No token found in localStorage after waiting, user-join not emitted');
				}
			}
		});

		_socket.on('reconnect_attempt', (attempt) => {
			console.log('reconnect_attempt', attempt);
		});

		_socket.on('reconnect_failed', () => {
			console.log('reconnect_failed');
		});

		_socket.on('disconnect', (reason, details) => {
			console.log(`Socket ${_socket.id} disconnected due to ${reason}`);

			if (heartbeatInterval) {
				clearInterval(heartbeatInterval);
				heartbeatInterval = null;
			}

			if (details) {
				console.log('Additional details:', details);
			}
		});
	};

	const chatEventHandler = async (event, cb) => {
		const chat = $page.url.pathname.includes(`/c/${event.chat_id}`);

		// Skip events from temporary chats that are not the current chat.
		// This prevents notifications from being sent to other tabs/devices
		// for privacy, since temporary chats are not meant to be persisted or visible elsewhere.
		const isTemporaryChat = event.chat_id?.startsWith('local:');
		if (isTemporaryChat && event.chat_id !== $chatId) {
			return;
		}

		let isFocused = document.visibilityState !== 'visible';
		if (window.electronAPI) {
			const res = await window.electronAPI.send({
				type: 'window:isFocused'
			});
			if (res) {
				isFocused = res.isFocused;
			}
		}

		await tick();
		const type = event?.data?.type ?? null;
		const data = event?.data?.data ?? null;

		// Track which chats are streaming live, regardless of which page the user is
		// viewing. The Tasks page (`TaskList.svelte`) and the sidebar
		// (`ChatItem.svelte`) read `$activeChatIds` to render the spinner. The
		// backend emits `chat:active` from the OWI legacy chat task path
		// (`main.py:1344` on completion, `main.py:1358` on task start) to room
		// `user:{user_id}`. Note: the Hermes-first chat surface in
		// `routers/openai.py` (`/myah/v1/message`) does NOT emit this event today,
		// so the spinner only fires for legacy traffic. A follow-up should add the
		// emit to the Hermes pipeline for full coverage.
		if (type === 'chat:active' && event.chat_id) {
			const isActive = !!data?.active;
			activeChatIds.update((ids) => {
				const next = new Set(ids);
				if (isActive) {
					next.add(event.chat_id);
				} else {
					next.delete(event.chat_id);
				}
				return next;
			});
			return;
		}

		if ((event.chat_id !== $chatId && !$temporaryChatEnabled) || isFocused) {
			if (type === 'chat:completion') {
				const { done, content, title } = data;
				const displayTitle = title || $i18n.t('New Chat');

				if (done) {
					if ($settings?.notificationSoundAlways ?? false) {
						playingNotificationSound.set(true);

						const audio = new Audio(`/audio/notification.mp3`);
						audio.play().finally(() => {
							// Ensure the global state is reset after the sound finishes
							playingNotificationSound.set(false);
						});
					}

					if ($isLastActiveTab) {
						if ($settings?.notificationEnabled ?? false) {
							new Notification(`${displayTitle} • Myah`, {
								body: content,
								icon: `${MYAH_BASE_URL}/static/favicon.png`
							});
						}
					}

					toast.custom(NotificationToast, {
						componentProps: {
							onClick: () => {
								goto(`/c/${event.chat_id}`);
							},
							content: content,
							title: displayTitle
						},
						duration: 15000,
						unstyled: true
					});
				}
			} else if (type === 'chat:title') {
				currentChatPage.set(1);
				await chats.set(await getChatList(localStorage.token, $currentChatPage));
			}
		} else if (data?.session_id === $socket.id) {
			if (type === 'request:chat:completion') {
				console.log(data, $socket.id);
				const { session_id, channel, form_data, model } = data;

				try {
					const directConnections = $settings?.directConnections ?? {};

					if (directConnections) {
						const urlIdx = model?.urlIdx;

						const OPENAI_API_URL = directConnections.OPENAI_API_BASE_URLS[urlIdx];
						const OPENAI_API_KEY = directConnections.OPENAI_API_KEYS[urlIdx];
						const API_CONFIG = directConnections.OPENAI_API_CONFIGS[urlIdx];

						try {
							if (API_CONFIG?.prefix_id) {
								const prefixId = API_CONFIG.prefix_id;
								form_data['model'] = form_data['model'].replace(`${prefixId}.`, ``);
							}

							const [res, controller] = await chatCompletion(
								OPENAI_API_KEY,
								form_data,
								OPENAI_API_URL
							);

							if (res) {
								// raise if the response is not ok
								if (!res.ok) {
									throw await res.json();
								}

								if (form_data?.stream ?? false) {
									cb({
										status: true
									});
									console.log({ status: true });

									// res will either be SSE or JSON
									const reader = res.body.getReader();
									const decoder = new TextDecoder();

									const processStream = async () => {
										while (true) {
											// Read data chunks from the response stream
											const { done, value } = await reader.read();
											if (done) {
												break;
											}

											// Decode the received chunk
											const chunk = decoder.decode(value, { stream: true });

											// Process lines within the chunk
											const lines = chunk.split('\n').filter((line) => line.trim() !== '');

											for (const line of lines) {
												console.log(line);
												$socket?.emit(channel, line);
											}
										}
									};

									// Process the stream in the background
									await processStream();
								} else {
									const data = await res.json();
									cb(data);
								}
							} else {
								throw new Error('An error occurred while fetching the completion');
							}
						} catch (error) {
							console.error('chatCompletion', error);
							cb(error);
						}
					}
				} catch (error) {
					console.error('chatCompletion', error);
					cb(error);
				} finally {
					$socket.emit(channel, {
						done: true
					});
				}
			} else {
				console.log('chatEventHandler', event);
			}
		}
	};

	const TOKEN_EXPIRY_BUFFER = 60; // seconds
	const checkTokenExpiry = async () => {
		const exp = $user?.expires_at; // token expiry time in unix timestamp
		const now = Math.floor(Date.now() / 1000); // current time in unix timestamp

		if (!exp) {
			// If no expiry time is set, do nothing
			return;
		}

		if (now >= exp - TOKEN_EXPIRY_BUFFER) {
			const res = await userSignOut();
			user.set(null);
			localStorage.removeItem('token');

			location.href = res?.redirect_url ?? '/auth';
		}
	};

	const desktopEventHandler = async (event) => {
		// Events that don't require auth
		if (event.type === 'page:reload') {
			location.reload();
			return;
		}
		if (event.type === 'page:navigate' && event.data?.path) {
			await goto(event.data.path);
			return;
		}
		if (event.type === 'models:refresh') {
			const token = localStorage.token;
			if (token) {
				models.set(
					await getModelsWithProviders(
						token,
						$config?.features?.enable_direct_connections
							? ($settings?.directConnections ?? null)
							: null
					)
				);
			}
			return;
		}

		const token = localStorage.token;
		if (!token) return;

		// Only admins can modify system-level connections
		if ($user?.role !== 'admin') return;

		try {
			if (event.type === 'connections:openai') {
				if (event.data.action === 'add') {
					await addOpenAIConnection(token, {
						url: event.data.url,
						key: event.data.key
					});
				} else if (event.data.action === 'remove') {
					await removeOpenAIConnection(token, event.data.url);
				}
			}
		} catch (e) {
			console.error('Desktop connection update failed:', e);
		}
	};

	const windowMessageEventHandler = async (_event) => {
		// Community sharing removed — no messages handled.
	};

	onMount(async () => {
		// OSS-mode first-run probe runs in parallel with the normal init
		// flow. The gating render below waits on ossProbeLoaded before
		// showing the app shell, so a slow probe doesn't gate normal
		// app boot in hosted mode.
		if (isOss) {
			void runOssProbe();
		} else {
			ossProbeLoaded = true;
		}

		window.addEventListener('message', windowMessageEventHandler);

		let touchstartY = 0;

		function isNavOrDescendant(el) {
			const nav = document.querySelector('nav'); // change selector if needed
			return nav && (el === nav || nav.contains(el));
		}

		const touchstartHandler = (e) => {
			if (!isNavOrDescendant(e.target)) return;
			touchstartY = e.touches[0].clientY;
		};

		const touchmoveHandler = (e) => {
			if (!isNavOrDescendant(e.target)) return;
			const touchY = e.touches[0].clientY;
			const touchDiff = touchY - touchstartY;
			if (touchDiff > 50 && window.scrollY === 0) {
				showRefresh = true;
				e.preventDefault();
			}
		};

		const touchendHandler = (e) => {
			if (!isNavOrDescendant(e.target)) return;
			if (showRefresh) {
				showRefresh = false;
				location.reload();
			}
		};

		document.addEventListener('touchstart', touchstartHandler);
		document.addEventListener('touchmove', touchmoveHandler, { passive: false });
		document.addEventListener('touchend', touchendHandler);

		if (typeof window !== 'undefined') {
			if (window.applyTheme) {
				window.applyTheme();
			}
		}

		if (window?.electronAPI) {
			const info = await window.electronAPI.send({
				type: 'app:info'
			});

			if (info) {
				isApp.set(true);
				appInfo.set(info);

				const data = await window.electronAPI.send({
					type: 'app:data'
				});

				if (data) {
					appData.set(data);
				}
			}

			// Listen for desktop service lifecycle events (scalable protocol)
			if (window.electronAPI.onEvent) {
				window.electronAPI.onEvent(desktopEventHandler);
			}
		}

		// Listen for messages on the BroadcastChannel
		bc.onmessage = (event) => {
			if (event.data === 'active') {
				isLastActiveTab.set(false); // Another tab became active
			}
		};

		// Set yourself as the last active tab when this tab is focused
		const handleVisibilityChange = () => {
			if (document.visibilityState === 'visible') {
				isLastActiveTab.set(true); // This tab is now the active tab
				// Guard: bc may already be closed if onDestroy ran before this handler fires
				try {
					bc.postMessage('active'); // Notify other tabs that this tab is active
				} catch {
					// BroadcastChannel closed — no-op
				}

				// Check token expiry when the tab becomes active
				checkTokenExpiry();
			}
		};

		// Add event listener for visibility state changes
		document.addEventListener('visibilitychange', handleVisibilityChange);

		// Call visibility change handler initially to set state on load
		handleVisibilityChange();

		theme.set(localStorage.theme);

		mobile.set(window.innerWidth < BREAKPOINT);

		const onResize = () => {
			if (window.innerWidth < BREAKPOINT) {
				mobile.set(true);
			} else {
				mobile.set(false);
			}
		};
		window.addEventListener('resize', onResize);

		// ── Cron delivery failure notification ─────────────────────────────
		// Shown globally so the user always knows when a scheduled task ran
		// but its output couldn't be delivered to the originating chat.
		const cronDeliveryFailedHandler = (data) => {
			const name = data?.job_name ?? 'Scheduled task';
			toast.error(`"${name}" ran but output could not be delivered — check task settings`, {
				duration: 8000
			});
		};

		user.subscribe(async (value) => {
			if (value) {
				$socket?.off('events', chatEventHandler);
				$socket?.off('process:delivery-failed', cronDeliveryFailedHandler);

				$socket?.on('events', chatEventHandler);
				$socket?.on('process:delivery-failed', cronDeliveryFailedHandler);

				const userSettings = await getUserSettings(localStorage.token);
				if (userSettings) {
					settings.set(userSettings.ui);
				} else {
					settings.set(JSON.parse(localStorage.getItem('settings') ?? '{}'));
				}
				setTextScale($settings?.textScale ?? 1);

				// Set up the token expiry check
				if (tokenTimer) {
					clearInterval(tokenTimer);
				}
				tokenTimer = setInterval(checkTokenExpiry, 15000);
			} else {
				$socket?.off('events', chatEventHandler);
				$socket?.off('process:delivery-failed', cronDeliveryFailedHandler);
			}
		});

		let backendConfig = null;
		try {
			backendConfig = await getBackendConfig();
			console.log('Backend config:', backendConfig);
		} catch (error) {
			if (error?.authRedirect) {
				// Forward-auth proxy is redirecting to an external login page.
				// Full-page navigation lets the browser follow the redirect natively.
				window.location.href = '/';
				return;
			}
			console.error('Error loading backend config:', error);
		}
		// Initialize i18n even if we didn't get a backend config,
		// so `/error` can show something that's not `undefined`.

		initI18n(localStorage?.locale);
		if (!localStorage.locale) {
			const languages = await getLanguages();
			const browserLanguages = navigator.languages
				? navigator.languages
				: [navigator.language || navigator.userLanguage];
			const lang = backendConfig?.default_locale
				? backendConfig.default_locale
				: bestMatchingLanguage(languages, browserLanguages, 'en-US');
			changeLanguage(lang);
			dayjs.locale(lang);
		}

		if (backendConfig) {
			// Save Backend Status to Store
			await config.set(backendConfig);
			await MYAH_NAME.set(backendConfig.name);

			if ($config) {
				// Always set up the socket connection — the auth page needs $socket to
				// emit user-join after a successful login. T3-859 (user-join emitted before
				// token is set) is addressed inside the socket connect handler, which only
				// emits user-join when localStorage.token is present.
				await setupSocket($config.features?.enable_websocket ?? true);

				const currentUrl = `${window.location.pathname}${window.location.search}`;
				const encodedUrl = encodeURIComponent(currentUrl);

				if (localStorage.token) {
					// Validate session after socket is ready.
					const sessionUser = await getSessionUser(localStorage.token).catch((error) => {
						console.error('Session validation failed:', error);
						return null;
					});

					if (sessionUser) {
						await user.set(sessionUser);
						// Myah T3-932: hydrate per-user default model from session payload.
						defaultModel.set(sessionUser?.default_model ?? null);
						try {
							await config.set(await getBackendConfig());
						} catch (error) {
							console.error('Error refreshing backend config:', error);
						}
					} else {
						// Retry once before destroying the token — the first failure may be
						// a transient network error during a hard reload (e.g. version update).
						const retryUser = await getSessionUser(localStorage.token).catch(() => null);
						if (retryUser) {
							await user.set(retryUser);
							defaultModel.set(retryUser?.default_model ?? null);
						} else {
							// Definitive failure — remove token and redirect to auth.
							localStorage.removeItem('token');
							await goto(`/auth?redirect=${encodedUrl}`);
						}
					}
				} else {
					// Don't redirect if we're already on the auth page
					// Needed because we pass in tokens from OAuth logins via URL fragments
					if ($page.url.pathname !== '/auth') {
						await goto(`/auth?redirect=${encodedUrl}`);
					}
				}
			}
		} else {
			// Redirect to /error when Backend Not Detected
			await goto(`/error`);
		}

		await tick();

		if (
			document.documentElement.classList.contains('her') &&
			document.getElementById('progress-bar')
		) {
			loadingProgress.subscribe((value) => {
				const progressBar = document.getElementById('progress-bar');

				if (progressBar) {
					progressBar.style.width = `${value}%`;
				}
			});

			await loadingProgress.set(100);

			document.getElementById('splash-screen')?.remove();

			const audio = new Audio(`/audio/greeting.mp3`);
			const playAudio = () => {
				audio.play();
				document.removeEventListener('click', playAudio);
			};

			document.addEventListener('click', playAudio);

			loaded = true;
		} else {
			document.getElementById('splash-screen')?.remove();
			loaded = true;
		}

		return () => {
			window.removeEventListener('resize', onResize);
			window.removeEventListener('message', windowMessageEventHandler);
			document.removeEventListener('touchstart', touchstartHandler);
			document.removeEventListener('touchmove', touchmoveHandler);
			document.removeEventListener('touchend', touchendHandler);
			document.removeEventListener('visibilitychange', handleVisibilityChange);
		};
	});

	onDestroy(() => {
		bc.close();
	});
</script>

<svelte:head>
	<title>{$MYAH_NAME}</title>
	<link crossorigin="anonymous" rel="icon" href="{MYAH_BASE_URL}/static/favicon.png" />

	<meta name="apple-mobile-web-app-title" content={$MYAH_NAME} />
	<meta name="description" content={$MYAH_NAME} />
	<link
		rel="search"
		type="application/opensearchdescription+xml"
		title={$MYAH_NAME}
		href="/opensearch.xml"
		crossorigin="use-credentials"
	/>
</svelte:head>

{#if showRefresh}
	<div class=" py-5">
		<Spinner className="size-5" />
	</div>
{/if}

{#if isOss && ossProbeLoaded && $page.url.pathname !== '/diagnostics'}
	<!--
		OSS first-run gate. Renders BEFORE the normal app shell when the
		probe surfaces an unrecoverable boot state or the welcome screen
		hasn't been dismissed yet. The /diagnostics route is exempt so
		users can always reach it from the blocking-error screens.
	-->
	{#if ossProbeError || !ossProbe}
		<HermesDownError
			hermesUrl={ossProbe?.hermes_url ?? 'http://host.docker.internal:8642'}
			onRetry={runOssProbe}
		/>
	{:else if !ossProbe.hermes_reachable}
		<HermesDownError hermesUrl={ossProbe.hermes_url} onRetry={runOssProbe} />
	{:else if !ossProbe.plugin_installed}
		<PluginMissingError hermesUrl={ossProbe.hermes_url} onRetry={runOssProbe} />
	{:else if ossProbe.first_run && ossProbe.providers_configured.length === 0}
		<Welcome probe={ossProbe} onContinue={handleWelcomeContinue} />
	{:else if loaded}
		{#if $isApp}
			<div class="flex flex-row h-screen">
				<AppSidebar />

				<div class="w-full flex-1 max-w-[calc(100%-4.5rem)]">
					<slot />
				</div>
			</div>
		{:else}
			<slot />
		{/if}
	{/if}
{:else if loaded}
	{#if $isApp}
		<div class="flex flex-row h-screen">
			<AppSidebar />

			<div class="w-full flex-1 max-w-[calc(100%-4.5rem)]">
				<slot />
			</div>
		</div>
	{:else}
		<slot />
	{/if}
{/if}

<Toaster
	theme={$theme.includes('dark')
		? 'dark'
		: $theme === 'system'
			? window.matchMedia('(prefers-color-scheme: dark)').matches
				? 'dark'
				: 'light'
			: 'light'}
	richColors
	position="top-right"
	closeButton
/>
