import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const source = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('composer model selector placement', () => {
	it('renders the model selector from MessageInput with a composer-specific trigger', () => {
		const messageInput = source('src/lib/components/chat/MessageInput.svelte');

		expect(messageInput).toContain('data-testid="composer-model-selector"');
		expect(messageInput).toContain('max-w-[10rem] sm:max-w-[14rem]');
		expect(messageInput).not.toContain('hidden sm:flex');
		expect(messageInput).toContain('id="composer"');
		expect(messageInput).toContain('side="top"');
		expect(messageInput).toContain('bind:selectedModels');
	});

	it('keeps selected model state bound through Chat into MessageInput', () => {
		const chat = source('src/lib/components/chat/Chat.svelte');
		const messageInputInvocation = chat.match(/<MessageInput[\s\S]*?\/>/);

		expect(messageInputInvocation?.[0]).toContain('bind:selectedModels');
		expect(messageInputInvocation?.[0]).not.toContain('\n\t\t\t\t\t\t\t{selectedModels}');
	});

	it('removes the top-left navbar model picker by default while preserving opt-in support', () => {
		const navbar = source('src/lib/components/chat/Navbar.svelte');

		expect(navbar).toContain('export let showModelSelector = false');
		expect(navbar).toContain('showModelSelector');
		expect(navbar).toContain('<ModelSelector bind:selectedModels />');
	});

	it('passes compact/id/side props through the ModelSelector wrapper', () => {
		const wrapper = source('src/lib/components/chat/ModelSelector.svelte');
		const selector = source('src/lib/components/chat/ModelSelector/Selector.svelte');

		expect(wrapper).toContain("export let id = '0'");
		expect(wrapper).toContain('export let compact = false');
		expect(wrapper).toContain("export let side: 'top' | 'bottom' = 'bottom'");
		expect(wrapper).toContain('{id}');
		expect(wrapper).toContain('{side}');
		expect(wrapper).toContain('triggerClassName={compact');
		expect(selector).toContain("export let side: 'top' | 'bottom' = 'bottom'");
		expect(selector).toContain('side={side}');
	});
});
