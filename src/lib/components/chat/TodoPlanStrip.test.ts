import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
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

describe('TodoPlanStrip', () => {
	it('renders nothing without a plan or todos', () => {
		const { container, rerender } = render(TodoPlanStrip, { props: { plan: null } });
		expect(container.querySelector('[aria-label="Agent plan"]')).not.toBeInTheDocument();

		rerender({ plan: plan({ todos: [] }) });
		expect(container.querySelector('[aria-label="Agent plan"]')).not.toBeInTheDocument();
	});

	it('renders collapsed header with plan progress and active task', () => {
		render(TodoPlanStrip, { props: { plan: plan(), initiallyExpanded: false } });

		expect(screen.getByText('Plan')).toBeInTheDocument();
		expect(screen.getAllByText('1/3')).toHaveLength(2);
		expect(screen.getByText('Build pinned strip')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: /show plan steps/i })).toHaveAttribute(
			'aria-expanded',
			'false'
		);
		expect(screen.getAllByTestId('todo-plan-segment')).toHaveLength(3);
	});

	it('toggles the dropdown checklist', async () => {
		render(TodoPlanStrip, { props: { plan: plan(), initiallyExpanded: false } });

		expect(screen.queryByRole('list', { name: /plan steps/i })).not.toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: /show plan steps/i }));

		expect(screen.getByRole('list', { name: /plan steps/i })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: /hide plan steps/i })).toHaveAttribute(
			'aria-expanded',
			'true'
		);
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
