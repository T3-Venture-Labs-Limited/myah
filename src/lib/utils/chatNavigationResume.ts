export type ChatNavigationResumeDeps = {
	chatId: string;
	loadCriticalChat: () => Promise<boolean | null | undefined>;
	loadDeferredMetadata?: () => Promise<void>;
	setLoading: (loading: boolean) => void;
	afterCriticalRender?: () => Promise<void> | void;
	resumeInflight?: (chatId: string) => void;
	isPersistedChat?: (chatId: string) => boolean;
};

export async function resumeChatAfterCriticalLoad({
	chatId,
	loadCriticalChat,
	loadDeferredMetadata,
	setLoading,
	afterCriticalRender,
	resumeInflight,
	isPersistedChat = (id) => !!id && !id.startsWith('local:')
}: ChatNavigationResumeDeps): Promise<boolean> {
	const loaded = await loadCriticalChat();
	if (!loaded) {
		return false;
	}

	await afterCriticalRender?.();
	setLoading(false);

	if (isPersistedChat(chatId)) {
		resumeInflight?.(chatId);
	}

	if (loadDeferredMetadata) {
		void loadDeferredMetadata().catch((err) => {
			console.warn('[chat-navigation] deferred metadata load failed:', err);
		});
	}

	return true;
}
