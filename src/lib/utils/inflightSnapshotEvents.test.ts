import { describe, expect, it } from 'vitest';
import type { InflightSnapshot } from '../types';
import { snapshotUpdateFromChatCompletionEvent } from './inflightSnapshotEvents';

const event = (overrides: Record<string, unknown> = {}) => ({
	chat_id: 'chat-1',
	message_id: 'msg-1',
	data: {
		type: 'chat:completion',
		data: {
			id: 'run-1',
			done: false,
			choices: [{ delta: { content: 'hello' } }]
		}
	},
	...overrides
});

const existing = (overrides: Partial<InflightSnapshot> = {}): InflightSnapshot => ({
	run_id: 'run-1',
	chat_id: 'chat-1',
	message_id: 'msg-1',
	started_at: 100,
	updated_at: 150,
	message_content: 'hello',
	reasoning_content: '',
	output: [{ type: 'message', content: 'old' } as any],
	status: 'streaming',
	...overrides
});

describe('snapshotUpdateFromChatCompletionEvent', () => {
	it('ignores non-chat-completion events and invalid chat ids', () => {
		expect(snapshotUpdateFromChatCompletionEvent(event({ data: { type: 'status', data: {} } }))).toEqual({
			kind: 'none'
		});
		expect(snapshotUpdateFromChatCompletionEvent(event({ chat_id: '' }))).toEqual({ kind: 'none' });
		expect(snapshotUpdateFromChatCompletionEvent(event({ chat_id: 'local:abc' }))).toEqual({
			kind: 'none'
		});
		expect(snapshotUpdateFromChatCompletionEvent(event({ message_id: '' }))).toEqual({ kind: 'none' });
	});

	it('creates a streaming snapshot from a delta event', () => {
		const update = snapshotUpdateFromChatCompletionEvent(event(), null, 1_000);

		expect(update.kind).toBe('save');
		if (update.kind !== 'save') throw new Error('expected save');
		expect(update.snapshot).toMatchObject({
			run_id: 'run-1',
			chat_id: 'chat-1',
			message_id: 'msg-1',
			started_at: 1_000,
			updated_at: 1_000,
			message_content: 'hello',
			output: [],
			status: 'streaming'
		});
	});

	it('appends delta content while preserving started_at and output', () => {
		const update = snapshotUpdateFromChatCompletionEvent(
			event({ data: { type: 'chat:completion', data: { done: false, choices: [{ delta: { content: ' world' } }] } } }),
			existing(),
			1_000
		);

		expect(update.kind).toBe('save');
		if (update.kind !== 'save') throw new Error('expected save');
		expect(update.snapshot.started_at).toBe(100);
		expect(update.snapshot.message_content).toBe('hello world');
		expect(update.snapshot.output).toEqual([{ type: 'message', content: 'old' }]);
	});

	it('ignores a leading newline delta when the message is still empty', () => {
		const update = snapshotUpdateFromChatCompletionEvent(
			event({ data: { type: 'chat:completion', data: { done: false, choices: [{ delta: { content: '\n' } }] } } }),
			existing({ message_content: '' }),
			1_000
		);

		expect(update.kind).toBe('save');
		if (update.kind !== 'save') throw new Error('expected save');
		expect(update.snapshot.message_content).toBe('');
	});

	it('appends non-stream message content from choices[0].message.content', () => {
		const update = snapshotUpdateFromChatCompletionEvent(
			event({
				data: {
					type: 'chat:completion',
					data: { done: false, choices: [{ message: { content: ' world' } }] }
				}
			}),
			existing(),
			1_000
		);

		expect(update.kind).toBe('save');
		if (update.kind !== 'save') throw new Error('expected save');
		expect(update.snapshot.message_content).toBe('hello world');
	});

	it('top-level content replaces existing content and output replaces existing output', () => {
		const output = [{ type: 'function_call', name: 'terminal' } as any];
		const update = snapshotUpdateFromChatCompletionEvent(
			event({ data: { type: 'chat:completion', data: { done: false, content: 'authoritative', output } } }),
			existing(),
			1_000
		);

		expect(update.kind).toBe('save');
		if (update.kind !== 'save') throw new Error('expected save');
		expect(update.snapshot.message_content).toBe('authoritative');
		expect(update.snapshot.output).toBe(output);
	});

	it('done events preserve existing content and output when final event is sparse', () => {
		const update = snapshotUpdateFromChatCompletionEvent(
			event({ data: { type: 'chat:completion', data: { id: 'run-1', done: true } } }),
			existing(),
			1_000
		);

		expect(update.kind).toBe('complete');
		if (update.kind !== 'complete') throw new Error('expected complete');
		expect(update.snapshot.message_content).toBe('hello');
		expect(update.snapshot.output).toEqual([{ type: 'message', content: 'old' }]);
		expect(update.snapshot.status).toBe('settled');
	});

	it('does not append the same event twice when event_id matches snapshot metadata', () => {
		const update = snapshotUpdateFromChatCompletionEvent(
			event({ event_id: 'evt-1' }),
			existing({ message_content: 'hello', last_event_id: 'evt-1' } as any),
			1_000
		);

		expect(update.kind).toBe('none');
	});
});
