import { describe, it, expect, vi } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import TodoRunPanel from './TodoRunPanel.svelte';

const data = {
	key: 'call_todo',
	completed: 1,
	total: 2,
	complete: false,
	items: [
		{ id: '1', content: 'Fix placement', status: 'completed' },
		{ id: '2', content: 'Run checks', status: 'pending' }
	]
};

describe('TodoRunPanel', () => {
	it('renders a themed todo panel with progress and tasks', () => {
		const { getByTestId, getByText, container } = render(TodoRunPanel, { props: { data } });

		expect(getByTestId('todo-run-panel')).toBeTruthy();
		expect(getByText('1 / 2')).toBeTruthy();
		expect(getByText('Fix placement')).toBeTruthy();
		expect(getByText('Run checks')).toBeTruthy();
		expect(container.querySelector('.dark\\:bg-gray-900\\/80')).toBeTruthy();
	});

	it('calls onHide when the Hide button is clicked', async () => {
		const onHide = vi.fn();
		const { getByTestId } = render(TodoRunPanel, { props: { data, onHide } });

		await fireEvent.click(getByTestId('todo-run-hide'));

		expect(onHide).toHaveBeenCalledOnce();
	});

	it('shows all steps complete for completed lists', () => {
		const { getByText } = render(TodoRunPanel, {
			props: { data: { ...data, completed: 2, complete: true, items: data.items.map((item) => ({ ...item, status: 'completed' })) } }
		});

		expect(getByText('All steps complete')).toBeTruthy();
	});
});
