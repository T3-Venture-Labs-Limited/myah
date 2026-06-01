import { describe, it, expect, beforeAll } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import TodoPlanStrip from './TodoPlanStrip.svelte';
import type { TodoPlanItem } from '$lib/types/contract';

function plan(overrides: Partial<TodoPlanItem> = {}): TodoPlanItem {
	return {
		type: 'todo_plan',
		id: 'todo-plan-1',
		call_id: 'call_todo_1',
		title: 'Plan',
		status: 'in_progress',
		todos: [
			{ id: '1', content: 'Inspect design files', status: 'completed' },
			{ id: '2', content: 'Build pinned strip', status: 'in_progress' },
			{ id: '3', content: 'Verify runtime smoke', status: 'pending' }
		],
		...overrides
	};
}

beforeAll(() => {
	if (!Element.prototype.animate) {
		Element.prototype.animate = (() => {
			const animation = {
				finished: Promise.resolve(),
				cancel: () => {},
				commitStyles: () => {},
				onfinish: null as ((event: Event) => void) | null
			};
			queueMicrotask(() => animation.onfinish?.(new Event('finish')));
			return animation;
		}) as unknown as Element['animate'];
	}
});

describe('TodoPlanStrip', () => {
	it('renders nothing without a plan or todos', () => {
		const { container, rerender } = render(TodoPlanStrip, { props: { plan: null } });
		expect(container.querySelector('[aria-label="Agent plan"]')).not.toBeInTheDocument();

		rerender({ plan: plan({ todos: [] }) });
		expect(container.querySelector('[aria-label="Agent plan"]')).not.toBeInTheDocument();
	});

	it('renders collapsed header with plan progress and active task', () => {
		render(TodoPlanStrip, { props: { plan: plan(), initiallyExpanded: false } });

		expect(screen.getByText('Working · step 2 of 3')).toBeInTheDocument();
		expect(screen.getByText('1/3')).toBeInTheDocument();
		expect(screen.getByText('Build pinned strip')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: /show plan steps/i })).toHaveAttribute(
			'aria-expanded',
			'false'
		);
		expect(screen.queryAllByTestId('todo-plan-segment')).toHaveLength(0);
	});

	it('renders a centered dynamic-island pill that expands when the pill is clicked', async () => {
		render(TodoPlanStrip, { props: { plan: plan(), initiallyExpanded: false } });

		const island = screen.getByRole('button', { name: /show plan steps/i });
		expect(island).toHaveClass('todo-plan-island');
		expect(island).toHaveTextContent('Working · step 2 of 3');
		expect(screen.queryByRole('list', { name: /plan steps/i })).not.toBeInTheDocument();

		await fireEvent.click(island);

		expect(screen.getByRole('list', { name: /plan steps/i })).toBeInTheDocument();
		expect(
			screen.getByRole('button', { name: /collapse plan to current task pill/i })
		).toHaveAttribute('aria-expanded', 'true');
		const panel = screen.getByRole('list', { name: /plan steps/i }).closest('.todo-plan-panel');
		expect(panel).toHaveAttribute('data-motion', 'dynamic-island-morph');
		expect(screen.getByRole('button', { name: /hide plan steps/i })).toBeInTheDocument();
	});

	it('returns to pill form instead of disappearing when hide is pressed', async () => {
		render(TodoPlanStrip, { props: { plan: plan(), initiallyExpanded: true } });

		expect(screen.getByRole('list', { name: /plan steps/i })).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: /hide plan steps/i }));

		await waitFor(() => {
			expect(screen.queryByRole('list', { name: /plan steps/i })).not.toBeInTheDocument();
		});
		expect(screen.getByRole('button', { name: /show plan steps/i })).toHaveTextContent(
			'Build pinned strip'
		);
	});

	it('describes pending-only plans as planned and previews the first pending task', () => {
		render(TodoPlanStrip, {
			props: {
				plan: plan({
					todos: [
						{ id: '1', content: 'First queued task', status: 'pending' },
						{ id: '2', content: 'Second queued task', status: 'pending' }
					]
				}),
				initiallyExpanded: false
			}
		});

		expect(screen.getByText('Planned · 0 of 2')).toBeInTheDocument();
		expect(screen.getByText('First queued task')).toBeInTheDocument();
		expect(screen.queryByText(/Complete · 0 of 2/)).not.toBeInTheDocument();
	});

	it('styles completed, active, and pending rows distinctly', () => {
		render(TodoPlanStrip, { props: { plan: plan(), initiallyExpanded: true } });

		const completed = screen.getByTestId('todo-plan-row-1');
		const active = screen.getByTestId('todo-plan-row-2');
		const pending = screen.getByTestId('todo-plan-row-3');

		expect(completed).toHaveAttribute('data-status', 'completed');
		expect(completed).toHaveTextContent('Inspect design files');
		expect(active).toHaveAttribute('data-active', 'true');
		expect(active).toHaveTextContent('Working');
		expect(pending).toHaveAttribute('data-status', 'pending');
		expect(pending).not.toHaveTextContent('Working');
	});
});
