// A small position arrives where a wider one would clip;
// the toolbar finds its frame, then settles in.

export interface ComputeArgs {
	anchor: DOMRect;
	toolbar: { width: number; height: number };
	viewport: { width: number; height: number };
	padding: number;
}

export interface FloatingPosition {
	top: number;
	left: number;
}

/**
 * Compute the position of a floating toolbar relative to its anchor's
 * bounding rect. Defaults to placing the toolbar above the anchor, falls
 * back to below if it would clip, and snaps to viewport edges if the
 * horizontal centering would clip.
 */
export function computeFloatingPosition(args: ComputeArgs): FloatingPosition {
	const { anchor, toolbar, viewport, padding } = args;
	let top = anchor.top - toolbar.height - padding;
	if (top < padding) {
		top = anchor.bottom + padding;
	}
	const anchorCenter = anchor.left + anchor.width / 2;
	let left = anchorCenter - toolbar.width / 2;
	if (left < padding) left = padding;
	if (left + toolbar.width > viewport.width - padding) {
		left = viewport.width - toolbar.width - padding;
	}
	return { top, left };
}
