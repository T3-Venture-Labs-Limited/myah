import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { get } from 'svelte/store';
import RefChipBar from './RefChipBar.svelte';
import { composerRefs, artifactPendingEdits } from '$lib/stores';
import type { SelectionPayload } from '$lib/types/artifact';

const docTextSelection: SelectionPayload = {
	kind: 'doc-text',
	anchor: { startOffset: 0, endOffset: 5, contextFingerprint: '|hello' },
	preview: 'hello',
	summary: 'doc-text 0-5'
};

describe('RefChipBar', () => {
	beforeEach(() => {
		composerRefs.set([]);
		artifactPendingEdits.set(new Map());
		// Default confirm to true; individual tests can override.
		vi.stubGlobal('confirm', vi.fn(() => true));
	});

	it('renders nothing when no chips', () => {
		const { container } = render(RefChipBar);
		expect(container.querySelector('[data-testid="ref-chip-bar"]')).toBeNull();
	});

	it('renders one chip per composerRefs entry plus per pending edit', () => {
		composerRefs.set([{ ...docTextSelection, id: 'ref-1', filename: 'notes.md' }]);
		artifactPendingEdits.set(
			new Map([['path:/tmp/foo.py', { filename: 'foo.py', diff: '-old\n+new\n' }]])
		);
		render(RefChipBar);
		const chips = screen.getAllByTestId('ref-chip');
		expect(chips).toHaveLength(2);
		expect(chips[0].textContent).toMatch(/notes\.md/);
		expect(chips[1].textContent).toMatch(/foo\.py/);
	});

	it('removing a user-ref chip filters composerRefs', async () => {
		composerRefs.set([
			{ ...docTextSelection, id: 'ref-1', filename: 'a.md' },
			{ ...docTextSelection, id: 'ref-2', filename: 'b.md' }
		]);
		render(RefChipBar);
		const removeButtons = screen.getAllByRole('button', { name: /Remove .* chip/ });
		await fireEvent.click(removeButtons[0]); // remove ref-1
		expect(get(composerRefs).map((r) => r.id)).toEqual(['ref-2']);
	});

	it('removing a file-edit chip prompts confirm and (when accepted) deletes from artifactPendingEdits', async () => {
		const confirmSpy = vi.fn(() => true);
		vi.stubGlobal('confirm', confirmSpy);
		artifactPendingEdits.set(
			new Map([['path:/tmp/foo.py', { filename: 'foo.py', diff: '-old\n+new\n' }]])
		);
		render(RefChipBar);
		await fireEvent.click(screen.getByRole('button', { name: /Remove foo\.py chip/ }));
		expect(confirmSpy).toHaveBeenCalledWith('Discard your edits to foo.py?');
		expect(get(artifactPendingEdits).size).toBe(0);
	});

	it('removing a file-edit chip with confirm=false leaves artifactPendingEdits intact', async () => {
		vi.stubGlobal('confirm', vi.fn(() => false));
		artifactPendingEdits.set(
			new Map([['path:/tmp/foo.py', { filename: 'foo.py', diff: '-old\n+new\n' }]])
		);
		render(RefChipBar);
		await fireEvent.click(screen.getByRole('button', { name: /Remove foo\.py chip/ }));
		expect(get(artifactPendingEdits).size).toBe(1);
	});
});
