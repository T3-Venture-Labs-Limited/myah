import { beforeEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import { allTasks, applyChatUpdateToAllTasks } from './tasks';
import type { TaskItem } from '$lib/utils/tasks';

const task = (id: string, updated_at: number): TaskItem => ({
	id,
	chatId: id,
	title: id,
	type: 'chat',
	status: 'completed',
	updated_at,
	files: []
});

describe('applyChatUpdateToAllTasks', () => {
	beforeEach(() => allTasks.set([]));

	it('updates and reorders the global task store', () => {
		allTasks.set([task('older', 1000), task('target', 500)]);

		applyChatUpdateToAllTasks({ id: 'target', title: 'Target', updated_at: 2000 });

		expect(get(allTasks).map((t) => t.id)).toEqual(['target', 'older']);
	});
});
