// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';

const readSource = () =>
	readFileSync(`${process.cwd()}/src/lib/components/chat/Chat.svelte`, 'utf8');

const handlerBlock = (source: string, handlerName: string): string => {
	const start = source.indexOf(`const ${handlerName}`);
	expect(start, `${handlerName} should exist`).toBeGreaterThanOrEqual(0);

	const nextHandler = source.indexOf('\n	const ', start + 1);
	return source.slice(start, nextHandler === -1 ? source.length : nextHandler);
};

describe('Chat task recency wiring', () => {
	it('imports the task recency store wrapper', () => {
		const source = readSource();
		expect(source).toContain("import { applyChatUpdateToAllTasks } from '$lib/stores/tasks';");
	});

	it('applies chat updates in each named persistence handler', () => {
		const source = readSource();
		for (const handler of [
			'chatCompletedHandler',
			'chatActionHandler',
			'initChatHandler',
			'saveChatHandler'
		]) {
			expect(handlerBlock(source, handler), `${handler} should update allTasks`).toContain(
				'applyChatUpdateToAllTasks('
			);
		}
	});

	it('applies chat updates in the temporary chat save callback', () => {
		const source = readSource();
		const start = source.indexOf('onSaveTempChat={async () => {');
		expect(start, 'onSaveTempChat callback should exist').toBeGreaterThanOrEqual(0);
		const callbackBlock = source.slice(start, source.indexOf('\n					/>', start));
		expect(callbackBlock).toContain('applyChatUpdateToAllTasks(savedChat);');
	});
});
