import { describe, it, expect, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/svelte';
import VideoRenderer from './VideoRenderer.svelte';
import type { ToolbarItem, SelectionPayload } from '$lib/types/artifact';

// jsdom doesn't implement HTMLMediaElement.play / pause / load / duration;
// these are no-op stubs.
beforeEach(() => {
	HTMLMediaElement.prototype.play = function () {
		return Promise.resolve();
	};
	HTMLMediaElement.prototype.pause = function () {};
	HTMLMediaElement.prototype.load = function () {};
	Object.defineProperty(HTMLMediaElement.prototype, 'duration', {
		configurable: true,
		get() {
			return 60;
		}
	});
});

describe('VideoRenderer', () => {
	const baseProps = {
		filename: 'clip.mp4',
		file_id: 'abc-123',
		editable: false
	};

	it('renders dark canvas wrapping the video', async () => {
		const { container } = render(VideoRenderer, { props: baseProps });
		for (let i = 0; i < 10; i++) {
			if (container.querySelector('[data-testid="video-canvas"]')) break;
			await new Promise((r) => setTimeout(r, 25));
		}
		expect(container.querySelector('[data-testid="video-canvas"]')).toBeInTheDocument();
	});

	it('renders custom timeline + play/pause control', async () => {
		const { container } = render(VideoRenderer, { props: baseProps });
		for (let i = 0; i < 10; i++) {
			if (container.querySelector('[data-testid="video-timeline"]')) break;
			await new Promise((r) => setTimeout(r, 25));
		}
		expect(container.querySelector('[data-testid="video-timeline"]')).toBeInTheDocument();
		expect(container.querySelector('[data-testid="video-playpause"]')).toBeInTheDocument();
	});

	it('emits toolbar event with mode-toggle + PiP + fullscreen items at overlay-tr', async () => {
		const { default: Harness } = await import('./__test__/VideoRendererHarness.svelte');
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
			if (items.length >= 4) break;
			await new Promise((r) => setTimeout(r, 25));
		}
		expect(items.find((i) => i.id === 'mode-move')?.placement).toBe('overlay-tr');
		expect(items.find((i) => i.id === 'mode-select')?.placement).toBe('overlay-tr');
		expect(items.find((i) => i.id === 'video-pip')?.placement).toBe('overlay-tr');
		expect(items.find((i) => i.id === 'video-fullscreen')?.placement).toBe('overlay-tr');
	});

	it('emits video-region select on timeline drag', async () => {
		const { default: Harness } = await import('./__test__/VideoRendererHarness.svelte');
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
			if (container.querySelector('[data-testid="video-timeline"]')) break;
			await new Promise((r) => setTimeout(r, 25));
		}
		const timeline = container.querySelector('[data-testid="video-timeline"]') as HTMLElement;
		Object.defineProperty(timeline, 'getBoundingClientRect', {
			value: () => ({
				left: 0,
				top: 0,
				width: 600,
				height: 20,
				x: 0,
				y: 0,
				right: 600,
				bottom: 20,
				toJSON: () => ''
			})
		});

		// Trigger a `loadedmetadata` synthesis: query the video element + simulate.
		const videoEl = container.querySelector('video') as HTMLVideoElement;
		if (videoEl) {
			videoEl.dispatchEvent(new Event('loadedmetadata'));
		}

		await fireEvent.mouseDown(timeline, { clientX: 100, clientY: 10 });
		await fireEvent.mouseMove(timeline, { clientX: 300, clientY: 10 });
		await fireEvent.mouseUp(timeline, { clientX: 300, clientY: 10 });

		expect(events.length).toBeGreaterThan(0);
		const sel = events[events.length - 1];
		expect(sel.kind).toBe('video-region');
		if (sel.kind === 'video-region') {
			// duration=60, timeline 0-600px → 100px = 10s, 300px = 30s
			expect(sel.anchor.startSeconds).toBeCloseTo(10, 0);
			expect(sel.anchor.endSeconds).toBeCloseTo(30, 0);
			// No spatial bbox on a pure timeline drag.
			expect(sel.anchor.xPct).toBeUndefined();
			expect(sel.anchor.wPct).toBeUndefined();
		}
	});

	// Regression: drag-to-region on the video frame in Select mode emits a
	// payload that carries BOTH the current playhead and the spatial bbox.
	it('emits video-region select with spatial bbox when frame-drag fires in select mode', async () => {
		const { default: Harness } = await import('./__test__/VideoRendererHarness.svelte');
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
			if (container.querySelector('[data-testid="video-frame"]')) break;
			await new Promise((r) => setTimeout(r, 25));
		}
		// Switch into select mode.
		const selectBtn = container.querySelector(
			'[data-testid="video-mode-select"]'
		) as HTMLElement;
		expect(selectBtn).toBeTruthy();
		await fireEvent.click(selectBtn);

		const frame = container.querySelector('[data-testid="video-frame"]') as HTMLElement;
		Object.defineProperty(frame, 'getBoundingClientRect', {
			value: () => ({
				left: 0,
				top: 0,
				width: 800,
				height: 400,
				x: 0,
				y: 0,
				right: 800,
				bottom: 400,
				toJSON: () => ''
			})
		});

		await fireEvent.mouseDown(frame, { clientX: 80, clientY: 40 });
		await fireEvent.mouseMove(frame, { clientX: 480, clientY: 240 });
		await fireEvent.mouseUp(frame, { clientX: 480, clientY: 240 });

		expect(events.length).toBeGreaterThan(0);
		const sel = events[events.length - 1];
		expect(sel.kind).toBe('video-region');
		if (sel.kind === 'video-region') {
			// (80/800, 40/400) → (10%, 10%); width=400/800=50%, height=200/400=50%
			expect(sel.anchor.xPct).toBeCloseTo(10, 0);
			expect(sel.anchor.yPct).toBeCloseTo(10, 0);
			expect(sel.anchor.wPct).toBeCloseTo(50, 0);
			expect(sel.anchor.hPct).toBeCloseTo(50, 0);
			// startSeconds === endSeconds on a pure spatial pick (single moment).
			expect(sel.anchor.startSeconds).toBe(sel.anchor.endSeconds);
		}
	});

	it('does NOT emit a frame-region selection while in default move mode', async () => {
		const { default: Harness } = await import('./__test__/VideoRendererHarness.svelte');
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
			if (container.querySelector('[data-testid="video-frame"]')) break;
			await new Promise((r) => setTimeout(r, 25));
		}

		const frame = container.querySelector('[data-testid="video-frame"]') as HTMLElement;
		Object.defineProperty(frame, 'getBoundingClientRect', {
			value: () => ({
				left: 0,
				top: 0,
				width: 800,
				height: 400,
				x: 0,
				y: 0,
				right: 800,
				bottom: 400,
				toJSON: () => ''
			})
		});

		await fireEvent.mouseDown(frame, { clientX: 80, clientY: 40 });
		await fireEvent.mouseMove(frame, { clientX: 480, clientY: 240 });
		await fireEvent.mouseUp(frame, { clientX: 480, clientY: 240 });

		// Default mode is 'move' — frame drags are ignored, no event emitted.
		expect(events).toHaveLength(0);
	});
});
