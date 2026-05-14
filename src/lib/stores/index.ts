import { APP_NAME } from '$lib/constants';
import { type Readable, type Writable, writable, derived } from 'svelte/store';
import type { ModelConfig } from '$lib/apis';
import type { Banner } from '$lib/types';
import type { AgentCommand } from '$lib/types';
import type { AgentToolset, AgentSkill, MemoryConclusion } from '$lib/apis/agent';
import type { ArtifactFile, SelectionPayload, AnchorPayload } from '$lib/types/artifact';
import type { Socket } from 'socket.io-client';

import emojiShortCodes from '$lib/emoji-shortcodes.json';

// What is held here is the only truth the house knows.
// When it changes, let every room hear at once.
// Backend
export const WEBUI_NAME = writable(APP_NAME);

export const WEBUI_VERSION = writable(null);
export const MYAH_DEPLOYMENT_ID = writable(null);

export const config: Writable<Config | undefined> = writable(undefined);
export const user: Writable<SessionUser | undefined> = writable(undefined);

// Electron App
export const isApp = writable(false);
export const appInfo = writable(null);
export const appData = writable(null);

// Frontend
export const MODEL_DOWNLOAD_POOL = writable({});

export const mobile = writable(false);

export const socket: Writable<null | Socket> = writable(null);
export const activeUserIds: Writable<null | string[]> = writable(null);
export const activeChatIds: Writable<Set<string>> = writable(new Set());
export const USAGE_POOL: Writable<null | string[]> = writable(null);

export const theme = writable('system');

export const shortCodesToEmojis = writable(
	Object.entries(emojiShortCodes).reduce<Record<string, string>>(
		(acc, [key, value]) => {
			if (typeof value === 'string') {
				acc[value] = key;
			} else {
				for (const v of value) {
					acc[v] = key;
				}
			}

			return acc;
		},
		{} as Record<string, string>
	)
);

export const chatId = writable('');
export const chatTitle = writable('');

export const chats = writable(null);
export const pinnedChats = writable([]);
export const tags = writable([]);
export const folders = writable([]);

export const selectedFolder = writable(null);

export const models: Writable<Model[]> = writable([]);

// Myah T3-932: Per-user default chat model id (e.g. 'anthropic/claude-opus-4-7').
// null means "no default set" — Chat.svelte falls back to admin DEFAULT_MODELS
// and then the first available provider model. Hydrated from the session user
// payload on app boot and updated whenever the user picks "Set as default".
export const defaultModel: Writable<string | null> = writable(null);

export const skills = writable(null);

// Agent capability stores — sourced from Hermes container, not Open WebUI DB
export const agentToolsets: Writable<AgentToolset[] | null> = writable(null);
export const agentSkills: Writable<AgentSkill[] | null> = writable(null);

// Agent memory stores — sourced from Honcho via platform API
export const agentMemoryProfile: Writable<string[] | null> = writable(null);
export const agentMemoryAiProfile: Writable<string[] | null> = writable(null);
export const agentMemoryConclusions: Writable<MemoryConclusion[] | null> = writable(null);

export const agentCommands: Writable<AgentCommand[]> = writable([]);

export const banners: Writable<Banner[]> = writable([]);

export const settings: Writable<Settings> = writable({});

export const chatRequestQueues: Writable<
	Record<string, { id: string; prompt: string; files: any[] }[]>
> = writable({});

export const sidebarWidth = writable(260);

export const showSidebar = writable(false);
export const showSearch = writable(false);
export const showSettings = writable(false);
export const showShortcuts = writable(false);
export const showArchivedChats = writable(false);
export const showChangelog = writable(false);

export const showControls = writable(false);

// Re-exported so existing consumers' `import { ArtifactFile } from '$lib/stores'`
// continues to compile. The canonical definition lives in $lib/types/artifact.
export type { ArtifactFile };

// ── Artifact pane state (Phase 1 of artifact-pane-redesign) ────────────
//
// The pane has a single source of truth: the open-files list + active tab
// index. There are NO direct writers to `currentArtifactFile` anymore —
// it is a derived projection of the two stores below. All mutations flow
// through `openArtifactInPane()` / `closeArtifactPane()`.

// Open files (tab state). Empty array = no tabs.
export const artifactOpenFiles: Writable<ArtifactFile[]> = writable([]);

// Index of the active tab. -1 = explorer view (no file focused).
export const artifactActiveTabIdx: Writable<number> = writable(-1);

// Whether the artifact pane is open at all. Drives the layout shift.
export const artifactPaneOpen: Writable<boolean> = writable(false);

// What's currently selected, single-valued across all renderers.
export const artifactSelection: Writable<SelectionPayload | null> = writable(null);

// Dirty edits per file_key. Read by the composer to surface file-edit chips.
export const artifactPendingEdits: Writable<Map<string, { filename: string; diff: string }>> =
	writable(new Map());

// 2026-05-05 dogfooding: monotonic counter bumped whenever something
// happens that may have added new files to the chat (typically: an
// artifact_card OutputItem appearing in the streamed message tree, OR a
// run.completed event finishing). The ArtifactExplorer subscribes to this
// counter and re-fetches /api/v1/chats/{id}/files on change. Without it,
// the explorer only loads on mount and never reflects files the agent
// creates mid-session — the user has to close and re-open the pane.
//
// Keep this a number (not a boolean toggle) so multiple subscribers can
// each compare against their last-seen value without coordinating resets.
export const artifactExplorerRefreshTick: Writable<number> = writable(0);

export function bumpArtifactExplorerRefresh(): void {
	artifactExplorerRefreshTick.update((n) => n + 1);
}

// Phase 4A — composer integration. SelectionToolbar's "Add to chat" pushes
// the active selection (with a generated id and the source filename) here;
// the composer-side RefChipBar consumes the `composerChips` derived store
// below to render chips above the input.
export const composerRefs: Writable<
	Array<SelectionPayload & { id: string; filename: string }>
> = writable([]);

// What the composer shows above its input. Merges user-added refs (from
// composerRefs) with auto-derived file-edit chips (from artifactPendingEdits).
// Each chip carries kind/filename/summary/payload so RefChip can tint by kind
// and remove logic can route back to the right store.
export interface RefChip {
	id: string;
	kind: 'doc-text' | 'sheet-cells' | 'image-region' | 'video-region' | 'code-lines' | 'file-edit';
	filename: string;
	summary: string;
	payload: unknown;
}

export const composerChips: Readable<RefChip[]> = derived(
	[composerRefs, artifactPendingEdits],
	([$refs, $edits]) => {
		const refChips: RefChip[] = $refs.map((ref) => ({
			id: ref.id,
			kind: ref.kind,
			filename: ref.filename,
			summary: ref.summary,
			payload: ref
		}));
		const editChips: RefChip[] = [...$edits].map(([file_key, value]) => ({
			id: `edit-${file_key}`,
			kind: 'file-edit',
			filename: value.filename,
			summary: `${countDiffLines(value.diff)} lines changed`,
			payload: { file_key, diff: value.diff }
		}));
		return [...refChips, ...editChips];
	}
);

function countDiffLines(diff: string): number {
	return diff.split('\n').filter((l) => l.startsWith('+') || l.startsWith('-')).length;
}

// Set by ref-chip clicks in Phase 4 to drive the pulse animation in renderers.
// Phase 3 introduces the store; renderers that subscribe (the pulse animation)
// also land in Phase 3, but Phase 4 fills in the ref-chip → store-write side.
export const artifactHighlightAnchor: Writable<{
	fileKey: string;
	anchor: AnchorPayload;
	reason: 'hover' | 'click';
} | null> = writable(null);

// Backwards-compat: existing components read currentArtifactFile.
// Now a derived store: returns active open file or null. There are NO writers
// to this store anymore; use openArtifactInPane() / closeArtifactPane() instead.
export const currentArtifactFile = derived(
	[artifactOpenFiles, artifactActiveTabIdx],
	([$files, $idx]) => {
		if ($idx < 0 || $idx >= $files.length) return null;
		return $files[$idx];
	}
);

// ── Helpers (the only writers to artifact pane state) ──────────────────

export function openArtifactInPane(file: ArtifactFile): void {
	// Append to open files (or focus existing tab), set as active, open the pane.
	artifactOpenFiles.update((files) => {
		const existing = files.findIndex((f) => f.file_key === file.file_key);
		if (existing >= 0) {
			artifactActiveTabIdx.set(existing);
			return files;
		}
		artifactActiveTabIdx.set(files.length);
		return [...files, file];
	});
	artifactPaneOpen.set(true);
}

export function closeArtifactPane(): void {
	artifactActiveTabIdx.set(-1);
	artifactPaneOpen.set(false);
	artifactSelection.set(null);
	// Note: artifactOpenFiles is intentionally NOT cleared — closing the pane
	// preserves tab state so reopening picks up where it left off. Tab list is
	// scoped to the chat session and clears on chat unmount.
}

// 2026-05-05 dogfooding: artifact tabs/selection are scoped to a single
// chat. Without this subscription they leak across chats — the user sees
// the previous chat's tabs after navigating to a fresh chat. The previous
// fix at ArtifactPane.svelte tracked `chatId` via a component-local
// variable, which doesn't survive the pane unmounting (e.g. when the user
// closes it on chat A and reopens on chat B). Subscribing here at the
// store layer means the reset fires regardless of which components are
// currently mounted.
//
// Skip the very first chatId we observe — that's the initial route load,
// not a user-initiated transition, and the artifact stores are already
// empty at that point so the reset would be a no-op anyway.
let _lastChatIdSeen: string | undefined = undefined;
chatId.subscribe((id) => {
	if (_lastChatIdSeen === undefined) {
		_lastChatIdSeen = id;
		return;
	}
	if (id === _lastChatIdSeen) return;
	_lastChatIdSeen = id;
	artifactOpenFiles.set([]);
	artifactActiveTabIdx.set(-1);
	artifactSelection.set(null);
	artifactPendingEdits.set(new Map());
	composerRefs.set([]);
});

// ── Other panel-related stores (preserved from previous shape) ────────
export const showChatFilesPanel: Writable<boolean> = writable(false);
export const activeChatFileId: Writable<string | null> = writable(null);

export const temporaryChatEnabled = writable(false);
export const scrollPaginationEnabled = writable(false);
export const currentChatPage = writable(1);

export const isLastActiveTab = writable(true);
export const playingNotificationSound = writable(false);

export type Model = OpenAIModel;

type BaseModel = {
	id: string;
	name: string;
	info?: ModelConfig;
	owned_by: 'openai';
};

export interface OpenAIModel extends BaseModel {
	owned_by: 'openai';
	external: boolean;
	source?: string;
}

type Settings = {
	pinnedModels?: never[];
	showUpdateToast?: boolean;
	showChangelog?: boolean;
	showEmojiInCall?: boolean;
	voiceInterruption?: boolean;
	collapseCodeBlocks?: boolean;
	expandDetails?: boolean;
	notificationSound?: boolean;
	notificationSoundAlways?: boolean;
	stylizedPdfExport?: boolean;
	notifications?: any;
	imageCompression?: boolean;
	imageCompressionSize?: any;
	textScale?: number;
	widescreenMode?: null;
	largeTextAsFile?: boolean;
	promptAutocomplete?: boolean;
	hapticFeedback?: boolean;
	responseAutoCopy?: any;
	richTextInput?: boolean;
	params?: any;
	userLocation?: any;
	webSearch?: any;
	autoTags?: boolean;
	autoFollowUps?: boolean;
	splitLargeChunks?(body: any, splitLargeChunks: any): unknown;
	backgroundImageUrl?: null;
	landingPageMode?: string;
	iframeSandboxAllowForms?: boolean;
	iframeSandboxAllowSameOrigin?: boolean;
	scrollOnBranchChange?: boolean;
	directConnections?: null;
	chatBubble?: boolean;
	copyFormatted?: boolean;
	models?: string[];
	conversationMode?: boolean;
	speechAutoSend?: boolean;
	responseAutoPlayback?: boolean;
	audio?: AudioSettings;
	showUsername?: boolean;
	notificationEnabled?: boolean;
	highContrastMode?: boolean;
	title?: TitleSettings;
	showChatTitleInTab?: boolean;
	splitLargeDeltas?: boolean;
	chatDirection?: 'LTR' | 'RTL' | 'auto';
	ctrlEnterToSend?: boolean;
	renderMarkdownInPreviews?: boolean;

	system?: string;
	seed?: number;
	temperature?: string;
	repeat_penalty?: string;
	top_k?: string;
	top_p?: string;
	num_ctx?: string;
	num_batch?: string;
	num_keep?: string;
	options?: ModelOptions;
};

type ModelOptions = {
	stop?: boolean;
};

type AudioSettings = {
	stt: any;
	tts: any;
	STTEngine?: string;
	TTSEngine?: string;
	speaker?: string;
	model?: string;
	nonLocalVoices?: boolean;
};

type TitleSettings = {
	auto?: boolean;
	model?: string;
	modelExternal?: string;
	prompt?: string;
};

type Config = {
	license_metadata: any;
	status: boolean;
	name: string;
	version: string;
	default_locale: string;
	default_models: string;
	default_prompt_suggestions: PromptSuggestion[];
	features: {
		auth: boolean;
		auth_trusted_header: boolean;
		enable_api_keys: boolean;
		enable_signup: boolean;
		enable_login_form: boolean;
		enable_web_search?: boolean;
		enable_google_drive_integration: boolean;
		enable_onedrive_integration: boolean;
		enable_admin_export: boolean;
		enable_admin_chat_access: boolean;
		enable_admin_analytics: boolean;
		enable_community_sharing: boolean;
		enable_autocomplete_generation: boolean;
		enable_direct_connections: boolean;
		enable_version_update_check: boolean;
		folder_max_file_count?: number;
	};
	oauth: {
		providers: {
			[key: string]: string;
		};
	};
	ui?: {
		pending_user_overlay_title?: string;
		pending_user_overlay_content?: string;
	};
};

type PromptSuggestion = {
	content: string;
	title: [string, string];
};

export type SessionUser = {
	permissions: any;
	id: string;
	email: string;
	name: string;
	role: string;
	profile_image_url: string;
	default_model?: string | null; // Myah T3-932
};

// Task stores
export {
	processMap,
	allTasks,
	taskStatusFilter,
	taskSpaceFilter,
	taskSearchQuery,
	showTaskList,
	taskListWidth
} from './tasks';

// Stream reconnect banner — null means hidden; any string is displayed as-is.
// State machine lives in Chat.svelte / tryResumeInflight (Task 6).
export const reconnectBanner: Writable<string | null> = writable(null);
