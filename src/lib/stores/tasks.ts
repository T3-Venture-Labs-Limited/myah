// These stores hold the living record of what Myah is working on —
// tasks in motion, tasks completed, tasks waiting to be called upon.

import { writable } from 'svelte/store';
import type { Process } from '$lib/apis/processes';
import type { TaskItem, TaskStatus } from '$lib/utils/tasks';

// Map of chatId -> Process for quick lookups
export const processMap = writable<Map<string, Process>>(new Map());

// All merged tasks (chats + processes)
export const allTasks = writable<TaskItem[]>([]);

// Current filter state
export const taskStatusFilter = writable<TaskStatus[]>([]);
export const taskSpaceFilter = writable<string | null>(null);
export const taskSearchQuery = writable<string>('');

// UI state
export const showTaskList = writable<boolean>(true);
export const taskListWidth = writable<number>(380);
