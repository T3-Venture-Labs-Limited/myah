import { describe, it, expect } from 'vitest';
import { computeFloatingPosition } from './floatingPosition';

function rect(top: number, left: number, width: number, height: number): DOMRect {
	return {
		top,
		left,
		width,
		height,
		bottom: top + height,
		right: left + width,
		x: left,
		y: top,
		toJSON: () => ''
	} as DOMRect;
}

describe('computeFloatingPosition', () => {
	const toolbar = { width: 280, height: 36 };
	const viewport = { width: 1280, height: 800 };
	const padding = 8;

	it('places the toolbar above the anchor when there is room', () => {
		const anchor = rect(400, 500, 100, 20);
		const pos = computeFloatingPosition({ anchor, toolbar, viewport, padding });
		// top = 400 - 36 - 8 = 356
		expect(pos.top).toBe(356);
		// horizontal: anchorCenter = 500 + 50 = 550 → left = 550 - 140 = 410
		expect(pos.left).toBe(410);
	});

	it('falls back below the anchor when above would clip the top edge', () => {
		const anchor = rect(20, 500, 100, 20);
		const pos = computeFloatingPosition({ anchor, toolbar, viewport, padding });
		// top above = 20 - 36 - 8 = -24 (clips), fallback = anchor.bottom + padding = 40 + 8 = 48
		expect(pos.top).toBe(48);
	});

	it('snaps to right viewport edge when horizontal centering would clip', () => {
		const anchor = rect(400, 1240, 30, 20);
		const pos = computeFloatingPosition({ anchor, toolbar, viewport, padding });
		// anchorCenter = 1240 + 15 = 1255 → desired left = 1255 - 140 = 1115
		// 1115 + 280 = 1395 > 1280 - 8 = 1272 → snap to viewport.width - toolbar.width - padding = 1280 - 280 - 8 = 992
		expect(pos.left).toBe(992);
	});

	it('snaps to left viewport edge when horizontal centering would clip the left side', () => {
		const anchor = rect(400, 10, 30, 20);
		const pos = computeFloatingPosition({ anchor, toolbar, viewport, padding });
		// anchorCenter = 25 → desired left = 25 - 140 = -115 < 8 → snap to padding (8)
		expect(pos.left).toBe(8);
	});
});
