<script lang="ts">
	// --- Temporary debug logging — set to true to enable, false to disable ---
	const DEBUG_CHAT = false;
	// -------------------------------------------------------------------------

	import { v4 as uuidv4 } from 'uuid';
	import { toast } from 'svelte-sonner';
	import { PaneGroup, Pane, PaneResizer } from 'paneforge';

	import { createEventDispatcher, getContext, onDestroy, onMount, tick } from 'svelte';
	import { fade } from 'svelte/transition';
	const i18n: Writable<i18nType> = getContext('i18n');

	import { goto } from '$app/navigation';
	import { page } from '$app/stores';

	import { type Unsubscriber, type Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';
	import { MYAH_BASE_URL } from '$lib/constants';

	import {
		chatId,
		chats,
		config,
		type Model,
		models,
		tags as allTags,
		settings,
		showSidebar,
		MYAH_NAME,
		banners,
		user,
		socket,
		artifactPaneOpen,
		artifactActiveTabIdx,
		composerRefs,
		artifactPendingEdits,
		currentChatPage,
		temporaryChatEnabled,
		mobile,
		chatTitle,
		selectedFolder,
		pinnedChats,
		chatRequestQueues,
		defaultModel,
		closeArtifactPane,
		agentCommands,
		bumpArtifactExplorerRefresh
	} from '$lib/stores';
	import { get } from 'svelte/store';
	import { assembleUIState } from '$lib/utils/uiState';

	import { MYAH_API_BASE_URL } from '$lib/constants';

	import {
		convertMessagesToHistory,
		copyToClipboard,
		getMessageContentParts,
		createMessagesList,
		getPromptVariables,
		processDetails,
		removeAllDetails,
		isYoutubeUrl
	} from '$lib/utils';

	import {
		archiveChatById,
		createNewChat,
		deleteChatById,
		getAllTags,
		getChatById,
		getChatList,
		getPinnedChatList,
		getTagsById,
		updateChatById,
		updateChatFolderIdById,
		getActiveRun,
		getChatLiveState
	} from '$lib/apis/chats';
	import { generateOpenAIChatCompletion } from '$lib/apis/openai';
	import { getAndUpdateUserLocation, getUserSettings } from '$lib/apis/users';
	import {
		chatCompleted,
		generateQueries,
		chatAction,
		stopTask,
		getTaskIdsByChatId
	} from '$lib/apis';
	import { uploadFile } from '$lib/apis/files';
	import { createOpenAITextStream } from '$lib/apis/streaming';
	import { updateFolderById } from '$lib/apis/folders';
	import { getAgentCommands } from '$lib/apis/agent';

	import Banner from '../common/Banner.svelte';
	import MessageInput from '$lib/components/chat/MessageInput.svelte';
	import Messages from '$lib/components/chat/Messages.svelte';
	import Navbar from '$lib/components/chat/Navbar.svelte';
	import ArtifactPane from './Artifacts/ArtifactPane.svelte';
	import EventConfirmDialog from '../common/ConfirmDialog.svelte';
	import Placeholder from './Placeholder.svelte';
	import FilesOverlay from './MessageInput/FilesOverlay.svelte';
	import NotificationToast from '../NotificationToast.svelte';
	import Spinner from '../common/Spinner.svelte';
	import Tooltip from '../common/Tooltip.svelte';
	import Sidebar from '../icons/Sidebar.svelte';
	import Image from '../common/Image.svelte';
	import { getBanners } from '$lib/apis/configs';
	import { linkProcessToChat } from '$lib/apis/processes';
	import { findModelByIdOrSelectionKey, selectionMatchesModel } from '$lib/utils/modelSelection';
	import {
		loadInflightSnapshot,
		clearInflightSnapshot,
		pruneStaleSnapshots
	} from '$lib/utils/inflightPersistence';
	import { reconnectBanner } from '$lib/stores';
	import { applyDurableFinalMessageEvent } from '$lib/utils/chatEventFallback';
	import type { InflightSnapshot } from '$lib/types';
	import ReconnectBanner from './ReconnectBanner.svelte';
	import TodoPlanStrip from './TodoPlanStrip.svelte';
	import { getPinnedTodoPlan } from './todoPlanSelection';
	import type { TodoPlanItem } from '$lib/types/contract';

	export let chatIdProp = '';
	export let embedded = false;
	export let linkedProcess: any = null;

	const dispatch = createEventDispatcher();

	let loading = true;

	const eventTarget = new EventTarget();

	let messageInput: MessageInput | undefined;

	let autoScroll = true;
	let processing = '';
	let messagesContainerElement: HTMLDivElement;

	let navbarElement;

	let showEventConfirmation = false;
	let eventConfirmationTitle = '';
	let eventConfirmationMessage = '';
	let eventConfirmationInput = false;
	let eventConfirmationInputPlaceholder = '';
	let eventConfirmationInputValue = '';
	let eventConfirmationInputType = '';
	let eventCallback = null;

	let selectedModels = [''];
	let atSelectedModel: Model | undefined;
	let selectedModelIds = [];
	let pinnedTodoPlan: TodoPlanItem | null = null;
	$: pinnedTodoPlan = getPinnedTodoPlan(history);
	$: if (atSelectedModel !== undefined) {
		selectedModelIds = [atSelectedModel.id];
	} else {
		selectedModelIds = selectedModels;
	}

	let selectedToolIds = [];
	let pendingOAuthTools = [];

	let webSearchEnabled = false;

	let showCommands = false;

	let generating = false;
	let dragged = false;
	let generationController = null;

	let chat = null;
	let tags = [];

	let history = {
		messages: {},
		currentId: null
	};

	let taskIds = null;

	// Chat Input
	let prompt = '';
	let chatFiles = [];
	let files = [];
	let params = {};

	$: if (chatIdProp) {
		navigateHandler();
	}

	const navigateHandler = async () => {
		loading = true;

		prompt = '';
		messageInput?.setText('');

		files = [];
		selectedToolIds = [];
		webSearchEnabled = false;

		const storageChatInput = sessionStorage.getItem(
			`chat-input${chatIdProp ? `-${chatIdProp}` : ''}`
		);

		if (chatIdProp && (await loadChat())) {
			await tick();
			loading = false;
			window.setTimeout(() => scrollToBottom(), 0);

			await tick();

			// Attempt to resume any in-flight run from before the page load.
			// Only for persisted chats — local/temporary chats have no server state.
			if (chatIdProp && !chatIdProp.startsWith('local:')) {
				tryResumeInflight(chatIdProp);
			}

			// Process any queued requests if the chat is idle
			const lastMessage = history.currentId ? history.messages[history.currentId] : null;
			const isIdle = !lastMessage || lastMessage.role !== 'assistant' || lastMessage.done;
			if (isIdle) {
				await processNextInQueue(chatIdProp);
			}

			if (storageChatInput) {
				try {
					const input = JSON.parse(storageChatInput);

					if (!$temporaryChatEnabled) {
						messageInput?.setText(input.prompt);
						files = input.files;
						selectedToolIds = input.selectedToolIds;
						webSearchEnabled = input.webSearchEnabled;
					}
				} catch (e) {}
			} else {
				await setDefaults();
			}

			const chatInput = document.getElementById('chat-input');
			chatInput?.focus();
		} else if (!embedded) {
			await goto('/');
		} else {
			// Embedded mode with no chat found — clear loading state so the
			// panel doesn't show an infinite spinner.
			loading = false;
		}
	};

	const onSelect = async (e) => {
		const { type, data } = e;

		if (type === 'prompt') {
			// Handle prompt selection
			messageInput?.setText(data, async () => {
				if (!($settings?.insertSuggestionPrompt ?? false)) {
					await tick();
					submitPrompt(prompt);
				}
			});
		}
	};

	$: if (selectedModels && chatIdProp !== '') {
		saveSessionSelectedModels();
	}

	const saveSessionSelectedModels = () => {
		const selectedModelsString = JSON.stringify(selectedModels);
		if (
			selectedModels.length === 0 ||
			(selectedModels.length === 1 && selectedModels[0] === '') ||
			sessionStorage.selectedModels === selectedModelsString
		) {
			return;
		}
		sessionStorage.selectedModels = selectedModelsString;
		console.log('saveSessionSelectedModels', selectedModels, sessionStorage.selectedModels);
	};

	let oldSelectedModelIds = [''];
	$: if (JSON.stringify(selectedModelIds) !== JSON.stringify(oldSelectedModelIds)) {
		onSelectedModelIdsChange();
	}

	const onSelectedModelIdsChange = () => {
		resetInput();
		oldSelectedModelIds = structuredClone(selectedModelIds);
	};

	const resetInput = () => {
		selectedToolIds = [];
		pendingOAuthTools = [];
		webSearchEnabled = false;

		if (selectedModelIds.filter((id) => id).length > 0) {
			setDefaults();
		}
	};

	const setDefaults = async () => {
		if (selectedModels.length !== 1 && !atSelectedModel) {
			return;
		}

		const model = atSelectedModel ?? findModelByIdOrSelectionKey(selectedModels[0], $models);
		if (model) {
			if ($settings?.tools) {
				selectedToolIds = $settings.tools;
			} else {
				selectedToolIds = selectedToolIds.filter((id) => !id.startsWith('direct_server:'));
			}

			// Set Default Features
			if (model?.info?.meta?.defaultFeatureIds) {
				if (
					model.info?.meta?.capabilities?.['web_search'] &&
					$config?.features?.enable_web_search &&
					($user?.role === 'admin' || $user?.permissions?.features?.web_search)
				) {
					webSearchEnabled = model.info.meta.defaultFeatureIds.includes('web_search');
				}
			}
		}
	};

	const showMessage = async (message, scroll = true) => {
		const _chatId = JSON.parse(JSON.stringify($chatId));
		let _messageId = JSON.parse(JSON.stringify(message.id));

		let messageChildrenIds = [];
		if (_messageId === null) {
			messageChildrenIds = Object.keys(history.messages).filter(
				(id) => history.messages[id].parentId === null
			);
		} else {
			messageChildrenIds = history.messages[_messageId].childrenIds;
		}

		while (messageChildrenIds.length !== 0) {
			_messageId = messageChildrenIds.at(-1);
			messageChildrenIds = history.messages[_messageId].childrenIds;
		}

		history.currentId = _messageId;

		await tick();

		if (($settings?.scrollOnBranchChange ?? true) && scroll) {
			const messageElement = document.getElementById(`message-${message.id}`);
			if (messageElement) {
				messageElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
			}
		}

		await tick();
		await tick();
		await tick();

		saveChatHandler(_chatId, history);
	};

	const chatEventHandler = async (event, cb) => {
		if (event.chat_id === $chatId) {
			if (applyDurableFinalMessageEvent(event, $chatId, { history }, { clearInflightSnapshot })) {
				const message = (history.messages as Record<string, any>)[event.message_id];
				await saveChatHandler($chatId, history);
				await finalizeCompletedAssistantMessage($chatId, message, { runBackgroundCompletion: false });
				return;
			}

			await tick();
			let message = history.messages[event.message_id];

			if (message) {
				const type = event?.data?.type ?? null;
				const data = event?.data?.data ?? null;

				if (DEBUG_CHAT) {
					// Log every socket event; for content deltas only show length to keep output manageable
					if (
						type === 'chat:completion' &&
						event?.data?.data?.choices?.[0]?.delta?.content !== undefined
					) {
						const delta = event.data.data.choices[0].delta.content;
						console.log(
							`[chat:event] msgId=${event.message_id} type=${type} delta(${delta.length}ch)=${JSON.stringify(delta.slice(0, 80))}${delta.length > 80 ? '...' : ''}`
						);
					} else {
						console.log(
							`[chat:event] msgId=${event.message_id} type=${type}`,
							JSON.parse(JSON.stringify(event?.data?.data ?? {}))
						);
					}
				}

				if (type === 'status') {
					// Drop status events that arrive after the message is already done —
					// background tasks (title generation, follow-ups) share the same socket
					// channel and can emit stale 'Thinking...' / 'Agent ready' events after
					// the response has completed, leaving the badge permanently shimmering.
					if (!message.done) {
						if (message?.statusHistory) {
							message.statusHistory.push(data);
						} else {
							message.statusHistory = [data];
						}
					} else if (DEBUG_CHAT) {
						console.log(
							`[chat:event] DROPPED late status after done: msgId=${event.message_id}`,
							data
						);
					}
				} else if (type === 'chat:completion') {
					chatCompletionEventHandler(data, message, event.chat_id);
				} else if (type === 'chat:tasks:cancel') {
					if (event.message_id === history.currentId) {
						taskIds = null;
						// Set all response messages to done
						for (const messageId of history.messages[message.parentId].childrenIds) {
							history.messages[messageId].done = true;
						}
						await processNextInQueue($chatId);
					} else {
						message.done = true;
					}
				} else if (type === 'chat:message:delta' || type === 'message') {
					message.content += data.content;
				} else if (type === 'chat:message' || type === 'replace') {
					message.content = data.content;
				} else if (type === 'chat:message:files' || type === 'files') {
					message.files = data.files;
				} else if (type === 'chat:message:embeds' || type === 'embeds') {
					message.embeds = data.embeds;

					// Auto-scroll to the embed once it's rendered in the DOM
					await tick();
					setTimeout(() => {
						const embedEl = document.getElementById(`${event.message_id}-embeds-container`);
						if (embedEl) {
							embedEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
						}
					}, 100);
				} else if (type === 'chat:message:error') {
					message.error = data.error;
				} else if (type === 'chat:message:follow_ups') {
					message.followUps = data.follow_ups;

					if (autoScroll) {
						scrollToBottom('smooth');
					}
				} else if (type === 'chat:message:favorite') {
					// Update message favorite status
					message.favorite = data.favorite;
				} else if (type === 'chat:title') {
					chatTitle.set(data);
					currentChatPage.set(1);
					await chats.set(await getChatList(localStorage.token, $currentChatPage));
				} else if (type === 'chat:tags') {
					chat = await getChatById(localStorage.token, $chatId);
					allTags.set(await getAllTags(localStorage.token));
				} else if (type === 'notification') {
					const toastType = data?.type ?? 'info';
					const toastContent = data?.content ?? '';

					if (toastType === 'success') {
						toast.success(toastContent);
					} else if (toastType === 'error') {
						toast.error(toastContent);
					} else if (toastType === 'warning') {
						toast.warning(toastContent);
					} else {
						toast.info(toastContent);
					}
				} else if (type === 'confirmation') {
					eventCallback = cb;

					eventConfirmationInput = false;
					showEventConfirmation = true;

					eventConfirmationTitle = data.title;
					eventConfirmationMessage = data.message;
				} else if (type === 'execute') {
					eventCallback = cb;

					try {
						// Use Function constructor to evaluate code in a safer way
						const asyncFunction = new Function(`return (async () => { ${data.code} })()`);
						const result = await asyncFunction(); // Await the result of the async function

						if (cb) {
							cb(result);
						}
					} catch (error) {
						console.error('Error executing code:', error);
					}
				} else if (type === 'input') {
					eventCallback = cb;

					eventConfirmationInput = true;
					showEventConfirmation = true;

					eventConfirmationTitle = data.title;
					eventConfirmationMessage = data.message;
					eventConfirmationInputPlaceholder = data.placeholder;
					eventConfirmationInputValue = data?.value ?? '';
					eventConfirmationInputType = data?.type ?? '';
				} else if (type?.startsWith('terminal:')) {
					terminalEventHandler(type, data);
				} else if (type === 'chat:active') {
					// Lifecycle heartbeat — no UI action needed
				} else if (type === 'hermes:artifact') {
					// Phase 1: hermes:artifact no longer triggers UI — Phase 4 replaces with artifact_card OutputItem (spec §3).
				}

				history.messages[event.message_id] = message;
			}
		} else {
			// Non-active chat completion: queue stays in the global store.
			// navigateHandler will process it when the user returns to that chat.
		}
	};

	const onMessageHandler = async (event: {
		origin: string;
		data: { type: string; text: string };
	}) => {
		const isSameOrigin = event.origin === window.origin;
		const type = event.data?.type;

		// Prompt-related message types only submit text to the chat input —
		// functionally equivalent to the user typing.  When same-origin is
		// enabled they go through immediately.  When it is disabled (opaque
		// origin) we show a confirmation dialog so the user stays in control.
		const iframePromptTypes = ['input:prompt', 'input:prompt:submit', 'action:submit'];

		if (!isSameOrigin && !iframePromptTypes.includes(type)) {
			return;
		}

		if (type === 'action:submit') {
			console.debug(event.data.text);

			if (prompt !== '') {
				await tick();
				submitPrompt(prompt);
			}
		}

		if (type === 'input:prompt') {
			console.debug(event.data.text);

			const inputElement = document.getElementById('chat-input');

			if (inputElement) {
				messageInput?.setText(event.data.text);
				inputElement.focus();
			}
		}

		if (type === 'input:prompt:submit') {
			console.debug(event.data.text);

			if (event.data.text !== '') {
				if (isSameOrigin) {
					await tick();
					submitPrompt(event.data.text);
				} else {
					// Cross-origin: ask user to confirm before submitting
					eventConfirmationInput = false;
					eventConfirmationTitle = $i18n.t('Confirm Prompt from Embed');
					eventConfirmationMessage = event.data.text;
					eventCallback = async (confirmed: boolean) => {
						if (confirmed) {
							await tick();
							submitPrompt(event.data.text);
						}
					};
					showEventConfirmation = true;
				}
			}
		}
	};

	const savedModelIds = async () => {
		if (
			$selectedFolder &&
			selectedModels.filter((modelId) => modelId !== '').length > 0 &&
			JSON.stringify($selectedFolder?.data?.model_ids) !== JSON.stringify(selectedModels)
		) {
			const res = await updateFolderById(localStorage.token, $selectedFolder.id, {
				data: {
					model_ids: selectedModels
				}
			});
		}
	};

	$: if (selectedModels !== null) {
		savedModelIds();
	}

	const stopAudio = () => {
		try {
			speechSynthesis.cancel();
		} catch {}
	};

	// Handle cron run output arriving for this chat — reload the history
	// from the DB so the injected assistant message appears in real time.
	const cronRunCompleteHandler = async (data: any) => {
		if (!data?.chat_id || data.chat_id !== $chatId) return;
		try {
			const freshChat = await getChatById(localStorage.token, $chatId);
			if (freshChat?.chat?.history) {
				history = freshChat.chat.history;
				await tick();
				if (autoScroll) {
					scrollToBottom('smooth');
				}
			}
		} catch (e) {
			console.warn('[chat] Failed to reload chat after cron run:', e);
		}
	};

	// ── Myah: mid-stream resume ───────────────────────────────────────────────
	// Reconstruct a partial assistant message from a snapshot (either from
	// localStorage or from the server's live_state endpoint).
	//
	// Reconstruct a partial assistant message from a snapshot (either from
	// localStorage or from the server's live_state endpoint).
	//
	// snapshot.output is a flat OutputItem[] matching the message.output shape
	// from the stream handler. message_content carries the prose seen so far.
	// We write directly into history.messages so Svelte reactivity picks it up.
	function _applyInflightSnapshot(snapshot: InflightSnapshot | Record<string, any>) {
		if (!snapshot) return;
		const msgId = String(snapshot.message_id ?? '');
		if (!msgId) return;
		const msg = (history.messages as Record<string, any>)[msgId];
		if (!msg) return;
		// Only update if the message is still in-progress (not done)
		if (msg.done) return;

		if (snapshot.message_content) {
			msg.content = snapshot.message_content;
		}
		// output is the flat OutputItem[] from the stream handler
		if (Array.isArray(snapshot.output) && snapshot.output.length > 0) {
			msg.output = snapshot.output;
		}
		(history.messages as Record<string, any>)[msgId] = msg;
	}

	// Race server truth against a 200 ms paint timer and a 30 s hard timeout.
	//
	// Fast path (server responds < 200 ms):
	//   clearTimeout(paintTimer) fires before the stale snapshot is shown.
	// Slow path (server takes > 200 ms):
	//   stale snapshot is painted as a partial message with a "Reconnecting…"
	//   banner, then replaced by server truth when the promise resolves.
	// Terminal failure (5xx / network error / malformed response):
	//   Class-7 mitigation — banner set to non-null terminal string; no retry.
	// Hard timeout (30 s):
	//   Class-9 fallback — fall back to DB-load; clear banner.
	async function tryResumeInflight(chatId: string) {
		const PAINT_THRESHOLD_MS = 200;
		const HARD_TIMEOUT_MS = 30_000;
		let snapshotPainted = false;

		// M2 guard: check whether the user has navigated to a different chat
		// between async boundaries. If they have, silently discard this result
		// so we don't stomp the new chat's banner or message state.
		const isStale = () => chatIdProp !== chatId;

		const serverPromise = (async () => {
			try {
				const active = await getActiveRun(localStorage.token, chatId);
				if (isStale()) return null;
				// Class-7: shape validation is the success gate
				if (typeof active?.run_id === 'undefined') {
					throw new Error('malformed active_run response');
				}
				if (active.run_id === null) {
					return null; // no active run — DB load wins
				}
				const live = active.message_id
					? await getChatLiveState(localStorage.token, chatId, active.message_id)
					: null;
				if (isStale()) return null;
				return live ? { ...active, ...live } : null;
			} catch (err) {
				if (isStale()) throw err; // don't update banner for stale chat
				// Class-7: terminal failure; NOT a retry
				console.error('[reconnect] active_run/live_state fetch failed:', err);
				if (typeof window !== 'undefined' && (window as any).Sentry) {
					(window as any).Sentry.addBreadcrumb({
						category: 'stream-persistence',
						message: 'tryResumeInflight fetch failed',
						level: 'error',
						data: { error: String(err), chat_id: chatId }
					});
				}
				reconnectBanner.set('Reconnect failed — refresh to retry');
				throw err;
			}
		})();

		const paintTimer = setTimeout(() => {
			if (isStale()) return;
			const stored = loadInflightSnapshot(chatId);
			if (stored && stored.chat_id === chatId) {
				_applyInflightSnapshot(stored);
				reconnectBanner.set('Reconnecting...');
				snapshotPainted = true;
			}
		}, PAINT_THRESHOLD_MS);

		// Class-9: hard timeout fallback
		const hardTimeout = setTimeout(async () => {
			if (isStale()) return;
			reconnectBanner.set('Reconnect timed out — falling back to saved state');
			await loadChat();
			if (!isStale()) reconnectBanner.set(null);
		}, HARD_TIMEOUT_MS);

		try {
			const serverState = await serverPromise;
			clearTimeout(paintTimer);
			clearTimeout(hardTimeout);
			if (isStale()) return; // navigated away — discard result
			if (serverState) {
				_applyInflightSnapshot(serverState);
				reconnectBanner.set(null);
			} else if (snapshotPainted) {
				// Stale snapshot was painted — replace it with the authoritative DB state
				await loadChat();
				if (!isStale()) {
					clearInflightSnapshot(chatId);
					reconnectBanner.set(null);
				}
			} else {
				// No active run, no stale snapshot painted. navigateHandler already
				// called loadChat() before tryResumeInflight — DB state is current.
				reconnectBanner.set(null);
			}
		} catch {
			clearTimeout(paintTimer);
			clearTimeout(hardTimeout);
			// Banner already set to terminal state inside serverPromise catch.
			// Do NOT call loadChat — user must refresh to retry.
		}
	}
	// ─────────────────────────────────────────────────────────────────────────

	onMount(() => {
		loading = true;
		console.log('mounted');
		window.addEventListener('message', onMessageHandler);
		$socket?.on('events', chatEventHandler);
		$socket?.on('process:run-complete', cronRunCompleteHandler);

		const pageSubscribe = page.subscribe(async (p) => {
			if (p.url.pathname === '/') {
				await tick();
				initNewChat();

				// Re-fetch banners on navigation to homepage so newly configured banners appear
				try {
					banners.set(await getBanners(localStorage.token).catch(() => []));
				} catch (e) {
					console.error('Failed to refresh banners:', e);
				}
			}

			stopAudio();
		});

		const selectedFolderSubscribe = selectedFolder.subscribe(async (folder) => {
			await tick();
			if (
				folder?.data?.model_ids &&
				JSON.stringify(selectedModels) !== JSON.stringify(folder.data.model_ids)
			) {
				selectedModels = folder.data.model_ids;

				console.log('Set selectedModels from folder data:', selectedModels);
			}
		});

		const storageChatInput = sessionStorage.getItem(
			`chat-input${chatIdProp ? `-${chatIdProp}` : ''}`
		);

		pruneStaleSnapshots();
		const _pruneInterval = setInterval(pruneStaleSnapshots, 5 * 60 * 1000);

		const init = async () => {
			try {
				agentCommands.set(await getAgentCommands(localStorage.token));
			} catch (e) {
				console.error(e);
				agentCommands.set([]);
			}

			if (!chatIdProp) {
				loading = false;
				await tick();
			}

			if (storageChatInput) {
				prompt = '';
				messageInput?.setText('');

				files = [];
				selectedToolIds = [];
				webSearchEnabled = false;

				try {
					const input = JSON.parse(storageChatInput);

					if (!$temporaryChatEnabled) {
						messageInput?.setText(input.prompt);
						files = input.files;
						selectedToolIds = input.selectedToolIds;
						webSearchEnabled = input.webSearchEnabled;
					}
				} catch (e) {}
			}

			const chatInput = document.getElementById('chat-input');
			chatInput?.focus();
		};
		init();

		return () => {
			try {
				clearInterval(_pruneInterval);
				pageSubscribe();
				selectedFolderSubscribe();
				window.removeEventListener('message', onMessageHandler);
				$socket?.off('events', chatEventHandler);
				$socket?.off('process:run-complete', cronRunCompleteHandler);

				// ── Reset artifact panel state on chat unmount ──────────
				// The artifact pane is global state, never scoped to a chat.
				// Without explicit cleanup it leaks the previous chat's
				// artifact into the next chat — which then auto-opens the
				// panel with stale content (and at minimum 404s if the
				// artifact was a path-based reference whose agent container
				// has rotated).
				closeArtifactPane();
				// ────────────────────────────────────────────────────────
			} catch (e) {
				console.error(e);
			}
		};
	});

	const onUpload = async (event) => {
		const { type, data } = event;

		if (type === 'web') {
			// Instead of uploading the URL to a retrieval router, just prepend it to the
			// draft message. The agent's web_extract tool will fetch the content when needed.
			const urls = (Array.isArray(data) ? data : [data])
				.map((u: string) => String(u).trim())
				.filter(Boolean);
			if (!urls.length) return;
			const formatted = urls.join('\n');
			const newPrompt = prompt.trim() ? `${prompt}\n\n${formatted}` : formatted;
			messageInput?.setText(newPrompt);
		}
	};

	//////////////////////////
	// Web functions
	//////////////////////////

	const initNewChat = async () => {
		console.log('initNewChat');
		if ($user?.role !== 'admin' && $user?.permissions?.chat?.temporary_enforced) {
			await temporaryChatEnabled.set(true);
		}

		if ($settings?.temporaryChatByDefault ?? false) {
			if ($temporaryChatEnabled === false) {
				await temporaryChatEnabled.set(true);
			} else if ($temporaryChatEnabled === null) {
				// if set to null set to false; refer to temp chat toggle click handler
				await temporaryChatEnabled.set(false);
			}
		}

		if ($user?.role !== 'admin' && !$user?.permissions?.chat?.temporary) {
			await temporaryChatEnabled.set(false);
		}

		const availableModels = $models
			.filter((m) => !(m?.info?.meta?.hidden ?? false))
			.map((m) => m.id);

		const defaultModels = $config?.default_models ? $config?.default_models.split(',') : [];

		if ($page.url.searchParams.get('model')) {
			const urlModelId = $page.url.searchParams.get('model') ?? '';

			if (!findModelByIdOrSelectionKey(urlModelId, $models)) {
				// Model not found; open model selector and prefill
				const modelSelectorButton = document.getElementById('model-selector-0-button');
				if (modelSelectorButton) {
					modelSelectorButton.click();
					await tick();

					const modelSelectorInput = document.getElementById('model-search-input');
					if (modelSelectorInput) {
						modelSelectorInput.focus();
						modelSelectorInput.value = urlModelId;
						modelSelectorInput.dispatchEvent(new Event('input'));
					}
				}
			} else {
				selectedModels = [urlModelId];
			}

			// Unavailable models filtering — accept both bare id and composite
			// selection_key so composite picks aren't dropped as "unavailable".
			selectedModels = selectedModels.filter((modelId) =>
				$models.some((m) => m.id === modelId || m.selection_key === modelId)
			);
		} else {
			if ($selectedFolder?.data?.model_ids) {
				// Set from folder model IDs
				selectedModels = $selectedFolder?.data?.model_ids;
			} else if ($defaultModel) {
				// Myah T3-932 + 2026-05-24: per-user default (provider, model) pair
				// wins for new chats. The structured pair routes through the right
				// credential pool even when duplicate model ids exist across
				// providers (T3-1031 disambiguation case). Find the matching
				// $models row by both fields; fall through if neither matches.
				const match = $models.find(
					(m) =>
						m.id === $defaultModel.model &&
						m.tags?.[0]?.name === $defaultModel.provider
				);
				if (match) {
					selectedModels = [match.selection_key ?? match.id];
					sessionStorage.removeItem('selectedModels');
				}
			} else if (sessionStorage.selectedModels) {
				// Carry the last-used model forward when no explicit default
				// is set (convenience for users who haven't pinned one).
				selectedModels = JSON.parse(sessionStorage.selectedModels);
				sessionStorage.removeItem('selectedModels');
			} else if ($settings?.models) {
				// Legacy user multi-select (pre-T3-932). Kept for back-compat.
				selectedModels = $settings?.models;
			} else if (defaultModels && defaultModels.length > 0) {
				// Admin-configured DEFAULT_MODELS.
				selectedModels = defaultModels;
			}

			// Unavailable & hidden models filtering — accept both bare id and
			// composite selection_key so composite picks aren't dropped as
			// "unavailable".
			selectedModels = selectedModels.filter((modelId) =>
				$models.some((m) => m.id === modelId || m.selection_key === modelId)
			);
		}

		// Ensure at least one model is selected
		if (selectedModels.length === 0 || (selectedModels.length === 1 && selectedModels[0] === '')) {
			if (availableModels.length > 0) {
				// Myah T3-932 + 2026-05-24: fallback priority — per-user default
				// pair, then admin, then first.
				if ($defaultModel) {
					const match = $models.find(
						(m) =>
							m.id === $defaultModel.model &&
							m.tags?.[0]?.name === $defaultModel.provider
					);
					if (match) selectedModels = [match.selection_key ?? match.id];
				} else if (defaultModels && defaultModels.length > 0) {
					selectedModels = defaultModels.filter((modelId) => availableModels.includes(modelId));
				}

				if (
					selectedModels.length === 0 ||
					(selectedModels.length === 1 && selectedModels[0] === '')
				) {
					selectedModels = [availableModels?.at(0) ?? ''];
				}
			} else {
				selectedModels = [''];
			}
		}

		if ($mobile) {
			closeArtifactPane();
		}
		if ($page.url.pathname.includes('/c/')) {
			window.history.replaceState(history.state, '', `/`);
		}

		autoScroll = true;

		resetInput();
		await chatId.set('');
		await chatTitle.set('');

		history = {
			messages: {},
			currentId: null
		};

		chatFiles = [];
		params = {};
		taskIds = null;

		if ($page.url.searchParams.get('youtube')) {
			const ytUrl = `https://www.youtube.com/watch?v=${$page.url.searchParams.get('youtube')}`;
			prompt = prompt.trim() ? `${prompt}\n\n${ytUrl}` : ytUrl;
		}

		if ($page.url.searchParams.get('load-url')) {
			const loadUrl = $page.url.searchParams.get('load-url') ?? '';
			if (loadUrl) {
				prompt = prompt.trim() ? `${prompt}\n\n${loadUrl}` : loadUrl;
			}
		}

		if ($page.url.searchParams.get('web-search') === 'true') {
			webSearchEnabled = true;
		}

		if ($page.url.searchParams.get('tools')) {
			selectedToolIds = $page.url.searchParams
				.get('tools')
				?.split(',')
				.map((id) => id.trim())
				.filter((id) => id);
		} else if ($page.url.searchParams.get('tool-ids')) {
			selectedToolIds = $page.url.searchParams
				.get('tool-ids')
				?.split(',')
				.map((id) => id.trim())
				.filter((id) => id);
		}

		// Restore tool selection after OAuth redirect
		const pendingToolId = sessionStorage.getItem('pendingOAuthToolId');
		if (pendingToolId) {
			sessionStorage.removeItem('pendingOAuthToolId');
			if (!selectedToolIds.includes(pendingToolId)) {
				selectedToolIds = [...selectedToolIds, pendingToolId];
			}
		}

		if ($page.url.searchParams.get('q')) {
			const q = $page.url.searchParams.get('q') ?? '';
			messageInput?.setText(q);

			if (q) {
				if (($page.url.searchParams.get('submit') ?? 'true') === 'true') {
					await tick();
					submitPrompt(q);
				}
			}
		}

		// Accept both bare id and composite selection_key — see submitPrompt for
		// the same pattern. Without this, composite picks fall through to '' and
		// hydration shows "Select a model" on chat load.
		selectedModels = selectedModels.map((modelId) =>
			$models.some((m) => m.id === modelId || m.selection_key === modelId) ? modelId : ''
		);

		const chatInput = document.getElementById('chat-input');
		setTimeout(() => chatInput?.focus(), 0);
	};

	const loadChat = async () => {
		chatId.set(chatIdProp);

		if ($temporaryChatEnabled) {
			temporaryChatEnabled.set(false);
		}

		chat = await getChatById(localStorage.token, $chatId).catch(async (error) => {
			// When embedded in the tasks split-panel, don't redirect to home on error —
			// just stay and show nothing. The user can select a different task.
			if (!embedded) {
				await goto('/');
			}
			return null;
		});

		if (chat) {
			tags = await getTagsById(localStorage.token, $chatId).catch(async (error) => {
				return [];
			});

			const chatContent = chat.chat;

			if (chatContent) {
				console.log(chatContent);

				selectedModels = Array.isArray(chatContent.models)
					? [chatContent.models[0] ?? '']
					: [chatContent.models ?? ''];

				oldSelectedModelIds = structuredClone(selectedModels);

				history =
					(chatContent?.history ?? undefined) !== undefined
						? chatContent.history
						: convertMessagesToHistory(chatContent.messages ?? []);

				chatTitle.set(chatContent.title);

				params = chatContent?.params ?? {};
				chatFiles = chatContent?.files ?? [];

				autoScroll = true;
				await tick();

				if (history.currentId) {
					for (const message of Object.values(history.messages)) {
						if (message && message.role === 'assistant' && message.done !== false) {
							message.done = true;
						}
					}
				}

				const taskRes = await getTaskIdsByChatId(localStorage.token, $chatId).catch((error) => {
					return null;
				});

				if (taskRes) {
					taskIds = taskRes.task_ids;
				}

				await tick();

				return true;
			} else {
				return null;
			}
		}
	};

	const scrollToBottom = async (behavior = 'auto') => {
		await tick();
		if (messagesContainerElement) {
			messagesContainerElement.scrollTo({
				top: messagesContainerElement.scrollHeight,
				behavior
			});
		}
	};

	let scrollRAF = null;
	const scheduleScrollToBottom = () => {
		if (!scrollRAF) {
			scrollRAF = requestAnimationFrame(async () => {
				scrollRAF = null;
				await scrollToBottom();
			});
		}
	};

	const processNextInQueue = async (targetChatId: string) => {
		const queue = $chatRequestQueues[targetChatId];
		if (!queue || queue.length === 0) return;

		const combinedPrompt = queue.map((m) => m.prompt).join('\n\n');
		const combinedFiles = queue.flatMap((m) => m.files);

		chatRequestQueues.update((q) => {
			const { [targetChatId]: _, ...rest } = q;
			return rest;
		});

		files = combinedFiles;
		await tick();
		await submitPrompt(combinedPrompt);
	};

	const chatCompletedHandler = async (_chatId, modelId, responseMessageId, messages) => {
		const res = await chatCompleted(localStorage.token, {
			model: modelId,
			messages: messages.map((m) => ({
				id: m.id,
				role: m.role,
				content: m.content,
				info: m.info ? m.info : undefined,
				timestamp: m.timestamp,
				...(m.usage ? { usage: m.usage } : {}),
				...(m.sources ? { sources: m.sources } : {})
			})),
			model_item: findModelByIdOrSelectionKey(modelId, $models),
			chat_id: _chatId,
			session_id: $socket?.id,
			id: responseMessageId
		}).catch((error) => {
			toast.error(`${error}`);
			messages.at(-1).error = { content: error };

			return null;
		});

		if (res !== null && res.messages) {
			// Update chat history with the new messages
			for (const message of res.messages) {
				if (message?.id) {
					// Add null check for message and message.id
					history.messages[message.id] = {
						...history.messages[message.id],
						...(history.messages[message.id].content !== message.content
							? { originalContent: history.messages[message.id].content }
							: {}),
						...message
					};
				}
			}
		}

		await tick();

		if ($chatId == _chatId) {
			if (!$temporaryChatEnabled) {
				chat = await updateChatById(localStorage.token, _chatId, {
					models: selectedModels,
					messages: messages,
					history: history,
					params: params,
					files: chatFiles
				});

				currentChatPage.set(1);
				await chats.set(await getChatList(localStorage.token, $currentChatPage));
			}
		}

		taskIds = null;
	};

	const chatActionHandler = async (_chatId, actionId, modelId, responseMessageId, event = null) => {
		const messages = createMessagesList(history, responseMessageId);

		const res = await chatAction(localStorage.token, actionId, {
			model: modelId,
			messages: messages.map((m) => ({
				id: m.id,
				role: m.role,
				content: m.content,
				info: m.info ? m.info : undefined,
				timestamp: m.timestamp,
				...(m.sources ? { sources: m.sources } : {})
			})),
			...(event ? { event: event } : {}),
			model_item: findModelByIdOrSelectionKey(modelId, $models),
			chat_id: _chatId,
			session_id: $socket?.id,
			id: responseMessageId
		}).catch((error) => {
			toast.error(`${error}`);
			messages.at(-1).error = { content: error };
			return null;
		});

		if (res !== null && res.messages) {
			// Update chat history with the new messages
			for (const message of res.messages) {
				history.messages[message.id] = {
					...history.messages[message.id],
					...(history.messages[message.id].content !== message.content
						? { originalContent: history.messages[message.id].content }
						: {}),
					...message
				};
			}
		}

		if ($chatId == _chatId) {
			if (!$temporaryChatEnabled) {
				chat = await updateChatById(localStorage.token, _chatId, {
					models: selectedModels,
					messages: messages,
					history: history,
					params: params,
					files: chatFiles
				});

				currentChatPage.set(1);
				await chats.set(await getChatList(localStorage.token, $currentChatPage));
			}
		}
	};

	const getChatEventEmitter = async (modelId: string, chatId: string = '') => {
		return setInterval(() => {
			$socket?.emit('usage', {
				action: 'chat',
				model: modelId,
				chat_id: chatId
			});
		}, 1000);
	};

	const createMessagePair = async (userPrompt) => {
		messageInput?.setText('');
		if (selectedModels.length === 0) {
			toast.error($i18n.t('Model not selected'));
		} else {
			const modelId = selectedModels[0];
			const model = findModelByIdOrSelectionKey(modelId, $models);

			if (!model) {
				toast.error($i18n.t('Model not found'));
				return;
			}

			const messages = createMessagesList(history, history.currentId);
			const parentMessage = messages.length !== 0 ? messages.at(-1) : null;

			const userMessageId = uuidv4();
			const responseMessageId = uuidv4();

			const userMessage = {
				id: userMessageId,
				parentId: parentMessage ? parentMessage.id : null,
				childrenIds: [responseMessageId],
				role: 'user',
				content: userPrompt ? userPrompt : `[PROMPT] ${userMessageId}`,
				timestamp: Math.floor(Date.now() / 1000)
			};

			const responseMessage = {
				id: responseMessageId,
				parentId: userMessageId,
				childrenIds: [],
				role: 'assistant',
				content: `[RESPONSE] ${responseMessageId}`,
				done: true,

				model: modelId,
				modelName: model.name ?? model.id,
				timestamp: Math.floor(Date.now() / 1000)
			};

			if (parentMessage) {
				parentMessage.childrenIds.push(userMessageId);
				history.messages[parentMessage.id] = parentMessage;
			}
			history.messages[userMessageId] = userMessage;
			history.messages[responseMessageId] = responseMessage;

			history.currentId = responseMessageId;

			await tick();

			if (autoScroll) {
				scrollToBottom();
			}

			if (messages.length === 0) {
				await initChatHandler(history);
			} else {
				await saveChatHandler($chatId, history);
			}
		}
	};

	const addMessages = async ({ modelId, parentId, messages }) => {
		const model = findModelByIdOrSelectionKey(modelId, $models);

		let parentMessage = history.messages[parentId];
		let currentParentId = parentMessage ? parentMessage.id : null;
		for (const message of messages) {
			let messageId = uuidv4();

			if (message.role === 'user') {
				const userMessage = {
					id: messageId,
					parentId: currentParentId,
					childrenIds: [],
					timestamp: Math.floor(Date.now() / 1000),
					...message
				};

				if (parentMessage) {
					parentMessage.childrenIds.push(messageId);
					history.messages[parentMessage.id] = parentMessage;
				}

				history.messages[messageId] = userMessage;
				parentMessage = userMessage;
				currentParentId = messageId;
			} else {
				const responseMessage = {
					id: messageId,
					parentId: currentParentId,
					childrenIds: [],
					done: true,
					model: model.id,
					modelName: model.name ?? model.id,
					timestamp: Math.floor(Date.now() / 1000),
					...message
				};

				if (parentMessage) {
					parentMessage.childrenIds.push(messageId);
					history.messages[parentMessage.id] = parentMessage;
				}

				history.messages[messageId] = responseMessage;
				parentMessage = responseMessage;
				currentParentId = messageId;
			}
		}

		history.currentId = currentParentId;
		await tick();

		if (autoScroll) {
			scrollToBottom();
		}

		if (messages.length === 0) {
			await initChatHandler(history);
		} else {
			await saveChatHandler($chatId, history);
		}
	};

	const finalizeCompletedAssistantMessage = async (
		chatId: string,
		message: Record<string, any>,
		{ runBackgroundCompletion = true } = {}
	) => {
		message.done = true;
		bumpArtifactExplorerRefresh();

		if (chatId && !chatId.startsWith('local:')) {
			setTimeout(() => clearInflightSnapshot(chatId), 10_000);
		}

		if ($settings.responseAutoCopy) {
			copyToClipboard(message.content);
		}

		if ($settings.responseAutoPlayback) {
			await tick();
			document.getElementById(`speak-button-${message.id}`)?.click();
		}

		eventTarget.dispatchEvent(
			new CustomEvent('chat:finish', {
				detail: {
					id: message.id,
					content: message.content
				}
			})
		);

		history.messages[message.id] = message;

		await tick();
		if (autoScroll) {
			scrollToBottom();
		}

		if (runBackgroundCompletion) {
			chatCompletedHandler(chatId, message.model, message.id, createMessagesList(history, message.id));
		}

		// ── Auto-link chat to cron process ────────────────────────────
		// When the agent creates a cron job, link this chat to the process
		// so it shows a clock icon in the task list instead of a checkmark.
		if (message.output && Array.isArray(message.output)) {
			for (const item of message.output) {
				if (item.type !== 'function_call_output' || !item.call_id) continue;
				// Find the matching function_call to check the tool name
				const callItem = message.output.find(
					(o: any) => o.type === 'function_call' && o.call_id === item.call_id && o.name === 'cronjob'
				);
				if (!callItem) continue;
				// Parse the tool result to find job_id
				try {
					const resultText = item.output?.[0]?.text ?? '';
					const result = JSON.parse(resultText);
					if (result?.success && result?.job_id) {
						// Skip temp chats — they have no persistent ID to link against
						if (!chatId || chatId.startsWith('local:')) continue;

						const attemptLink = async (retryCount = 0): Promise<void> => {
							try {
								await linkProcessToChat(localStorage.token, result.job_id, chatId);
							} catch (e) {
								if (retryCount < 1) {
									await new Promise((res) => setTimeout(res, 2000));
									return attemptLink(retryCount + 1);
								}
								console.warn('[chat] Failed to link process to chat after retries:', e);
								toast.error('Failed to link scheduled task to this chat');
							}
						};
						attemptLink();
					}
				} catch {
					// Not JSON or no job_id — skip
				}
			}
		}

		// Process next queued request if any
		await processNextInQueue(chatId);
	};

	const chatCompletionEventHandler = async (data, message, chatId) => {
		const { id, done, choices, content, output, sources, selected_model_id, error, usage } = data;

		// Store raw OR-aligned output items from backend
		if (output) {
			message.output = output;
		}

		if (error) {
			await handleOpenAIError(error, message);
		}

		if (choices) {
			if (choices[0]?.message?.content) {
				// Non-stream response
				message.content += choices[0]?.message?.content;
			} else {
				// Stream response
				let value = choices[0]?.delta?.content ?? '';
				if (message.content == '' && value == '\n') {
					console.log('Empty response');
				} else {
					message.content += value;

					if (navigator.vibrate && ($settings?.hapticFeedback ?? false)) {
						navigator.vibrate(5);
					}
				}
			}
		}

		if (content) {
			// REALTIME_CHAT_SAVE is disabled
			message.content = content;

			if (navigator.vibrate && ($settings?.hapticFeedback ?? false)) {
				navigator.vibrate(5);
			}
		}

		if (selected_model_id) {
			message.selectedModelId = selected_model_id;
		}

		if (usage) {
			message.usage = usage;
		}

		history.messages[message.id] = message;

		if (done) {
			if (DEBUG_CHAT) {
				// Dump the complete message content on completion — this contains all
				// <details type="reasoning">, <details type="tool_calls">, and plain text.
				// Copy this from the console to diagnose thinking/tool-call rendering bugs.
				console.groupCollapsed(`[chat:done] msgId=${message.id} — click to expand full content`);
				console.log('[chat:done] raw content:\n' + message.content);
				console.log(
					'[chat:done] statusHistory:',
					JSON.parse(JSON.stringify(message.statusHistory ?? []))
				);
				console.log('[chat:done] output:', message.output ?? null);
				console.groupEnd();
			}

			await finalizeCompletedAssistantMessage(chatId, message);
		}


		if (DEBUG_CHAT) console.log('[chat:completion] done handler', data);
		await tick();

		if (autoScroll) {
			scheduleScrollToBottom();
		}
	};

	//////////////////////////
	// Chat functions
	//////////////////////////

	// When a UI component fires a ui-interaction event in a normal chat context
	// (no process jobId), translate the action into a user message and submit it.
	async function handleUIInteraction(event: CustomEvent) {
		const detail = event.detail ?? {};
		const { action, payload, type, toolCallId, formId, data, submitAction, composition } = detail;
		const envelopeData = {
			type: type ?? 'ui:action',
			action: submitAction ?? action ?? type ?? 'unknown',
			composition: composition ?? '',
			...(toolCallId ? { toolCallId } : {}),
			payload: payload ?? {},
			formId: formId ?? '',
			data: data ?? {}
		};
		const envelope = `[UI_ACTION]\n${JSON.stringify(envelopeData)}\n[/UI_ACTION]`;
		await submitPrompt(envelope, { _agui_interaction: true });
	}

	const submitPrompt = async (userPrompt, { _raw = false, _agui_interaction = false } = {}) => {
		// selectedModels[i] may be bare model.id (legacy) or composite selection_key
		// (after the user picks a row from the dropdown). Accept either form when
		// validating — same pattern as the ModelSelector wrapper. Without this,
		// composite picks get reset to '' and the user sees "Model not selected"
		// even though they just clicked a valid row.
		const validKeys = new Set($models.flatMap((m) => [m.id, m.selection_key].filter(Boolean)));
		const _selectedModels = selectedModels.map((modelId) =>
			validKeys.has(modelId) ? modelId : ''
		);

		if (JSON.stringify(selectedModels) !== JSON.stringify(_selectedModels)) {
			selectedModels = _selectedModels;
		}

		if (pendingOAuthTools.length > 0) {
			toast.warning($i18n.t('Please connect all required integrations before sending a message'));
			return;
		}
		if (userPrompt === '' && files.length === 0) {
			toast.error($i18n.t('Please enter a prompt'));
			return;
		}
		if (selectedModels.includes('')) {
			toast.error($i18n.t('Model not selected'));
			return;
		}

		if (
			files.length > 0 &&
			files.filter((file) => file.type !== 'image' && file.status === 'uploading').length > 0
		) {
			toast.error(
				$i18n.t(`Oops! There are files still uploading. Please wait for the upload to complete.`)
			);
			return;
		}

		if (
			($config?.file?.max_count ?? null) !== null &&
			files.length + chatFiles.length > $config?.file?.max_count
		) {
			toast.error(
				$i18n.t(`You can only chat with a maximum of {{maxCount}} file(s) at a time.`, {
					maxCount: $config?.file?.max_count
				})
			);
			return;
		}

		// Check if the assistant is still generating the main response
		// (don't block on background tasks like title gen, follow-ups, tags)
		const lastMessage = history.currentId ? history.messages[history.currentId] : null;
		const isGenerating = lastMessage && lastMessage.role === 'assistant' && !lastMessage.done;

		if (isGenerating) {
			if ($settings?.enableMessageQueue ?? true) {
				// Enqueue the request
				const _files = structuredClone(files);
				chatRequestQueues.update((q) => ({
					...q,
					[$chatId]: [...(q[$chatId] ?? []), { id: uuidv4(), prompt: userPrompt, files: _files }]
				}));
				// Clear input
				messageInput?.setText('');
				prompt = '';
				files = [];
				return;
			} else {
				// Interrupt: stop current generation and proceed
				await stopResponse();
				await tick();
			}
		}

		if (history?.currentId) {
			const currentMessage = history.messages[history.currentId];

			if (currentMessage.error && !currentMessage.content) {
				// Error in response
				toast.error($i18n.t(`Oops! There was an error in the previous response.`));
				return;
			}
		}

		messageInput?.setText('');
		prompt = '';

		const messages = createMessagesList(history, history.currentId);
		const _files = structuredClone(files);

		chatFiles.push(
			..._files.filter(
				(item) =>
					['doc', 'text', 'note', 'chat', 'folder', 'collection'].includes(item.type) ||
					(item.type === 'file' && !(item?.content_type ?? '').startsWith('image/'))
			)
		);
		chatFiles = chatFiles.filter(
			// Remove duplicates
			(item, index, array) =>
				array.findIndex((i) => JSON.stringify(i) === JSON.stringify(item)) === index
		);

		files = [];
		messageInput?.setText('');

		// Snapshot the composer's selection refs at send time so the user
		// message carries them in chat history (rendered as chips above the
		// bubble) AND so the API messages array build can prepend the
		// referenced content to the prompt (so the agent actually sees what
		// the user highlighted). Cleared from the global store after the
		// snapshot — the composer should be empty after sending.
		const _userRefs = get(composerRefs);

		// Create user message
		let userMessageId = uuidv4();
		let userMessage = {
			id: userMessageId,
			parentId: messages.length !== 0 ? messages.at(-1).id : null,
			childrenIds: [],
			role: 'user',
			content: userPrompt,
			files: _files.length > 0 ? _files : undefined,
			// 2026-05-05 dogfooding: persist selection refs on the message
			// itself so chat history reflects what the user attached. Each
			// ref is the same shape the SelectionToolbar pushed into
			// composerRefs (kind / filename / summary / preview / anchor).
			...(_userRefs.length > 0 ? { refs: _userRefs } : {}),
			timestamp: Math.floor(Date.now() / 1000), // Unix epoch
			models: selectedModels,
			// annotation: persisted to DB, read by middleware to detect UI action messages
			...(_agui_interaction ? { annotation: { type: 'ui-action' } } : {})
		};

		// Add message to history and Set currentId to messageId
		history.messages[userMessageId] = userMessage;
		history.currentId = userMessageId;

		// Append messageId to childrenIds of parent message
		if (messages.length !== 0) {
			history.messages[messages.at(-1).id].childrenIds.push(userMessageId);
		}

		// focus on chat input
		const chatInput = document.getElementById('chat-input');
		chatInput?.focus();

		saveSessionSelectedModels();

		await sendMessage(history, userMessageId, { newChat: true });
	};

	const sendMessage = async (
		_history,
		parentId: string,
		{
			messages = null,
			modelId = null,
			newChat = false
		}: {
			messages?: any[] | null;
			modelId?: string | null;
			newChat?: boolean;
		} = {}
	) => {
		if (autoScroll) {
			scrollToBottom();
		}

		let _chatId = JSON.parse(JSON.stringify($chatId));
		_history = structuredClone(_history);

		// Resolve the single model to use. `findModelByIdOrSelectionKey` accepts
		// both composite picks (post-T3-1031) and bare ids (legacy `default_model`
		// shapes) — needed because `ensureSelectionKey` always sets `m.selection_key`
		// on $models, making the inline `(m.selection_key ?? m.id)` pattern silently
		// drop bare-id lookups and trip this toast on a fresh chat's first send.
		const resolvedModelId = modelId ?? atSelectedModel?.id ?? selectedModels[0];
		const model = findModelByIdOrSelectionKey(resolvedModelId, $models);

		if (!model) {
			toast.error($i18n.t(`Model {{modelId}} not found`, { modelId: resolvedModelId }));
			return;
		}

		// Create the single response message
		const responseMessageId = uuidv4();
		const responseMessage = {
			parentId,
			id: responseMessageId,
			childrenIds: [],
			role: 'assistant',
			content: '',
			model: model.id,
			modelName: model.name ?? model.id,
			timestamp: Math.floor(Date.now() / 1000) // Unix epoch
		};

		// Add message to history and set currentId
		history.messages[responseMessageId] = responseMessage;
		history.currentId = responseMessageId;

		// Append responseMessageId to childrenIds of parent
		if (parentId !== null && history.messages[parentId]) {
			history.messages[parentId].childrenIds = [
				...history.messages[parentId].childrenIds,
				responseMessageId
			];
		}

		history = history;

		// Create new chat if newChat is true and first user message
		if (newChat && _history.messages[_history.currentId].parentId === null) {
			// Derive a provisional title from the first user message content
			const firstUserMsg = _history.messages[_history.currentId];
			const rawContent = firstUserMsg?.content;
			let titleText: string;
			if (Array.isArray(rawContent)) {
				const textPart = rawContent.find((p: any) => p.type === 'text');
				titleText = textPart?.text ?? '';
			} else {
				titleText = rawContent ?? '';
			}
			const provisionalTitle = titleText
				? titleText.length > 64
					? titleText.slice(0, 64) + '…'
					: titleText
				: $i18n.t('New Chat');
			_chatId = await initChatHandler(_history, provisionalTitle);
		}

		await tick();

		_history = structuredClone(history);

		// Check vision capability
		const hasImages = createMessagesList(_history, parentId).some((message) =>
			message.files?.some(
				(file) => file.type === 'image' || (file?.content_type ?? '').startsWith('image/')
			)
		);

		if (hasImages && !(model.info?.meta?.capabilities?.vision ?? true)) {
			toast.error(
				$i18n.t('Model {{modelName}} is not vision capable', {
					modelName: model.name ?? model.id
				})
			);
		}

		const chatEventEmitter = await getChatEventEmitter(model.id, _chatId);

		// Save chat and start agent request concurrently
		await Promise.all([
			saveChatHandler(_chatId, _history),
			sendMessageSocket(
				model,
				messages && messages.length > 0
					? messages
					: createMessagesList(_history, responseMessageId),
				_history,
				responseMessageId,
				_chatId
			)
		]);

		if (chatEventEmitter) clearInterval(chatEventEmitter);
	};

	const getFeatures = () => {
		let features = {};

		if ($config?.features)
			features = {
				web_search:
					$config?.features?.enable_web_search &&
					($user?.role === 'admin' || $user?.permissions?.features?.web_search)
						? webSearchEnabled
						: false
			};

		const currentModelId = atSelectedModel?.id ?? selectedModels[0];
		const currentModel = findModelByIdOrSelectionKey(currentModelId, $models);
		if (currentModel?.info?.meta?.capabilities?.web_search ?? true) {
			if ($config?.features?.enable_web_search && ($settings?.webSearch ?? false) === 'always') {
				features = { ...features, web_search: true };
			}
		}

		return features;
	};

	const getStopTokens = () => {
		const stop = params?.stop ?? $settings?.params?.stop;
		if (!stop) return undefined;

		const tokens = Array.isArray(stop) ? stop : stop.split(',').map((s) => s.trim());

		return tokens
			.filter(Boolean)
			.map((token) => decodeURIComponent(JSON.parse(`"${token.replace(/"/g, '\\"')}"`)));
	};

	const sendMessageSocket = async (model, _messages, _history, responseMessageId, _chatId) => {
		const responseMessage = _history.messages[responseMessageId];
		const userMessage = _history.messages[responseMessage.parentId];

		// Tag this message's Sentry context (non-blocking, best-effort)
		import('@sentry/sveltekit')
			.then((S) => {
				S.setTag('message_id', responseMessageId);
			})
			.catch(() => {});

		const chatMessageFiles = _messages
			.filter((message) => message.files)
			.flatMap((message) => message.files);

		// Filter chatFiles to only include files that are in the chatMessageFiles
		chatFiles = chatFiles.filter((item) => {
			const fileExists = chatMessageFiles.some((messageFile) => messageFile.id === item.id);
			return fileExists;
		});

		let files = structuredClone(chatFiles);
		files.push(
			...(userMessage?.files ?? []).filter(
				(item) =>
					['doc', 'text', 'note', 'chat', 'collection'].includes(item.type) ||
					(item.type === 'file' && !(item?.content_type ?? '').startsWith('image/'))
			)
		);
		// Remove duplicates
		files = files.filter(
			(item, index, array) =>
				array.findIndex((i) => JSON.stringify(i) === JSON.stringify(item)) === index
		);

		scrollToBottom();
		eventTarget.dispatchEvent(
			new CustomEvent('chat:start', {
				detail: {
					id: responseMessageId
				}
			})
		);
		await tick();

		let userLocation;
		if ($settings?.userLocation) {
			userLocation = await getAndUpdateUserLocation(localStorage.token).catch((err) => {
				console.error(err);
				return undefined;
			});
		}

		const stream =
			model?.info?.params?.stream_response ??
			$settings?.params?.stream_response ??
			params?.stream_response ??
			true;

		let messages = [
			params?.system || $settings.system
				? {
						role: 'system',
						content: `${params?.system ?? $settings?.system ?? ''}`
					}
				: undefined,
			..._messages.map((message) => ({
				...message,
				content: processDetails(message.content),
				// Include output for temp chats (backend will use it and strip before LLM)
				...(message.output ? { output: message.output } : {})
			}))
		].filter((message) => message);

		messages = messages
			.map((message, idx, arr) => {
				const imageFiles = (message?.files ?? []).filter(
					(file) => file.type === 'image' || (file?.content_type ?? '').startsWith('image/')
				);

				// Note: selection refs (the chips above each user message) are
				// shipped via the separate `ui_state` body field on the request
				// — see `assembleUIState` below. The backend's
				// `prepend_user_ref_block` reads `ui_state.selectionRefs` and
				// builds the [USER_REFERENCED] context block server-side
				// before the message reaches Hermes. Doing the injection on
				// the backend avoids the frontend-lifecycle pitfalls (regen
				// path, temp chat path, structuredClone drops) that this code
				// previously had to navigate. The chat bubble keeps rendering
				// the pristine user prose via `message.content`.
				const _wireText = message?.merged?.content ?? message.content;

				return {
					role: message.role,
					// Preserve output items so backend can reconstruct tool_calls/tool-role messages (temp chats)
					...(message.output ? { output: message.output } : {}),
					...(message.role === 'user' && imageFiles.length > 0
						? {
								content: [
									{
										type: 'text',
										text: _wireText
									},
									...imageFiles.map((file) => ({
										type: 'image_url',
										image_url: {
											url: file.url
										}
									}))
								]
							}
						: {
								content: _wireText
							})
				};
			})
			.filter((message) => message?.role === 'user' || message?.content?.trim());

		const toolIds = [];
		const toolServerIds = [];

		for (const toolId of selectedToolIds) {
			if (toolId.startsWith('direct_server:')) {
				let serverId = toolId.replace('direct_server:', '');
				// Check if serverId is a number
				if (!isNaN(parseInt(serverId))) {
					toolServerIds.push(parseInt(serverId));
				} else {
					toolServerIds.push(serverId);
				}
			} else {
				toolIds.push(toolId);
			}
		}

		// Parse skill mentions (<$skillId|label>) from user messages
		const skillMentionRegex = /<\$([^|>]+)\|?[^>]*>/g;
		const skillIds = [];
		for (const message of messages) {
			const content =
				typeof message.content === 'string' ? message.content : (message.content?.[0]?.text ?? '');
			for (const match of content.matchAll(skillMentionRegex)) {
				if (!skillIds.includes(match[1])) {
					skillIds.push(match[1]);
				}
			}
		}

		// Strip skill mentions from message content
		if (skillIds.length > 0) {
			messages = messages.map((message) => {
				if (typeof message.content === 'string') {
					return {
						...message,
						content: message.content.replace(/<\$[^>]+>/g, '').trim()
					};
				} else if (Array.isArray(message.content)) {
					return {
						...message,
						content: message.content.map((part) =>
							part.type === 'text'
								? { ...part, text: part.text.replace(/<\$[^>]+>/g, '').trim() }
								: part
						)
					};
				}
				return message;
			});
		}

		// Assemble per-turn UI state (selectionRefs + pendingEdits) so the
		// agent receives ground truth about what the user is looking at.
		// Spec §7. composerRefs are cleared after send; pendingEdits survive
		// until the agent's edit lands or the user discards.
		const _uiState = assembleUIState(get(composerRefs), get(artifactPendingEdits));
		composerRefs.set([]);

		const res = await generateOpenAIChatCompletion(
			localStorage.token,
			{
				stream: stream,
				model: model.id,
				messages: messages,
				ui_state: _uiState,
				params: {
					...$settings?.params,
					...params,
					stop: getStopTokens()
				},

				files: (files?.length ?? 0) > 0 ? files : undefined,

				tool_ids: toolIds.length > 0 ? toolIds : undefined,
				skill_ids: skillIds.length > 0 ? skillIds : undefined,
				tool_servers: [],
				features: getFeatures(),
				variables: {
					...getPromptVariables(
						$user?.name,
						$settings?.userLocation ? userLocation : undefined,
						$user?.email
					)
				},
				// model is the resolved row (composite-aware lookup above) — reuse it
				// directly so the chat completion payload's model_item carries the
				// exact provider tags the user selected, not a same-id duplicate.
				model_item: model,

				session_id: $socket?.id,
				chat_id: $chatId,
				folder_id: $selectedFolder?.id ?? undefined,

				id: responseMessageId,
				parent_id: userMessage?.id ?? null,
				parent_message: userMessage,

				background_tasks: {
					...(!$temporaryChatEnabled &&
					(messages.length == 1 ||
						(messages.length == 2 &&
							messages.at(0)?.role === 'system' &&
							messages.at(1)?.role === 'user')) &&
					(selectionMatchesModel(selectedModels[0], model) || atSelectedModel !== undefined)
						? {
								title_generation: $settings?.title?.auto ?? true,
								tags_generation: $settings?.autoTags ?? true
							}
						: {}),
					follow_up_generation: $settings?.autoFollowUps ?? true
				},

				...(stream && (model.info?.meta?.capabilities?.usage ?? false)
					? {
							stream_options: {
								include_usage: true
							}
						}
					: {})
			},
			`${MYAH_BASE_URL}/api`
		).catch(async (error) => {
			console.log(error);

			let errorMessage = error;
			if (error?.error?.message) {
				errorMessage = error.error.message;
			} else if (error?.message) {
				errorMessage = error.message;
			}

			if (typeof errorMessage === 'object') {
				errorMessage = $i18n.t(`Uh-oh! There was an issue with the response.`);
			}

			toast.error(`${errorMessage}`);
			responseMessage.error = {
				content: error
			};

			responseMessage.done = true;

			history.messages[responseMessageId] = responseMessage;
			history.currentId = responseMessageId;

			return null;
		});

		if (res) {
			if (res.error) {
				await handleOpenAIError(res.error, responseMessage);
			} else {
				if (taskIds) {
					taskIds.push(res.task_id);
				} else {
					taskIds = [res.task_id];
				}
			}
		}

		await tick();
		scrollToBottom();
	};

	const handleOpenAIError = async (error, responseMessage) => {
		let errorMessage = '';
		let innerError;

		if (error) {
			innerError = error;
		}

		console.error(innerError);
		if ('detail' in innerError) {
			// FastAPI error
			toast.error(innerError.detail);
			errorMessage = innerError.detail;
		} else if ('error' in innerError) {
			// OpenAI error
			if ('message' in innerError.error) {
				toast.error(innerError.error.message);
				errorMessage = innerError.error.message;
			} else {
				toast.error(innerError.error);
				errorMessage = innerError.error;
			}
		} else if ('message' in innerError) {
			// OpenAI error
			toast.error(innerError.message);
			errorMessage = innerError.message;
		}

		responseMessage.error = {
			content: $i18n.t(`Uh-oh! There was an issue with the response.`) + '\n' + errorMessage
		};
		responseMessage.done = true;
		history.messages[responseMessage.id] = responseMessage;
	};

	const stopResponse = async () => {
		if (taskIds) {
			for (const taskId of taskIds) {
				const res = await stopTask(localStorage.token, taskId).catch((error) => {
					toast.error(`${error}`);
					return null;
				});
			}

			taskIds = null;

			const responseMessage = history.messages[history.currentId];
			// Set all response messages to done
			if (responseMessage.parentId && history.messages[responseMessage.parentId]) {
				for (const messageId of history.messages[responseMessage.parentId].childrenIds) {
					history.messages[messageId].done = true;
				}
			}

			history.messages[history.currentId] = responseMessage;

			if (autoScroll) {
				scrollToBottom();
			}
		}

		if (generating) {
			generating = false;
			generationController?.abort();
			generationController = null;
		}

		await processNextInQueue($chatId);
	};

	const submitMessage = async (parentId, prompt) => {
		let userPrompt = prompt;
		let userMessageId = uuidv4();

		let userMessage = {
			id: userMessageId,
			parentId: parentId,
			childrenIds: [],
			role: 'user',
			content: userPrompt,
			models: selectedModels,
			timestamp: Math.floor(Date.now() / 1000) // Unix epoch
		};

		if (parentId !== null) {
			history.messages[parentId].childrenIds = [
				...history.messages[parentId].childrenIds,
				userMessageId
			];
		}

		history.messages[userMessageId] = userMessage;
		history.currentId = userMessageId;

		await tick();

		if (autoScroll) {
			scrollToBottom();
		}

		await sendMessage(history, userMessageId);
	};

	// Workstream H Path 2 cleanup: regenerateResponse / continueResponse were
	// removed because they conflict with the Hermes-aligned identity model
	// (append-only SessionDB; Honcho turn extraction; immutable compression
	// history). See cleanup note in Messages.svelte for the full rationale.

	const initChatHandler = async (history, provisionalTitle?: string) => {
		let _chatId = $chatId;

		if (!$temporaryChatEnabled) {
			chat = await createNewChat(
				localStorage.token,
				{
					id: _chatId,
					title: provisionalTitle ?? $i18n.t('New Chat'),
					models: selectedModels,
					system: $settings.system ?? undefined,
					params: params,
					history: history,
					messages: createMessagesList(history, history.currentId),
					tags: [],
					timestamp: Date.now()
				},
				$selectedFolder?.id
			);

			_chatId = chat.id;
			await chatId.set(_chatId);

			window.history.replaceState(history.state, '', `/c/${_chatId}`);

			await tick();

			await chats.set(await getChatList(localStorage.token, $currentChatPage));
			currentChatPage.set(1);

			selectedFolder.set(null);

			// Tag the chat as auto-titled so later renames are preserved
			if (provisionalTitle) {
				await updateChatById(localStorage.token, _chatId, {}, { titleSource: 'auto' });
			}
		} else {
			_chatId = `local:${$socket?.id}`; // Use socket id for temporary chat
			await chatId.set(_chatId);
		}
		await tick();

		return _chatId;
	};

	const saveChatHandler = async (_chatId, history) => {
		if ($chatId == _chatId) {
			if (!$temporaryChatEnabled) {
				chat = await updateChatById(localStorage.token, _chatId, {
					models: selectedModels,
					history: history,
					messages: createMessagesList(history, history.currentId),
					params: params,
					files: chatFiles
				});
			}
		}
	};

	const MAX_DRAFT_LENGTH = 5000;
	let saveDraftTimeout: ReturnType<typeof setTimeout> | null = null;

	const saveDraft = async (draft, chatId = null) => {
		if (saveDraftTimeout) {
			clearTimeout(saveDraftTimeout);
		}

		if (draft.prompt !== null && draft.prompt.length < MAX_DRAFT_LENGTH) {
			saveDraftTimeout = setTimeout(async () => {
				await sessionStorage.setItem(
					`chat-input${chatId ? `-${chatId}` : ''}`,
					JSON.stringify(draft)
				);
			}, 500);
		} else {
			sessionStorage.removeItem(`chat-input${chatId ? `-${chatId}` : ''}`);
		}
	};

	const clearDraft = async (chatId = null) => {
		if (saveDraftTimeout) {
			clearTimeout(saveDraftTimeout);
		}
		await sessionStorage.removeItem(`chat-input${chatId ? `-${chatId}` : ''}`);
	};

	const moveChatHandler = async (chatId, folderId) => {
		if (chatId && folderId) {
			const res = await updateChatFolderIdById(localStorage.token, chatId, folderId).catch(
				(error) => {
					toast.error(`${error}`);
					return null;
				}
			);

			if (res) {
				currentChatPage.set(1);
				await chats.set(await getChatList(localStorage.token, $currentChatPage));
				await pinnedChats.set(await getPinnedChatList(localStorage.token));

				toast.success($i18n.t('Chat moved successfully'));
			}
		} else {
			toast.error($i18n.t('Failed to move chat'));
		}
	};

	const archiveChatHandler = async (id: string) => {
		try {
			await archiveChatById(localStorage.token, id);
			currentChatPage.set(1);
			initNewChat();
			await goto('/');
			chats.set(await getChatList(localStorage.token, $currentChatPage));
			pinnedChats.set(await getPinnedChatList(localStorage.token));
			toast.success($i18n.t('Chat archived.'));
		} catch (error) {
			console.error('Error archiving chat:', error);
			toast.error($i18n.t('Failed to archive chat.'));
		}
	};

	const deleteChatHandler = async (id: string) => {
		if (!confirm($i18n.t('Are you sure you want to delete this chat?'))) return;
		try {
			await deleteChatById(localStorage.token, id);
			currentChatPage.set(1);
			initNewChat();
			await goto('/');
			chats.set(await getChatList(localStorage.token, $currentChatPage));
			pinnedChats.set(await getPinnedChatList(localStorage.token));
			toast.success($i18n.t('Chat deleted.'));
		} catch (error) {
			console.error('Error deleting chat:', error);
			toast.error($i18n.t('Failed to delete chat.'));
		}
	};
</script>

<svelte:head>
	<title>
		{$settings.showChatTitleInTab !== false && $chatTitle
			? `${$chatTitle.length > 30 ? `${$chatTitle.slice(0, 30)}...` : $chatTitle} • ${$MYAH_NAME}`
			: `${$MYAH_NAME}`}
	</title>
</svelte:head>

<audio id="audioElement" src="" style="display: none;"></audio>

<EventConfirmDialog
	bind:show={showEventConfirmation}
	title={eventConfirmationTitle}
	message={eventConfirmationMessage}
	input={eventConfirmationInput}
	inputPlaceholder={eventConfirmationInputPlaceholder}
	inputValue={eventConfirmationInputValue}
	inputType={eventConfirmationInputType}
	on:confirm={(e) => {
		if (e.detail) {
			eventCallback(e.detail);
		} else {
			eventCallback(true);
		}
	}}
	on:cancel={() => {
		eventCallback(false);
	}}
/>

<div
	class="{embedded
		? 'h-full'
		: 'h-screen max-h-[100dvh]'} transition-width duration-200 ease-in-out {!embedded &&
	$showSidebar
		? '  md:max-w-[calc(100%-var(--sidebar-width))]'
		: ' '} w-full max-w-full flex flex-col"
	id="chat-container"
>
	{#if !loading}
		<div in:fade={{ duration: 50 }} class="w-full h-full flex flex-col">
			{#if $selectedFolder && $selectedFolder?.meta?.background_image_url}
				<div
					class="absolute top-0 left-0 w-full h-full bg-cover bg-center bg-no-repeat"
					style="background-image: url({$selectedFolder?.meta?.background_image_url})  "
				/>

				<div
					class="absolute top-0 left-0 w-full h-full bg-linear-to-t from-white to-white/85 dark:from-gray-900 dark:to-gray-900/90 z-0"
				/>
			{:else if $settings?.backgroundImageUrl ?? $config?.license_metadata?.background_image_url ?? null}
				<div
					class="absolute top-0 left-0 w-full h-full bg-cover bg-center bg-no-repeat"
					style="background-image: url({$settings?.backgroundImageUrl ??
						$config?.license_metadata?.background_image_url})  "
				/>

				<div
					class="absolute top-0 left-0 w-full h-full bg-linear-to-t from-white to-white/85 dark:from-gray-900 dark:to-gray-900/90 z-0"
				/>
			{/if}

			<PaneGroup direction="horizontal" class="w-full h-full">
				<Pane defaultSize={70} minSize={30} class="h-full flex relative max-w-full flex-col">
					<FilesOverlay show={dragged} />
					<Navbar
						bind:this={navbarElement}
						chat={{
							id: $chatId,
							chat: {
								title: $chatTitle,
								models: selectedModels,
								system: $settings.system ?? undefined,
								params: params,
								history: history,
								timestamp: Date.now()
							}
						}}
						{history}
						title={$chatTitle}
						bind:selectedModels
						{initNewChat}
						{archiveChatHandler}
						{deleteChatHandler}
						{moveChatHandler}
						{embedded}
						{linkedProcess}
						on:back
						on:expand
						onSaveTempChat={async () => {
							try {
								if (!history?.currentId || !Object.keys(history.messages).length) {
									toast.error($i18n.t('No conversation to save'));
									return;
								}
								const messages = createMessagesList(history, history.currentId);
								const title =
									messages.find((m) => m.role === 'user')?.content ?? $i18n.t('New Chat');

								const savedChat = await createNewChat(
									localStorage.token,
									{
										id: uuidv4(),
										title: title.length > 50 ? `${title.slice(0, 50)}...` : title,
										models: selectedModels,
										params: params,
										history: history,
										messages: messages,
										timestamp: Date.now()
									},
									null
								);

								if (savedChat) {
									temporaryChatEnabled.set(false);
									chatId.set(savedChat.id);
									chats.set(await getChatList(localStorage.token, $currentChatPage));

									await goto(`/c/${savedChat.id}`);
									toast.success($i18n.t('Conversation saved successfully'));
								}
							} catch (error) {
								console.error('Error saving conversation:', error);
								toast.error($i18n.t('Failed to save conversation'));
							}
						}}
					/>

					<ReconnectBanner />
					<TodoPlanStrip plan={pinnedTodoPlan} />

					<div id="chat-pane" class="flex flex-col flex-auto z-10 w-full @container overflow-auto">
						{#if ($settings?.landingPageMode === 'chat' && !$selectedFolder) || createMessagesList(history, history.currentId).length > 0}
							<div
								class=" pb-2.5 flex flex-col justify-between w-full flex-auto overflow-auto h-0 max-w-full z-10 scrollbar-hidden"
								id="messages-container"
								bind:this={messagesContainerElement}
								on:scroll={(e) => {
									autoScroll =
										messagesContainerElement.scrollHeight - messagesContainerElement.scrollTop <=
										messagesContainerElement.clientHeight + 5;
								}}
							>
								<div class=" h-full w-full flex flex-col">
									<Messages
										chatId={$chatId}
										bind:history
										bind:autoScroll
										bind:prompt
										setInputText={(text) => {
											messageInput?.setText(text);
										}}
										{selectedModels}
										{atSelectedModel}
										{sendMessage}
										{showMessage}
										{submitMessage}
										{chatActionHandler}
										{addMessages}
										topPadding={true}
										bottomPadding={files.length > 0}
										{onSelect}
										on:ui-interaction={handleUIInteraction}
									/>
								</div>
							</div>

							<div class=" pb-2 {dragged ? 'z-0' : 'z-10'}">
								<MessageInput
									bind:this={messageInput}
									{history}
									{taskIds}
									{selectedModels}
									bind:files
									bind:prompt
									bind:autoScroll
									bind:selectedToolIds
									{pendingOAuthTools}
									bind:webSearchEnabled
									bind:atSelectedModel
									bind:showCommands
									bind:dragged
									{generating}
									{stopResponse}
									{createMessagePair}
									{onUpload}
									messageQueue={$chatRequestQueues[$chatId] ?? []}
									onQueueSendNow={async (id) => {
										const queue = $chatRequestQueues[$chatId] ?? [];
										const item = queue.find((m) => m.id === id);
										if (item) {
											// Remove from queue
											chatRequestQueues.update((q) => ({
												...q,
												[$chatId]: queue.filter((m) => m.id !== id)
											}));
											// Stop current generation first
											await stopResponse();
											await tick();
											// Set files and submit
											files = item.files;
											await tick();
											await submitPrompt(item.prompt);
										}
									}}
									onQueueEdit={(id) => {
										const queue = $chatRequestQueues[$chatId] ?? [];
										const item = queue.find((m) => m.id === id);
										if (item) {
											// Remove from queue
											chatRequestQueues.update((q) => ({
												...q,
												[$chatId]: queue.filter((m) => m.id !== id)
											}));
											// Set files and restore prompt to input
											files = item.files;
											messageInput?.setText(item.prompt);
										}
									}}
									onQueueDelete={(id) => {
										const queue = $chatRequestQueues[$chatId] ?? [];
										chatRequestQueues.update((q) => ({
											...q,
											[$chatId]: queue.filter((m) => m.id !== id)
										}));
									}}
									onChange={(data) => {
										if (!$temporaryChatEnabled) {
											saveDraft(data, $chatId);
										}
									}}
									on:submit={async (e) => {
										clearDraft();
										if (e.detail || files.length > 0) {
											await tick();

											submitPrompt(e.detail.replaceAll('\n\n', '\n'));
										}
									}}
								/>

								<div
									class="absolute bottom-1 text-xs text-gray-500 text-center line-clamp-1 right-0 left-0"
								>
									<!-- {$i18n.t('LLMs can make mistakes. Verify important information.')} -->
								</div>
							</div>
						{:else}
							<div class="flex items-center h-full">
								<Placeholder
									{history}
									{selectedModels}
									bind:messageInput
									bind:files
									bind:prompt
									bind:autoScroll
									bind:selectedToolIds
									bind:webSearchEnabled
									bind:atSelectedModel
									bind:showCommands
									bind:dragged
									{pendingOAuthTools}
									{stopResponse}
									{createMessagePair}
									{onSelect}
									{onUpload}
									onChange={(data) => {
										if (!$temporaryChatEnabled) {
											saveDraft(data);
										}
									}}
									on:submit={async (e) => {
										clearDraft();
										if (e.detail || files.length > 0) {
											await tick();
											submitPrompt(e.detail.replaceAll('\n\n', '\n'));
										}
									}}
								/>
							</div>
						{/if}
					</div>
				</Pane>

				{#if $artifactPaneOpen}
					<PaneResizer
						class="relative flex items-center justify-center group border-l border-gray-50 dark:border-gray-850/30 hover:border-gray-200 dark:hover:border-gray-800 transition z-20"
						id="artifact-resizer"
					>
						<div
							class="absolute -left-1.5 -right-1.5 -top-0 -bottom-0 z-20 cursor-col-resize bg-transparent"
						/>
					</PaneResizer>
					<Pane defaultSize={30} minSize={0} class="z-10 bg-white dark:bg-gray-850">
						<ArtifactPane chatId={$chatId} token={$user?.token ?? ''} />
					</Pane>
				{/if}
			</PaneGroup>
		</div>
	{:else if loading}
		<div class=" flex items-center justify-center h-full w-full">
			<div class="m-auto">
				<Spinner className="size-5" />
			</div>
		</div>
	{/if}
</div>

<style>
	::-webkit-scrollbar {
		height: 0.5rem;
		width: 0.5rem;
	}
</style>
