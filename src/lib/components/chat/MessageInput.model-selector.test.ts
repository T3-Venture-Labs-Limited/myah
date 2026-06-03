// @vitest-environment node
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';

const source = (path: string) => readFileSync(`${process.cwd()}/${path}`, 'utf8');

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

	it('syncs Hermes default model using composite provider-qualified selection keys', () => {
		const selector = source('src/lib/components/chat/ModelSelector/Selector.svelte');

		expect(selector).toContain('patchAgentConfig(localStorage.token, { model: selectionKey })');
		expect(selector).toContain('selectionKey,');
		expect(selector).not.toContain('patchAgentConfig(localStorage.token, { model: modelId })');
	});

	it('re-resolves blank new-chat selection after models/defaults hydrate', () => {
		const chat = source('src/lib/components/chat/Chat.svelte');

		expect(chat).toContain("selectedModels.length === 0 || (selectedModels.length === 1 && selectedModels[0] === '')");
		expect(chat).toContain('selectedModels = resolveInitialSelectedModels({');
		expect(chat).toContain('defaultModel: $defaultModel');
		expect(chat).toContain('adminDefaults: $settings?.models ?? defaultModels');
		expect(chat).toContain('firstAvailable: availableModels?.at(0) ?? null');
	});

	it('reassigns selectedModels array when composer selector value changes', () => {
		const wrapper = source('src/lib/components/chat/ModelSelector.svelte');

		expect(wrapper).toContain('let selectedModelValue = selectedModels[0] ??');
		expect(wrapper).toContain('const incoming = selectedModels[0] ??');
		expect(wrapper).toContain('if (incoming !== selectedModelValue)');
		expect(wrapper).toContain('selectedModelValue = incoming');
		expect(wrapper).toContain('const syncSelectedModelToParent = (event?: CustomEvent<{ selectionKey?: string }>) =>');
		expect(wrapper).toContain('const nextValue = event?.detail?.selectionKey ?? selectedModelValue');
		expect(wrapper).toContain('selectedModels = [nextValue]');
		expect(wrapper).toContain('bind:value={selectedModelValue}');
		expect(wrapper).toContain('on:change={syncSelectedModelToParent}');
		expect(wrapper).not.toContain('bind:value={selectedModels[0]}');
	});

	it('clears stale parent selection when the selected model is no longer available', () => {
		const wrapper = source('src/lib/components/chat/ModelSelector.svelte');

		expect(wrapper).toContain('if (!validKeys.has(selectedModelValue))');
		expect(wrapper).toContain("selectedModelValue = ''");
		expect(wrapper).toContain("selectedModels = ['']");
	});
});
