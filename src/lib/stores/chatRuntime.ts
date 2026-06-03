import { get, writable } from 'svelte/store';
import {
	applyChatRuntimeEvent,
	emptyChatRuntimeState,
	reconcileLoadedHistoryWithRuntime,
	seedChatRuntimeGraph,
	type ChatRuntimeChatState,
	type ChatRuntimeState,
	type ChatHistory
} from '$lib/utils/chatRuntimeProjection';

export const DEFAULT_CHAT_RUNTIME_MAX_AGE_MS = 10 * 60 * 1000;
export const DEFAULT_CHAT_RUNTIME_MAX_CHATS = 25;

type MergeHistoryOptions = {
	isolateToChat?: boolean;
};

function createChatRuntimeStore() {
	const store = writable<ChatRuntimeState>(emptyChatRuntimeState());

	return {
		subscribe: store.subscribe,
		applyEvent(event: unknown, now = Date.now()) {
			store.update((state) => applyChatRuntimeEvent(state, event, now));
		},
		seedHistory(chatId: string, history: unknown, now = Date.now()) {
			if (!chatId || chatId.startsWith('local:')) return;
			store.update((state) => ({
				chats: {
					...state.chats,
					[chatId]: seedChatRuntimeGraph(state.chats[chatId] ?? null, chatId, history, now)
				}
			}));
		},
		getSnapshot(chatId: string): ChatRuntimeChatState | null {
			return get(store).chats[chatId] ?? null;
		},
		// True when a stream has ended for this chat but its runtime projection has
		// not yet been confirmed durable (DB final). Callers use this to keep the
		// active indicator visible and the projection painted until durable final.
		isAwaitingDurableFinal(chatId: string): boolean {
			const chat = get(store).chats[chatId];
			return !!chat && chat.streamEnded === true;
		},
		// Acknowledge that the final assistant message for (chatId, messageId) is
		// durably saved. Clears that message's runtime projection. If no other
		// in-flight (non-user, not-done) message remains, the whole chat entry is
		// dropped. A non-matching message id is a no-op.
		markDurableFinal(chatId: string, messageId: string) {
			store.update((state) => {
				const chat = state.chats[chatId];
				if (!chat || !chat.messages[messageId]) return state;

				const otherInFlight = Object.entries(chat.messages).some(
					([id, message]) => id !== messageId && message.role !== 'user' && message.done !== true
				);

				const chats = { ...state.chats };
				if (!otherInFlight) {
					delete chats[chatId];
					return { chats };
				}

				const messages = { ...chat.messages };
				delete messages[messageId];
				chats[chatId] = {
					...chat,
					messages,
					currentId: chat.currentId === messageId ? null : chat.currentId
				};
				return { chats };
			});
		},
		clearChat(chatId: string) {
			store.update((state) => {
				if (!state.chats[chatId]) return state;
				const chats = { ...state.chats };
				delete chats[chatId];
				return { chats };
			});
		},
		mergeHistory(
			chatId: string,
			history: unknown,
			now = Date.now(),
			options: MergeHistoryOptions = {}
		): ChatHistory {
			return reconcileLoadedHistoryWithRuntime(history, get(store).chats[chatId] ?? null, now, {
				chatId,
				...options
			});
		},
		prune({
			maxAgeMs = DEFAULT_CHAT_RUNTIME_MAX_AGE_MS,
			maxChats = DEFAULT_CHAT_RUNTIME_MAX_CHATS,
			now = Date.now()
		}: { maxAgeMs?: number; maxChats?: number; now?: number } = {}) {
			store.update((state) => {
				const cutoff = now - maxAgeMs;
				const entries = Object.entries(state.chats)
					.filter(([, chat]) => chat.active || chat.lastUpdated >= cutoff)
					.sort(([, a], [, b]) => b.lastUpdated - a.lastUpdated);

				const kept = new Map(entries.slice(0, maxChats));
				return { chats: Object.fromEntries(kept) };
			});
		},
		reset() {
			store.set(emptyChatRuntimeState());
		}
	};
}

export const chatRuntimeStore = createChatRuntimeStore();
