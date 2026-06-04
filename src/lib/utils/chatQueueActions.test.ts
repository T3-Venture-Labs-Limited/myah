// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import {
	combineQueuedMessages,
	removeQueuedMessage,
	toHermesQueueCommand,
	queuedMessageHasFiles,
	type ChatQueuedMessage
} from './chatQueueActions';

const item = (overrides: Partial<ChatQueuedMessage> = {}): ChatQueuedMessage => ({
	id: 'q1',
	prompt: 'Please account for the new constraint',
	files: [],
	...overrides
});

const source = (path: string) => readFileSync(`${process.cwd()}/${path}`, 'utf8');

describe('chatQueueActions', () => {
	it('removes only the selected queued item', () => {
		const queue = [item({ id: 'q1' }), item({ id: 'q2', prompt: 'second' })];
		expect(removeQueuedMessage(queue, 'q1')).toEqual([item({ id: 'q2', prompt: 'second' })]);
	});

	it('returns the same queue when selected item is missing', () => {
		const queue = [item({ id: 'q1' })];
		expect(removeQueuedMessage(queue, 'missing')).toEqual(queue);
	});

	it('wraps steer text in a single-line Hermes /queue slash command', () => {
		expect(toHermesQueueCommand('  steer this\nwith details  ')).toBe('/queue steer this with details');
	});

	it('collapses multiline steer text so additional slash commands are not command-bearing', () => {
		expect(toHermesQueueCommand('remember this\n/stop\n/yolo')).toBe(
			'/queue remember this /stop /yolo'
		);
	});

	it('does not create an empty /queue command for blank text', () => {
		expect(toHermesQueueCommand('   ')).toBe(null);
	});

	it('combines queued prompts/files for natural drain only', () => {
		const combined = combineQueuedMessages([
			item({ id: 'a', prompt: 'first', files: [{ id: 'f1' }] }),
			item({ id: 'b', prompt: 'second', files: [{ id: 'f2' }] })
		]);
		expect(combined.prompt).toBe('first\n\nsecond');
		expect(combined.files).toEqual([{ id: 'f1' }, { id: 'f2' }]);
	});

	it('handles empty queues and missing file arrays', () => {
		expect(combineQueuedMessages([])).toEqual({ prompt: '', files: [] });
		expect(combineQueuedMessages([{ id: 'q1', prompt: '', files: undefined as unknown as any[] }])).toEqual({
			prompt: '',
			files: []
		});
	});

	it('detects whether a queued message has files', () => {
		expect(queuedMessageHasFiles(item())).toBe(false);
		expect(queuedMessageHasFiles(item({ files: [{ id: 'file-1' }] }))).toBe(true);
		expect(queuedMessageHasFiles(item({ files: undefined as unknown as any[] }))).toBe(false);
	});

	it('waits for authoritative task cleanup before draining the natural queue', () => {
		const chat = source('src/lib/components/chat/Chat.svelte');
		expect(chat).toContain('await waitForChatTasksToDrain(targetChatId);');
		expect(chat).toContain('await submitPrompt(combinedPrompt, { queuePolicy: \'bypass\' });');
		expect(chat.indexOf('await waitForChatTasksToDrain(targetChatId);')).toBeLessThan(
			chat.indexOf('chatRequestQueues.update((q) => {\n			const { [targetChatId]: _, ...rest } = q;')
		);
	});

	it('sends queued steer commands through a hidden transport instead of creating a visible chat turn', () => {
		const chat = source('src/lib/components/chat/Chat.svelte');
		expect(chat).toContain('const sendHiddenQueueCommand = async (command: string) =>');
		expect(chat).toContain('await sendHiddenQueueCommand(command);');
		expect(chat).not.toContain('await submitPrompt(command, { queuePolicy: \'bypass\' });');
	});

	it('forces interrupt-and-send past stale generating state after marking active assistants done', () => {
		const chat = source('src/lib/components/chat/Chat.svelte');
		expect(chat).toContain('markCurrentAssistantDone();');
		expect(chat).toContain('await submitPrompt(item.prompt, { queuePolicy: \'bypass\' });');
	});
});
