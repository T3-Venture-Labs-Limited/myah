import { describe, it, expect } from 'vitest';
import type { OutputItem } from '$lib/components/chat/Messages/HermesOutputRenderer/types';
import { extractTodoListFromOutput, filterTodoToolOutput } from './todoOutput';

const todoOutput = (text: string): OutputItem[] => [
	{
		type: 'function_call',
		id: 'fc_todo',
		call_id: 'call_todo',
		name: 'todo',
		arguments: '{}',
		status: 'completed'
	},
	{
		type: 'function_call_output',
		id: 'out_todo',
		call_id: 'call_todo',
		status: 'completed',
		output: [{ type: 'input_text', text }]
	}
];

describe('extractTodoListFromOutput', () => {
	it('parses Hermes todo tool output with todos payload', () => {
		const panel = extractTodoListFromOutput(
			todoOutput(
				JSON.stringify({
					todos: [
						{ id: '1', content: 'Fix placement', status: 'completed' },
						{ id: '2', content: 'Run checks', status: 'pending' }
					]
				})
			)
		);

		expect(panel?.items).toHaveLength(2);
		expect(panel?.completed).toBe(1);
		expect(panel?.total).toBe(2);
		expect(panel?.complete).toBe(false);
		expect(panel?.key).toBe('call_todo');
	});

	it('supports direct array payloads and normalizes statuses', () => {
		const panel = extractTodoListFromOutput(
			todoOutput(
				JSON.stringify([
					{ id: '1', content: 'One', status: 'completed' },
					{ id: '2', content: 'Two', status: 'done' },
					{ id: '3', content: 'Three', status: 'in_progress' }
				])
			)
		);

		expect(panel?.completed).toBe(2);
		expect(panel?.items[1].status).toBe('completed');
		expect(panel?.items[2].status).toBe('in_progress');
	});

	it('returns null for non-todo output and malformed JSON', () => {
		expect(
			extractTodoListFromOutput([
				{
					type: 'function_call',
					id: 'fc_terminal',
					call_id: 'call_terminal',
					name: 'terminal',
					arguments: '{}',
					status: 'completed'
				}
			] as OutputItem[])
		).toBeNull();
		expect(extractTodoListFromOutput(todoOutput('{not json'))).toBeNull();
	});
});

describe('filterTodoToolOutput', () => {
	it('removes only todo function call pairs and keeps other tools', () => {
		const output = [
			...todoOutput(JSON.stringify({ todos: [{ content: 'Todo', status: 'pending' }] })),
			{
				type: 'function_call',
				id: 'fc_terminal',
				call_id: 'call_terminal',
				name: 'terminal',
				arguments: '{}',
				status: 'completed'
			},
			{
				type: 'function_call_output',
				id: 'out_terminal',
				call_id: 'call_terminal',
				status: 'completed',
				output: [{ type: 'input_text', text: 'ok' }]
			}
		] as OutputItem[];

		const filtered = filterTodoToolOutput(output);

		expect(filtered.map((item) => item.id)).toEqual(['fc_terminal', 'out_terminal']);
	});
});
