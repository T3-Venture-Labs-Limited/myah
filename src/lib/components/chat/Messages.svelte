<script lang="ts">
	import { v4 as uuidv4 } from 'uuid';
	import {
		chats,
		config,
		settings,
		user as _user,
		mobile,
		currentChatPage,
		temporaryChatEnabled
	} from '$lib/stores';
	import { tick, getContext, onMount, onDestroy, createEventDispatcher } from 'svelte';
	const dispatch = createEventDispatcher();

	import { toast } from 'svelte-sonner';
	import { getChatList, updateChatById } from '$lib/apis/chats';
	import { copyToClipboard, extractCurlyBraceWords } from '$lib/utils';

	import Message from './Messages/Message.svelte';
	import Loader from '../common/Loader.svelte';
	import Spinner from '../common/Spinner.svelte';

	import ChatPlaceholder from './ChatPlaceholder.svelte';

	const i18n = getContext('i18n');

	export let className = 'h-full flex pt-8';

	export let chatId = '';
	export let user = $_user;

	export let prompt;
	export let history = {};
	export let selectedModels;
	export let atSelectedModel;

	let messages = [];

	export let setInputText: Function = () => {};

	export let sendMessage: Function;

	export let chatActionHandler: Function;
	export let showMessage: Function = () => {};
	export let submitMessage: Function = () => {};
	export let addMessages: Function = () => {};

	export let readOnly = false;
	export let editCodeBlock = true;

	export let topPadding = false;
	export let bottomPadding = false;
	export let autoScroll;

	export let onSelect = (e) => {};

	export let messagesCount: number | null = 20;
	let messagesLoading = false;

	const loadMoreMessages = async () => {
		// scroll slightly down to disable continuous loading
		const element = document.getElementById('messages-container');
		element.scrollTop = element.scrollTop + 100;

		messagesLoading = true;
		messagesCount += 20;
		buildMessages();

		await tick();

		messagesLoading = false;
	};

	let pendingRebuild = null;
	let lastCurrentId = null;

	const buildMessages = () => {
		let _messages = [];

		let message = history.messages[history.currentId];
		const visitedMessageIds = new Set();

		while (message && (messagesCount !== null ? _messages.length <= messagesCount : true)) {
			if (visitedMessageIds.has(message.id)) {
				console.warn('Circular dependency detected in message history', message.id);
				break;
			}
			visitedMessageIds.add(message.id);

			_messages.push(message);
			message = message.parentId !== null ? history.messages[message.parentId] : null;
		}

		messages = _messages.reverse();
	};

	// Throttle message list rebuilds to once per animation frame during streaming.
	// Structural changes (currentId change) always rebuild immediately.
	const handleHistoryChange = (currentId, _messages) => {
		if (!currentId) {
			messages = [];
			return;
		}

		const currentIdChanged = currentId !== lastCurrentId;
		lastCurrentId = currentId;

		if (currentIdChanged) {
			// Structural change: new chat, navigation, new message — rebuild immediately
			cancelAnimationFrame(pendingRebuild);
			pendingRebuild = null;
			buildMessages();
		} else if (_messages) {
			// Content update (streaming) — throttle to once per frame
			if (!pendingRebuild) {
				pendingRebuild = requestAnimationFrame(() => {
					pendingRebuild = null;
					buildMessages();
				});
			}
		}
	};

	$: handleHistoryChange(history.currentId, history.messages);

	$: if (autoScroll && bottomPadding) {
		(async () => {
			await tick();
			scrollToBottom();
		})();
	}

	const scrollToBottom = () => {
		const element = document.getElementById('messages-container');
		element.scrollTop = element.scrollHeight;
	};

	const updateChat = async () => {
		if (!$temporaryChatEnabled) {
			history = history;
			await tick();
			await updateChatById(localStorage.token, chatId, {
				history: history,
				messages: messages
			});

			currentChatPage.set(1);
			await chats.set(await getChatList(localStorage.token, $currentChatPage));
		}
	};

	const gotoMessage = async (message, idx) => {
		// Determine the correct sibling list (either parent's children or root messages)
		let siblings;
		if (message.parentId !== null) {
			siblings = history.messages[message.parentId].childrenIds;
		} else {
			siblings = Object.values(history.messages)
				.filter((msg) => msg.parentId === null)
				.map((msg) => msg.id);
		}

		// Clamp index to a valid range
		idx = Math.max(0, Math.min(idx, siblings.length - 1));

		let messageId = siblings[idx];

		// If we're navigating to a different message
		if (message.id !== messageId) {
			// Drill down to the deepest child of that branch
			let messageChildrenIds = history.messages[messageId].childrenIds;
			while (messageChildrenIds.length !== 0) {
				messageId = messageChildrenIds.at(-1);
				messageChildrenIds = history.messages[messageId].childrenIds;
			}

			history.currentId = messageId;
		}

		await tick();

		// Optional auto-scroll
		if ($settings?.scrollOnBranchChange ?? true) {
			const element = document.getElementById('messages-container');
			autoScroll = element.scrollHeight - element.scrollTop <= element.clientHeight + 50;

			setTimeout(() => {
				scrollToBottom();
			}, 100);
		}
	};

	const showPreviousMessage = async (message) => {
		if (message.parentId !== null) {
			let messageId =
				history.messages[message.parentId].childrenIds[
					Math.max(history.messages[message.parentId].childrenIds.indexOf(message.id) - 1, 0)
				];

			if (message.id !== messageId) {
				let messageChildrenIds = history.messages[messageId].childrenIds;

				while (messageChildrenIds.length !== 0) {
					messageId = messageChildrenIds.at(-1);
					messageChildrenIds = history.messages[messageId].childrenIds;
				}

				history.currentId = messageId;
			}
		} else {
			let childrenIds = Object.values(history.messages)
				.filter((message) => message.parentId === null)
				.map((message) => message.id);
			let messageId = childrenIds[Math.max(childrenIds.indexOf(message.id) - 1, 0)];

			if (message.id !== messageId) {
				let messageChildrenIds = history.messages[messageId].childrenIds;

				while (messageChildrenIds.length !== 0) {
					messageId = messageChildrenIds.at(-1);
					messageChildrenIds = history.messages[messageId].childrenIds;
				}

				history.currentId = messageId;
			}
		}

		await tick();

		if ($settings?.scrollOnBranchChange ?? true) {
			const element = document.getElementById('messages-container');
			autoScroll = element.scrollHeight - element.scrollTop <= element.clientHeight + 50;

			setTimeout(() => {
				scrollToBottom();
			}, 100);
		}
	};

	const showNextMessage = async (message) => {
		if (message.parentId !== null) {
			let messageId =
				history.messages[message.parentId].childrenIds[
					Math.min(
						history.messages[message.parentId].childrenIds.indexOf(message.id) + 1,
						history.messages[message.parentId].childrenIds.length - 1
					)
				];

			if (message.id !== messageId) {
				let messageChildrenIds = history.messages[messageId].childrenIds;

				while (messageChildrenIds.length !== 0) {
					messageId = messageChildrenIds.at(-1);
					messageChildrenIds = history.messages[messageId].childrenIds;
				}

				history.currentId = messageId;
			}
		} else {
			let childrenIds = Object.values(history.messages)
				.filter((message) => message.parentId === null)
				.map((message) => message.id);
			let messageId =
				childrenIds[Math.min(childrenIds.indexOf(message.id) + 1, childrenIds.length - 1)];

			if (message.id !== messageId) {
				let messageChildrenIds = history.messages[messageId].childrenIds;

				while (messageChildrenIds.length !== 0) {
					messageId = messageChildrenIds.at(-1);
					messageChildrenIds = history.messages[messageId].childrenIds;
				}

				history.currentId = messageId;
			}
		}

		await tick();

		if ($settings?.scrollOnBranchChange ?? true) {
			const element = document.getElementById('messages-container');
			autoScroll = element.scrollHeight - element.scrollTop <= element.clientHeight + 50;

			setTimeout(() => {
				scrollToBottom();
			}, 100);
		}
	};

	const rateMessage = async (messageId, rating) => {
		history.messages[messageId].annotation = {
			...history.messages[messageId].annotation,
			rating: rating
		};

		await updateChat();
	};

	// Workstream H Path 2 cleanup: editMessage / deleteMessage / regenerate /
	// continueResponse handlers were removed because they conflict with the
	// Hermes-aligned identity model:
	//   * Hermes SessionDB is append-only — there is no rewrite primitive.
	//   * Honcho memory tracks turns by sequence; mutating past turns
	//     corrupts the user-model state.
	//   * Compression assumes immutable history when summarising.
	// The OWI fork inherited these features from upstream Open WebUI; they
	// don't fit a Hermes-native frontend. Re-introduce only by extending
	// Hermes' primitives (e.g. add a SessionDB ``edit_message`` op upstream)
	// — never by mutating ``chat.history.messages`` from the platform.

	const actionMessage = async (actionId, message, event = null) => {
		await chatActionHandler(chatId, actionId, message.model, message.id, event);
	};

	const saveMessage = async (messageId, message) => {
		if (!history.messages?.[messageId]) {
			return;
		}

		history.messages[messageId] = message;
		await updateChat();
	};

	onDestroy(() => {
		cancelAnimationFrame(pendingRebuild);
	});

	const triggerScroll = () => {
		if (autoScroll) {
			const element = document.getElementById('messages-container');
			autoScroll = element.scrollHeight - element.scrollTop <= element.clientHeight + 50;
			setTimeout(() => {
				scrollToBottom();
			}, 100);
		}
	};
</script>

<div class={className}>
	{#if Object.keys(history?.messages ?? {}).length == 0}
		<ChatPlaceholder modelIds={selectedModels} {atSelectedModel} {onSelect} />
	{:else}
		<div class="w-full pt-2">
			{#key chatId}
				<section class="w-full" aria-labelledby="chat-conversation">
					<h2 class="sr-only" id="chat-conversation">{$i18n.t('Chat Conversation')}</h2>
					{#if messages.at(0)?.parentId !== null}
						<Loader
							on:visible={(e) => {
								console.log('visible');
								if (!messagesLoading) {
									loadMoreMessages();
								}
							}}
						>
							<div class="w-full flex justify-center py-1 text-xs animate-pulse items-center gap-2">
								<Spinner className=" size-4" />
								<div class=" ">{$i18n.t('Loading...')}</div>
							</div>
						</Loader>
					{/if}
					<ul role="log" aria-live="polite" aria-relevant="additions" aria-atomic="false">
						{#each messages as message, messageIdx (message.id)}
							<Message
								{chatId}
								bind:history
								{selectedModels}
								messageId={message.id}
								idx={messageIdx}
								{user}
								{setInputText}
								{gotoMessage}
								{showPreviousMessage}
								{showNextMessage}
								{updateChat}
								{rateMessage}
								{actionMessage}
								{saveMessage}
								{sendMessage}
								{submitMessage}
								{addMessages}
								{readOnly}
								{editCodeBlock}
								{topPadding}
								on:ui-interaction
							/>
						{/each}
					</ul>
				</section>
				<div class="pb-18" />
				{#if bottomPadding}
					<div class="  pb-6" />
				{/if}
			{/key}
		</div>
	{/if}
</div>
