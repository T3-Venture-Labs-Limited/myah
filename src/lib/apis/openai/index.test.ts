import { describe, expect, it, vi, beforeEach } from 'vitest';

import { generateOpenAIChatCompletion } from './index';

describe('generateOpenAIChatCompletion', () => {
	beforeEach(() => {
		vi.restoreAllMocks();
	});

	it('returns event-stream responses without trying to parse them as JSON', async () => {
		const stream = new ReadableStream({
			start(controller) {
				controller.enqueue(new TextEncoder().encode('data: {"choices":[]}\n\n'));
				controller.close();
			}
		});
		const response = new Response(stream, {
			status: 200,
			headers: { 'Content-Type': 'text/event-stream' }
		});

		global.fetch = vi.fn().mockResolvedValue(response) as unknown as typeof fetch;

		const result = await generateOpenAIChatCompletion(
			'token',
			{ stream: true },
			'http://localhost/api'
		);

		expect(result).toBe(response);
		expect(global.fetch).toHaveBeenCalledWith(
			'http://localhost/api/chat/completions',
			expect.objectContaining({ method: 'POST' })
		);
	});

	it('still parses JSON completion responses', async () => {
		global.fetch = vi.fn().mockResolvedValue(
			new Response(JSON.stringify({ task_id: 'task-1' }), {
				status: 200,
				headers: { 'Content-Type': 'application/json' }
			})
		) as unknown as typeof fetch;

		await expect(
			generateOpenAIChatCompletion('token', { stream: false }, 'http://localhost/api')
		).resolves.toEqual({ task_id: 'task-1' });
	});
});
