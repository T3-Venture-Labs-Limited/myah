import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import RefChip from './RefChip.svelte';
import RefChipHarness from './__test__/RefChipHarness.svelte';
import type { RefChip as RefChipT } from '$lib/stores';

const baseChip: RefChipT = {
	id: 'ref-1',
	kind: 'doc-text',
	filename: 'notes.md',
	summary: 'doc-text 0-5',
	payload: {}
};

// Svelte 5 removed component.$on; createEventDispatcher events go to parent
// component listeners (on:event) and not to the DOM. Tests that need to
// observe dispatched events use RefChipHarness which forwards them via
// callback props.
describe('RefChip', () => {
	it('renders filename and summary', () => {
		render(RefChip, { props: { chip: baseChip } });
		expect(screen.getByText(/notes\.md.*doc-text 0-5/)).toBeInTheDocument();
	});

	it('applies kind-specific bg class for doc-text', () => {
		const { container } = render(RefChip, { props: { chip: baseChip } });
		const chipEl = container.querySelector('[data-testid="ref-chip"]');
		expect(chipEl?.className).toMatch(/bg-pink-500\/10/);
	});

	it('applies kind-specific bg class for sheet-cells', () => {
		const { container } = render(RefChip, {
			props: { chip: { ...baseChip, kind: 'sheet-cells' } }
		});
		const chipEl = container.querySelector('[data-testid="ref-chip"]');
		expect(chipEl?.className).toMatch(/bg-green-500\/10/);
	});

	it('applies kind-specific bg class for file-edit', () => {
		const { container } = render(RefChip, {
			props: { chip: { ...baseChip, kind: 'file-edit' } }
		});
		const chipEl = container.querySelector('[data-testid="ref-chip"]');
		expect(chipEl?.className).toMatch(/bg-orange-500\/10/);
	});

	it('dispatches remove event with chip id when ✕ clicked', async () => {
		const events: string[] = [];
		render(RefChipHarness, {
			props: { chip: baseChip, onRemove: (id: string) => events.push(id) }
		});
		await fireEvent.click(screen.getByRole('button', { name: /Remove notes\.md chip/ }));
		expect(events).toEqual(['ref-1']);
	});
});
