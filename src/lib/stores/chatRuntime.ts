import { get, writable } from 'svelte/store';
import {
	applyChatRuntimeEvent,
	emptyChatRuntimeState,
	reconcileLoadedHistoryWithRuntime,
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
		getSnapshot(chatId: string): ChatRuntimeChatState | null {
			return get(store).chats[chatId] ?? null;
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
