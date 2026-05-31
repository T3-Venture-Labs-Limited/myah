import { describe, expect, it } from 'vitest';
import { getPinnedTodoPlan } from './todoPlanSelection';
import type { TodoPlanItem } from '$lib/types/contract';

function plan(overrides: Partial<TodoPlanItem> = {}): TodoPlanItem {
	return {
		type: 'todo_plan',
		id: 'plan-1',
		call_id: 'call-1',
		title: 'Plan',
		status: 'in_progress',
		todos: [{ id: '1', content: 'Do work', status: 'in_progress' }],
		...overrides
	};
}

describe('getPinnedTodoPlan', () => {
	it('selects the latest todo_plan from the active assistant branch only', () => {
		const stale = plan({ id: 'stale', call_id: 'stale-call' });
		const current = plan({ id: 'current', call_id: 'current-call' });

		expect(
			getPinnedTodoPlan({
				currentId: 'assistant-current',
				messages: {
					'assistant-stale': { role: 'assistant', done: false, output: [stale] },
					'assistant-current': {
						role: 'assistant',
						done: false,
						output: [plan({ id: 'older' }), current]
					}
				}
			})
		).toBe(current);
	});

	it('does not pin a completed plan after the run is done', () => {
		const completed = plan({
			status: 'completed',
			todos: [{ id: '1', content: 'Done', status: 'completed' }]
		});

		expect(
			getPinnedTodoPlan({
				currentId: 'assistant-current',
				messages: {
					'assistant-current': { role: 'assistant', done: true, output: [completed] }
				}
			})
		).toBeNull();
	});

	it('keeps a completed plan visible while the run is still streaming', () => {
		const completed = plan({
			status: 'completed',
			todos: [{ id: '1', content: 'Done', status: 'completed' }]
		});

		expect(
			getPinnedTodoPlan({
				currentId: 'assistant-current',
				messages: {
					'assistant-current': { role: 'assistant', done: false, output: [completed] }
				}
			})
		).toBe(completed);
	});

	it('returns null when current message is not assistant or has no plan output', () => {
		expect(
			getPinnedTodoPlan({
				currentId: 'user-current',
				messages: { 'user-current': { role: 'user', output: [plan()] } }
			})
		).toBeNull();
		expect(getPinnedTodoPlan({ currentId: 'assistant', messages: { assistant: { role: 'assistant' } } })).toBeNull();
	});
});
