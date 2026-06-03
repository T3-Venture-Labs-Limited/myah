import { describe, expect, it } from 'vitest';
import { createStreamContinuityTrace } from './streamContinuityTrace';

describe('streamContinuityTrace', () => {
	it('records bounded per-chat lifecycle events in order', () => {
		const trace = createStreamContinuityTrace({ maxEntries: 3, now: () => 1000 });

		trace.record('chat-a', 'socket:completion', { message_id: 'm1' });
		trace.record('chat-a', 'runtime:merge', { message_id: 'm1' });
		trace.record('chat-a', 'db:load:start');
		trace.record('chat-a', 'db:load:finish');

		expect(trace.entries('chat-a').map((entry) => entry.phase)).toEqual([
			'runtime:merge',
			'db:load:start',
			'db:load:finish'
		]);
	});

	it('drops content-like fields so trace output is safe to paste in PR notes', () => {
		const trace = createStreamContinuityTrace({ maxEntries: 5, now: () => 1000 });

		trace.record('chat-a', 'socket:completion', {
			message_id: 'm1',
			content: 'secret prompt text',
			output: [{ content: 'tool output' }],
			file: 'private.pdf',
			tool_args: { token: 'secret' },
			has_content: true,
			output_count: 1
		});

		expect(trace.entries('chat-a')[0].data).toEqual({
			message_id: 'm1',
			has_content: true,
			output_count: 1
		});
	});

	it('keeps independent ring buffers per chat and stamps a timestamp', () => {
		let clock = 5;
		const trace = createStreamContinuityTrace({ maxEntries: 10, now: () => clock++ });

		trace.record('chat-a', 'chat:route:mount');
		trace.record('chat-b', 'chat:route:mount');

		expect(trace.entries('chat-a')).toHaveLength(1);
		expect(trace.entries('chat-b')).toHaveLength(1);
		expect(trace.entries('chat-a')[0].at).toBe(5);
		expect(trace.entries('chat-b')[0].at).toBe(6);
		expect(trace.entries('chat-unknown')).toEqual([]);
	});

	it('ignores records for empty chat ids', () => {
		const trace = createStreamContinuityTrace({ now: () => 1 });
		trace.record('', 'chat:route:mount');
		expect(trace.entries('')).toEqual([]);
	});
});
