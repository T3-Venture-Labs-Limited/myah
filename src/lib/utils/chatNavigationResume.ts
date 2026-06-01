export type ChatNavigationResumeDeps = {
	chatId: string;
	loadCriticalChat: () => Promise<boolean | null | undefined>;
	loadFastProjection?: () => Promise<boolean> | boolean;
	loadDeferredMetadata?: () => Promise<void>;
	setLoading: (loading: boolean) => void;
	afterFastProjectionRender?: () => Promise<void> | void;
	afterCriticalRender?: () => Promise<void> | void;
	afterCriticalReconcile?: () => Promise<void> | void;
	resumeInflight?: (chatId: string) => Promise<void> | void;
	isPersistedChat?: (chatId: string) => boolean;
};

export async function resumeChatAfterCriticalLoad({
	chatId,
	loadCriticalChat,
	loadFastProjection,
	loadDeferredMetadata,
	setLoading,
	afterFastProjectionRender,
	afterCriticalRender,
	afterCriticalReconcile,
	resumeInflight,
	isPersistedChat = (id) => !!id && !id.startsWith('local:')
}: ChatNavigationResumeDeps): Promise<boolean> {
	const fastPainted = (await loadFastProjection?.()) === true;
	if (fastPainted) {
		await afterFastProjectionRender?.();
		setLoading(false);
	}

	const loaded = await loadCriticalChat();
	if (!loaded) {
		return false;
	}

	if (!fastPainted) {
		await afterCriticalRender?.();
		setLoading(false);
	}

	await afterCriticalReconcile?.();

	if (isPersistedChat(chatId)) {
		void Promise.resolve(resumeInflight?.(chatId)).catch((err) => {
			console.warn('[chat-navigation] resumeInflight failed:', err);
		});
	}

	if (loadDeferredMetadata) {
		void loadDeferredMetadata().catch((err) => {
			console.warn('[chat-navigation] deferred metadata load failed:', err);
		});
	}

	return true;
}
