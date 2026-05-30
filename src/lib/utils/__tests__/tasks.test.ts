import { describe, it, expect } from 'vitest';
import { get } from 'svelte/store';
import {
	mergeChatsAndProcesses,
	getTaskStatus,
	getTaskFiles,
	filterTasks,
	stripProcessPrefix,
	isProcessAdoptable
} from '$lib/utils/tasks';
import type { TaskItem } from '$lib/utils/tasks';
import { allTasks, applyAdoptedProcessToTasks } from '$lib/stores/tasks';

describe('stripProcessPrefix', () => {
	it('removes "Process: " prefix', () => {
		expect(stripProcessPrefix('Process: Daily Report')).toBe('Daily Report');
	});

	it('returns original if no prefix', () => {
		expect(stripProcessPrefix('Regular Chat')).toBe('Regular Chat');
	});
});

describe('getTaskStatus', () => {
	it('returns "active" when chatId is in activeChatIds', () => {
		const activeChatIds = new Set(['chat-1']);
		expect(getTaskStatus('chat-1', null, activeChatIds)).toBe('active');
	});

	it('returns "needs_input" when process has pending input', () => {
		const process = { has_pending_input: true } as any;
		expect(getTaskStatus('chat-1', process, new Set())).toBe('needs_input');
	});

	it('returns "scheduled" when process exists without pending input and is enabled', () => {
		const process = { has_pending_input: false, enabled: true, state: 'scheduled' } as any;
		expect(getTaskStatus('chat-1', process, new Set())).toBe('scheduled');
	});

	it('returns "completed" when process is paused', () => {
		const process = { has_pending_input: false, enabled: true, state: 'paused' } as any;
		expect(getTaskStatus('chat-1', process, new Set())).toBe('completed');
	});

	it('returns "completed" when process is disabled', () => {
		const process = { has_pending_input: false, enabled: false, state: 'scheduled' } as any;
		expect(getTaskStatus('chat-1', process, new Set())).toBe('completed');
	});

	it('returns "completed" by default', () => {
		expect(getTaskStatus('chat-1', null, new Set())).toBe('completed');
	});
});

describe('mergeChatsAndProcesses', () => {
	it('merges and sorts by updated_at descending', () => {
		// Use realistic Unix epoch seconds; process last_run_at ISO parses to ~1767225602s
		// c2 (1767226602) > p1 (1767225602) > c1 (1767224602)
		const chats = [
			{ id: 'c1', title: 'Chat One', updated_at: 1767224602 },
			{ id: 'c2', title: 'Chat Two', updated_at: 1767226602 }
		];
		const processes = [
			{
				id: 'p1',
				name: 'Hourly',
				last_run_at: '2026-01-01T00:00:02Z',
				created_at: '2026-01-01T00:00:00Z'
			}
		];

		const result = mergeChatsAndProcesses(chats as any, processes as any);
		expect(result).toHaveLength(3);
		// c2 > p1 > c1 by updated_at
		expect(result[0].id).toBe('c2');
		expect(result[2].id).toBe('c1');
	});

	it('marks process tasks as type "recurring"', () => {
		const result = mergeChatsAndProcesses([], [
			{
				id: 'p1',
				name: 'Hourly',
				chat_id: 'c3',
				created_at: '2026-01-01T00:00:00Z'
			}
		] as any);
		expect(result[0].type).toBe('recurring');
		expect(result[0].processId).toBe('p1');
	});

	it('excludes process chats from regular list and uses the chat ID for the process task (title match)', () => {
		const chats = [
			{ id: 'c1', title: 'Process: Hourly', updated_at: 1000 },
			{ id: 'c2', title: 'Regular Chat', updated_at: 2000 }
		];
		// No chat_id on process — matched by title convention
		const processes = [{ id: 'p1', name: 'Hourly', created_at: '2026-01-01T00:00:00Z' }];
		const result = mergeChatsAndProcesses(chats as any, processes as any);
		// c1 is excluded from regular chats (its title starts with "Process: ")
		// but appears as the process task (id = c1, the linked chat's ID)
		const ids = result.map((t) => t.id);
		expect(ids).toContain('c2');
		expect(ids).toContain('c1'); // process task uses the linked chat ID
		expect(result).toHaveLength(2);
		// Verify the process task has id = c1 (the linked chat)
		const processTask = result.find((t) => t.type === 'recurring');
		expect(processTask?.id).toBe('c1');
		expect(processTask?.processId).toBe('p1');
	});

	it('deduplicates task IDs when multiple processes share the same name', () => {
		const chats = [
			{ id: 'c1', title: 'Process: Science Joke Bot', updated_at: 3000 },
			{ id: 'c2', title: 'Regular Chat', updated_at: 2000 }
		];
		const processes = [
			{ id: 'p1', name: 'Science Joke Bot', created_at: '2026-01-01T00:00:00Z' },
			{ id: 'p2', name: 'Science Joke Bot', created_at: '2026-01-01T01:00:00Z' }
		];
		const result = mergeChatsAndProcesses(chats as any, processes as any);
		const ids = result.map((t) => t.id);
		// All IDs must be unique — no duplicates
		expect(new Set(ids).size).toBe(ids.length);
		// One process gets the linked chat ID, the other falls back to its own proc.id
		expect(ids).toContain('c1');
		expect(ids).toContain('p2');
		expect(ids).toContain('c2');
		expect(result).toHaveLength(3);
	});

	it('falls back to proc.id when no chat title matches', () => {
		const chats = [{ id: 'c2', title: 'Regular Chat', updated_at: 2000 }];
		const processes = [{ id: 'p1', name: 'Orphan Process', created_at: '2026-01-01T00:00:00Z' }];
		const result = mergeChatsAndProcesses(chats as any, processes as any);
		// Process has no linked chat — falls back to proc.id
		const processTask = result.find((t) => t.type === 'recurring');
		expect(processTask?.id).toBe('p1');
		// chatId stays undefined for orphans → TaskItem.svelte falls back to task.id
		expect(processTask?.chatId).toBeUndefined();
	});

	// ── Bug A: chatId is the navigation target, distinct from id (Svelte key)
	it('exposes origin chat_id as task.chatId so navigation reaches the originating chat', () => {
		const chats = [{ id: 'origin-chat', title: 'My Active Chat', updated_at: 1000 }];
		const processes = [
			{ id: 'p1', name: 'My Cron', chat_id: 'origin-chat', created_at: '2026-01-01T00:00:00Z' }
		];
		const result = mergeChatsAndProcesses(chats as any, processes as any);
		const cronTask = result.find((t) => t.type === 'recurring');
		expect(cronTask?.chatId).toBe('origin-chat');
		expect(cronTask?.id).toBe('origin-chat'); // unique here, so id == chatId
	});

	it('multiple crons sharing one origin chat all navigate there even when ids disambiguate', () => {
		const chats = [{ id: 'shared-chat', title: 'Active Chat', updated_at: 1000 }];
		const processes = [
			{ id: 'pA', name: 'Cron A', chat_id: 'shared-chat', created_at: '2026-01-01T00:00:00Z' },
			{ id: 'pB', name: 'Cron B', chat_id: 'shared-chat', created_at: '2026-01-01T01:00:00Z' }
		];
		const result = mergeChatsAndProcesses(chats as any, processes as any);
		const cronTasks = result.filter((t) => t.type === 'recurring');
		expect(cronTasks).toHaveLength(2);
		// Svelte keys must be unique
		expect(cronTasks[0].id).not.toBe(cronTasks[1].id);
		// But BOTH navigate to the shared origin chat — fixes Bug A where the
		// disambiguated cron used to navigate to /c/{job_id} (an empty chat).
		expect(cronTasks[0].chatId).toBe('shared-chat');
		expect(cronTasks[1].chatId).toBe('shared-chat');
	});
});

describe('getTaskFiles', () => {
	it('extracts files from chat meta', () => {
		const chat = { meta: { files: [{ name: 'report.pdf' }] } };
		expect(getTaskFiles(chat as any)).toEqual([{ name: 'report.pdf' }]);
	});

	it('returns empty array when no files', () => {
		expect(getTaskFiles({} as any)).toEqual([]);
		expect(getTaskFiles({ meta: {} } as any)).toEqual([]);
	});
});

describe('filterTasks', () => {
	const baseTask = (overrides: Partial<TaskItem>): TaskItem => ({
		id: 't1',
		title: 'Test Task',
		type: 'chat',
		status: 'completed',
		updated_at: 1000,
		files: [],
		...overrides
	});

	it('returns all tasks when no filters applied', () => {
		const tasks = [baseTask({ id: 't1' }), baseTask({ id: 't2' })];
		expect(filterTasks(tasks, {}, new Set())).toHaveLength(2);
	});

	it('filters by status', () => {
		const tasks = [
			baseTask({ id: 't1' }),
			baseTask({
				id: 't2',
				process: { has_pending_input: false, enabled: true, state: 'scheduled' } as any
			})
		];
		const result = filterTasks(tasks, { status: ['scheduled'] }, new Set());
		expect(result).toHaveLength(1);
		expect(result[0].id).toBe('t2');
	});

	it('filters by spaceId', () => {
		const tasks = [
			baseTask({ id: 't1', folder_id: 'space-1' }),
			baseTask({ id: 't2', folder_id: 'space-2' })
		];
		const result = filterTasks(tasks, { spaceId: 'space-1' }, new Set());
		expect(result).toHaveLength(1);
		expect(result[0].id).toBe('t1');
	});

	it('filters by search text (case-insensitive)', () => {
		const tasks = [
			baseTask({ id: 't1', title: 'Marketing Report' }),
			baseTask({ id: 't2', title: 'Finance Summary' })
		];
		const result = filterTasks(tasks, { search: 'marketing' }, new Set());
		expect(result).toHaveLength(1);
		expect(result[0].id).toBe('t1');
	});

	it('marks tasks as active when in activeChatIds', () => {
		const tasks = [baseTask({ id: 'chat-active' })];
		const result = filterTasks(tasks, {}, new Set(['chat-active']));
		expect(result[0].status).toBe('active');
	});

	// ── Adopt Legacy Crons (Phase 6): active status must key off the
	// navigation target (chatId), not the Svelte key (id, which is the
	// JOB_ID for disambiguated crons sharing one origin chat).
	it('marks a disambiguated cron task active by chatId, not processId', () => {
		const tasks = [
			baseTask({
				id: 'p1', // Svelte key = processId after disambiguation
				chatId: 'shared-chat', // real navigation target
				processId: 'p1',
				type: 'recurring',
				process: { has_pending_input: false, enabled: true, state: 'scheduled' } as any
			})
		];
		const result = filterTasks(tasks, {}, new Set(['shared-chat']));
		expect(result[0].status).toBe('active');
	});
});

describe('adoption classification (Adopt Legacy Crons — Phase 6)', () => {
	it('legacy_unowned process is adoptable with no navigation chat', () => {
		const procs = [
			{
				id: 'p1',
				name: 'Legacy Cron',
				adoptable: true,
				adoption_state: 'legacy_unowned',
				created_at: '2026-01-01T00:00:00Z'
			}
		];
		const result = mergeChatsAndProcesses([], procs as any);
		const task = result.find((t) => t.type === 'recurring')!;
		expect(task.adoptable).toBe(true);
		expect(task.adoptionState).toBe('legacy_unowned');
		// No chat to navigate to → the UI shows the Adopt affordance instead of
		// routing to a fake empty chat.
		expect(task.chatId).toBeUndefined();
		expect(isProcessAdoptable(procs[0] as any)).toBe(true);
	});

	it('external_origin process is adoptable and carries the warning state', () => {
		const procs = [
			{
				id: 'p1',
				name: 'Telegram Bot',
				adoptable: true,
				adoption_state: 'external_origin',
				origin: { platform: 'telegram', chat_id: 'tg-1' },
				created_at: '2026-01-01T00:00:00Z'
			}
		];
		const result = mergeChatsAndProcesses([], procs as any);
		const task = result.find((t) => t.type === 'recurring')!;
		expect(task.adoptable).toBe(true);
		expect(task.adoptionState).toBe('external_origin');
		expect(isProcessAdoptable(procs[0] as any)).toBe(true);
	});

	it('adopted (myah_linked) process navigates to its chat_id and is not adoptable', () => {
		const procs = [
			{
				id: 'p1',
				name: 'Adopted Cron',
				chat_id: 'chat-xyz',
				adoptable: false,
				adoption_state: 'myah_linked',
				created_at: '2026-01-01T00:00:00Z'
			}
		];
		const result = mergeChatsAndProcesses([], procs as any);
		const task = result.find((t) => t.type === 'recurring')!;
		expect(task.chatId).toBe('chat-xyz');
		expect(task.adoptable).toBe(false);
		expect(task.adoptionState).toBe('myah_linked');
		expect(isProcessAdoptable(procs[0] as any)).toBe(false);
	});

	it('isProcessAdoptable falls back to absence of chat_id when adoptable is absent', () => {
		expect(isProcessAdoptable({ id: 'p', name: 'x' } as any)).toBe(true);
		expect(isProcessAdoptable({ id: 'p', name: 'x', chat_id: 'c' } as any)).toBe(false);
		expect(isProcessAdoptable(null)).toBe(false);
	});

	it('updates task-store shape after adoption so the card does not remain stale', () => {
		const task = {
			id: 'p1',
			processId: 'p1',
			title: 'Legacy Cron',
			type: 'recurring',
			status: 'scheduled',
			updated_at: 0,
			files: [],
			adoptable: true,
			adoptionState: 'legacy_unowned',
			process: { id: 'p1', name: 'Legacy Cron', adoptable: true } as any
		} satisfies TaskItem;

		const next = applyAdoptedProcessToTasks([task], task.process as any, 'chat-1');
		expect(next[0].id).toBe('chat-1');
		expect(next[0].chatId).toBe('chat-1');
		expect(next[0].adoptable).toBe(false);
		expect(next[0].adoptionState).toBe('myah_linked');
		expect(next[0].process?.chat_id).toBe('chat-1');
		expect(next[0].process?.adoptable).toBe(false);

		allTasks.set([task]);
		allTasks.update((tasks) => applyAdoptedProcessToTasks(tasks, task.process as any, 'chat-1'));
		expect(get(allTasks)[0].chatId).toBe('chat-1');
	});
});
