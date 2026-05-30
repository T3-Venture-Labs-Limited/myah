// Each task here is a thread of intention — something asked, something running,
// something waiting to be answered. These utilities weave them into a single view.

import type { Process } from '$lib/apis/processes';

export interface ChatLike {
	id: string;
	title?: string | null;
	updated_at?: number | null;
	folder_id?: string | null;
	meta?: { files?: TaskFile[] };
}

export type TaskStatus = 'active' | 'needs_input' | 'scheduled' | 'completed';
export type TaskType = 'chat' | 'recurring';

export interface TaskItem {
	id: string; // unique key for Svelte {#each} (chat_id when 1 cron per chat,
	//             falls back to processId to disambiguate multiple crons sharing an origin chat)
	chatId?: string; // navigation target — origin chat for crons; same as id for chat tasks
	processId?: string;
	title: string;
	type: TaskType;
	status: TaskStatus;
	updated_at: number;
	process?: Process;
	files: TaskFile[];
	chat?: ChatLike;
	folder_id?: string;
	// ── Adopt Legacy Crons (Phase 6): whether to show the "Adopt into Myah"
	// affordance, and which copy variant to use. Populated for recurring tasks.
	adoptable?: boolean;
	adoptionState?: Process['adoption_state'];
}

export interface TaskFile {
	name: string;
	type?: string;
	url?: string;
}

export function stripProcessPrefix(title: string): string {
	if (title?.startsWith('Process: ')) {
		return title.slice(9);
	}
	return title ?? '';
}

/**
 * Whether a process should surface the "Adopt into Myah" affordance.
 *
 * Trusts the backend-derived `adoptable` flag when present; falls back to
 * "no linked Myah chat → adoptable" for older backends that don't emit it.
 */
export function isProcessAdoptable(process: Process | null | undefined): boolean {
	if (!process) return false;
	if (typeof process.adoptable === 'boolean') return process.adoptable;
	return !process.chat_id;
}

export function getTaskStatus(
	chatId: string,
	process: Process | null | undefined,
	activeChatIds: Set<string>
): TaskStatus {
	if (activeChatIds.has(chatId)) {
		return 'active';
	}
	if (process) {
		if (process.has_pending_input) {
			return 'needs_input';
		}
		// Paused processes are treated as completed (not scheduled)
		if (process.state === 'paused' || !process.enabled) {
			return 'completed';
		}
		return 'scheduled';
	}
	return 'completed';
}

export function getTaskFiles(chatOrProcess: ChatLike | Process): TaskFile[] {
	if (chatOrProcess?.meta?.files && Array.isArray(chatOrProcess.meta.files)) {
		return chatOrProcess.meta.files;
	}
	return [];
}

export function mergeChatsAndProcesses(chats: ChatLike[], processes: Process[]): TaskItem[] {
	// Match processes to their linked chats by title convention "Process: {name}".
	// The API never returns chat_id on process objects, so we look up by title.
	// Build a map: process name → chat object
	const processChatByName = new Map<string, ChatLike>();
	const processChatIds = new Set<string>();

	for (const chat of chats) {
		const title: string = chat.title ?? '';
		if (title.startsWith('Process: ')) {
			const procName = title.slice(9); // strip "Process: " prefix
			processChatByName.set(procName, chat);
			processChatIds.add(chat.id);
		}
	}

	// Also handle chat_id if the API ever starts returning it
	for (const proc of processes) {
		if (proc.chat_id) {
			processChatIds.add(proc.chat_id);
		}
	}

	const tasks: TaskItem[] = [];

	// Add regular chats — excluding those that are process output chats
	for (const chat of chats) {
		if (processChatIds.has(chat.id)) {
			continue; // will be surfaced as part of the process task
		}
		tasks.push({
			id: chat.id,
			chatId: chat.id,
			title: chat.title ?? 'New Chat',
			type: 'chat',
			status: 'completed',
			updated_at: chat.updated_at ?? 0,
			files: getTaskFiles(chat),
			chat,
			folder_id: chat.folder_id
		});
	}

	// Add processes as recurring tasks, using the linked chat ID when available.
	// Track assigned IDs to prevent duplicates — multiple processes can share
	// the same name (e.g. two "Science Joke Bot" cron jobs) and would otherwise
	// both resolve to the same linked chat ID, crashing Svelte's keyed {#each}.
	const usedTaskIds = new Set<string>(tasks.map((t) => t.id));

	for (const proc of processes) {
		// Try to find the linked chat: first by explicit chat_id, then by title match
		const linkedChat = proc.chat_id
			? chats.find((c) => c.id === proc.chat_id)
			: processChatByName.get(proc.name);

		// Bug A — separate Svelte key (`id`) from navigation target (`chatId`):
		// the `id` must be unique across the list (Svelte keyed {#each}); two
		// crons sharing the same origin chat would otherwise collide.  The
		// `chatId` is the actual link target — every cron that has an origin
		// chat should navigate there regardless of how its key was disambiguated.
		const originChatId = linkedChat?.id ?? proc.chat_id;
		let taskId = originChatId ?? proc.id;
		if (usedTaskIds.has(taskId)) {
			taskId = proc.id; // Disambiguate the Svelte key only.
		}
		usedTaskIds.add(taskId);

		tasks.push({
			id: taskId,
			chatId: originChatId, // navigate here when present (Bug A fix)
			title: stripProcessPrefix(proc.name),
			type: 'recurring',
			status: 'scheduled',
			updated_at:
				linkedChat?.updated_at ??
				(proc.last_run_at
					? new Date(proc.last_run_at).getTime() / 1000
					: proc.created_at
						? new Date(proc.created_at).getTime() / 1000
						: 0),
			processId: proc.id,
			process: proc,
			files: [],
			// Adopt Legacy Crons (Phase 6): surface adoption affordance state.
			adoptable: isProcessAdoptable(proc),
			adoptionState: proc.adoption_state
		});
	}

	// Sort by updated_at descending (most recent first)
	tasks.sort((a, b) => b.updated_at - a.updated_at);

	return tasks;
}

/**
 * Filter and update task statuses. Pass a live `activeChatIds` set for accurate
 * 'active' status detection — passing an empty set will never show tasks as active.
 */
export function filterTasks(
	tasks: TaskItem[],
	filters: {
		status?: TaskStatus[];
		spaceId?: string | null;
		search?: string;
	},
	activeChatIds: Set<string>
): TaskItem[] {
	let filtered = tasks;

	// Update live status before filtering. Key off the navigation target
	// (chatId) rather than the Svelte key (id) — for crons sharing one origin
	// chat, `id` is disambiguated to the JOB_ID, which is never in activeChatIds.
	filtered = filtered.map((task) => ({
		...task,
		status: getTaskStatus(task.chatId ?? task.id, task.process ?? null, activeChatIds)
	}));

	if (filters.status && filters.status.length > 0) {
		filtered = filtered.filter((t) => filters.status!.includes(t.status));
	}

	if (filters.spaceId) {
		filtered = filtered.filter((t) => t.folder_id === filters.spaceId);
	}

	if (filters.search && filters.search.trim()) {
		const query = filters.search.toLowerCase().trim();
		filtered = filtered.filter((t) => t.title.toLowerCase().includes(query));
	}

	return filtered;
}
