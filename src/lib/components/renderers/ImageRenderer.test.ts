import { describe, it, expect } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import ImageRenderer from './ImageRenderer.svelte';
import type { ToolbarItem, SelectionPayload } from '$lib/types/artifact';

describe('ImageRenderer', () => {
	const baseProps = {
		filename: 'chart.png',
		file_id: 'abc-123',
		editable: false
	};

	it('renders a dark canvas wrapping the image', async () => {
		const { container } = render(ImageRenderer, { props: baseProps });
		// Wait for the canvas to mount.
		for (let i = 0; i < 10; i++) {
			if (container.querySelector('[data-testid="image-canvas"]')) break;
			await new Promise((r) => setTimeout(r, 25));
		}
		const canvas = container.querySelector('[data-testid="image-canvas"]');
		expect(canvas).toBeInTheDocument();
		expect(canvas?.className ?? '').toContain('bg-gray-900');
	});

	it('emits toolbar event with mode + reset/zoom items at overlay-tr', async () => {
		const { default: Harness } = await import('./__test__/ImageRendererHarness.svelte');
		const items: ToolbarItem[] = [];
		render(Harness, {
			props: {
				rendererProps: baseProps,
				onToolbar: (e: ToolbarItem[]) => {
					items.length = 0;
					items.push(...e);
				}
			}
		});
		for (let i = 0; i < 10; i++) {
			if (items.length > 0) break;
			await new Promise((r) => setTimeout(r, 25));
		}
		const ids = items.map((i) => i.id);
		// New: explicit move/select mode toggle alongside the zoom triplet.
		expect(ids).toContain('mode-move');
		expect(ids).toContain('mode-select');
		expect(ids).toContain('reset-zoom');
		expect(ids).toContain('zoom-in');
		expect(ids).toContain('zoom-out');
		// All five at overlay-tr
		expect(items.every((i) => i.placement === 'overlay-tr')).toBe(true);
	});

	it('does NOT emit a region selection while in default move mode', async () => {
		const { default: Harness } = await import('./__test__/ImageRendererHarness.svelte');
		const events: SelectionPayload[] = [];
		const { container } = render(Harness, {
			props: {
				rendererProps: baseProps,
				onSelect: (e: SelectionPayload | null) => {
					if (e) events.push(e);
				}
			}
		});
		for (let i = 0; i < 10; i++) {
			if (container.querySelector('[data-testid="image-region-overlay"]')) break;
			await new Promise((r) => setTimeout(r, 25));
		}
		const overlay = container.querySelector('[data-testid="image-region-overlay"]') as HTMLElement;
		expect(overlay).toBeTruthy();

		Object.defineProperty(overlay, 'getBoundingClientRect', {
			value: () => ({
				left: 0,
				top: 0,
				width: 1000,
				height: 500,
				x: 0,
				y: 0,
				right: 1000,
				bottom: 500,
				toJSON: () => ''
			})
		});

		// Default mode is 'move' — drag should be ignored by the selection
		// handler and panzoom owns the gesture.
		await fireEvent.mouseDown(overlay, { clientX: 100, clientY: 50 });
		await fireEvent.mouseMove(overlay, { clientX: 300, clientY: 200 });
		await fireEvent.mouseUp(overlay, { clientX: 300, clientY: 200 });

		expect(events).toHaveLength(0);
	});

	it('emits image-region select on drag after switching to select mode', async () => {
		const { default: Harness } = await import('./__test__/ImageRendererHarness.svelte');
		const events: SelectionPayload[] = [];
		const { container } = render(Harness, {
			props: {
				rendererProps: baseProps,
				onSelect: (e: SelectionPayload | null) => {
					if (e) events.push(e);
				}
			}
		});
		for (let i = 0; i < 10; i++) {
			if (container.querySelector('[data-testid="image-region-overlay"]')) break;
			await new Promise((r) => setTimeout(r, 25));
		}
		const overlay = container.querySelector('[data-testid="image-region-overlay"]') as HTMLElement;
		expect(overlay).toBeTruthy();

		Object.defineProperty(overlay, 'getBoundingClientRect', {
			value: () => ({
				left: 0,
				top: 0,
				width: 1000,
				height: 500,
				x: 0,
				y: 0,
				right: 1000,
				bottom: 500,
				toJSON: () => ''
			})
		});

		// Switch into select mode via the toolbar button.
		const selectBtn = container.querySelector(
			'[data-testid="image-mode-select"]'
		) as HTMLElement;
		expect(selectBtn).toBeTruthy();
		await fireEvent.click(selectBtn);

		await fireEvent.mouseDown(overlay, { clientX: 100, clientY: 50 });
		await fireEvent.mouseMove(overlay, { clientX: 300, clientY: 200 });
		await fireEvent.mouseUp(overlay, { clientX: 300, clientY: 200 });

		expect(events.length).toBeGreaterThan(0);
		const sel = events[events.length - 1];
		expect(sel.kind).toBe('image-region');
		if (sel.kind === 'image-region') {
			// (100/1000, 50/500) = (10%, 10%); (300-100)/1000=20%, (200-50)/500=30%
			expect(sel.anchor.xPct).toBeCloseTo(10, 1);
			expect(sel.anchor.yPct).toBeCloseTo(10, 1);
			expect(sel.anchor.wPct).toBeCloseTo(20, 1);
			expect(sel.anchor.hPct).toBeCloseTo(30, 1);
		}
	});
});
