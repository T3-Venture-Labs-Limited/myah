import { describe, it, expect, vi, beforeAll } from 'vitest';
import { render, waitFor } from '@testing-library/svelte';
import MarkdownStub from './__test__/MarkdownStub.svelte';
import MarkdownRendererHarness from './__test__/MarkdownRendererHarness.svelte';
import type { ToolbarItem } from '$lib/types/artifact';

// jsdom's Blob lacks .text(); polyfill it.
beforeAll(() => {
	if (typeof Blob.prototype.text !== 'function') {
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		(Blob.prototype as any).text = function (): Promise<string> {
			return new Promise((resolve, reject) => {
				const reader = new FileReader();
				reader.onload = () => resolve(reader.result as string);
				reader.onerror = () => reject(reader.error);
				reader.readAsText(this as Blob);
			});
		};
	}
});

// Stub out the heavy chat Markdown component — we don't need to test its rendering,
// only that the paper-card wrapper + selection wiring + toolbar event work.
vi.mock('$lib/components/chat/Messages/Markdown.svelte', async () => {
	return { default: MarkdownStub };
});

describe('MarkdownRenderer', () => {
	const baseProps = {
		filename: 'doc.md',
		content: new Blob(['# Hello\n\nworld'])
	};

	it('renders content inside a paper card on inset background', async () => {
		const { container } = render(MarkdownRendererHarness, { props: baseProps });
		await waitFor(() => {
			expect(container.querySelector('[data-testid="md-paper-card"]')).toBeInTheDocument();
		});
	});

	it('marks the paper card as a selection listener', async () => {
		const { container } = render(MarkdownRendererHarness, { props: baseProps });
		await waitFor(() => {
			const card = container.querySelector('[data-testid="md-paper-card"]');
			expect(card?.getAttribute('data-listens-for-selection')).toBe('true');
		});
	});

	it('emits toolbar event with show-source toggle item at placement: top', async () => {
		const items: ToolbarItem[] = [];
		render(MarkdownRendererHarness, {
			props: {
				...baseProps,
				onToolbar: (toolbarItems: ToolbarItem[]) => items.push(...toolbarItems)
			}
		});

		await waitFor(() => {
			expect(items.find((x) => x.id === 'md-show-source')).toBeDefined();
		});

		const showSource = items.find((i) => i.id === 'md-show-source');
		expect(showSource?.placement).toBe('top');
	});
});
