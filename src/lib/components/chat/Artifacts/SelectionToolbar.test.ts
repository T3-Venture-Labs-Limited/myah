import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';
import SelectionToolbar from './SelectionToolbar.svelte';
import { artifactSelection, composerRefs } from '$lib/stores';
import type { SelectionPayload } from '$lib/types/artifact';

const docTextSelection: SelectionPayload = {
	kind: 'doc-text',
	anchor: { startOffset: 0, endOffset: 5, contextFingerprint: '|hello' },
	preview: 'hello',
	summary: 'doc-text 0-5'
};

describe('SelectionToolbar', () => {
	beforeEach(() => {
		artifactSelection.set(null);
		composerRefs.set([]);
	});

	it('renders nothing when artifactSelection is null', () => {
		const { container } = render(SelectionToolbar);
		expect(container.querySelector('[data-testid="selection-toolbar"]')).toBeNull();
	});

	it('renders summary, Add to chat, and Copy buttons when selection exists', () => {
		artifactSelection.set(docTextSelection);
		render(SelectionToolbar);
		expect(screen.getByText('doc-text 0-5')).toBeInTheDocument();
		expect(screen.getByTestId('selection-toolbar-add')).toBeInTheDocument();
		expect(screen.getByTestId('selection-toolbar-copy')).toBeInTheDocument();
	});

	it('Add to chat pushes the selection to composerRefs and clears artifactSelection', async () => {
		artifactSelection.set(docTextSelection);
		render(SelectionToolbar, { props: { filename: 'notes.md' } });
		await fireEvent.click(screen.getByTestId('selection-toolbar-add'));
		const refs = get(composerRefs);
		expect(refs).toHaveLength(1);
		expect(refs[0]).toMatchObject({
			kind: 'doc-text',
			preview: 'hello',
			filename: 'notes.md'
		});
		expect(refs[0].id).toMatch(/^ref-/);
		expect(get(artifactSelection)).toBeNull();
	});

	it('Copy writes preview to clipboard for doc-text', async () => {
		const writeText = vi.fn().mockResolvedValue(undefined);
		Object.assign(navigator, { clipboard: { writeText } });
		artifactSelection.set(docTextSelection);
		render(SelectionToolbar);
		await fireEvent.click(screen.getByTestId('selection-toolbar-copy'));
		// Wait a tick for the async handler.
		await Promise.resolve();
		expect(writeText).toHaveBeenCalledWith('hello');
	});

	it('Cancel button clears the selection and unmounts the toolbar', async () => {
		artifactSelection.set(docTextSelection);
		const { container } = render(SelectionToolbar);
		expect(container.querySelector('[data-testid="selection-toolbar"]')).toBeInTheDocument();
		await fireEvent.click(screen.getByTestId('selection-toolbar-cancel'));
		expect(get(artifactSelection)).toBeNull();
		// Toolbar is gated on $artifactSelection so it should be removed from DOM.
		expect(container.querySelector('[data-testid="selection-toolbar"]')).toBeNull();
	});

	it('Esc key clears the selection while the toolbar is mounted', async () => {
		artifactSelection.set(docTextSelection);
		render(SelectionToolbar);
		expect(get(artifactSelection)).not.toBeNull();
		await fireEvent.keyDown(window, { key: 'Escape' });
		expect(get(artifactSelection)).toBeNull();
	});

	it('Esc keydown listener is removed when the toolbar unmounts', async () => {
		artifactSelection.set(docTextSelection);
		const { unmount } = render(SelectionToolbar);
		unmount();
		// Selection still null after unmount; pressing Esc must not throw or
		// re-toggle anything because the listener is detached. We assert by
		// checking the keydown handler is gone — easiest proxy is dispatching
		// Escape on the window and confirming no error / no state change
		// on a fresh selection set after unmount.
		artifactSelection.set(docTextSelection);
		await fireEvent.keyDown(window, { key: 'Escape' });
		// If the unmounted listener were still attached, the line above
		// would clear the selection. Confirm it didn't.
		expect(get(artifactSelection)).not.toBeNull();
	});
});
