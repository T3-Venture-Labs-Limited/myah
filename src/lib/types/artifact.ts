// ── Anchor payloads (per kind) ──────────────────────────────────────
export interface DocTextAnchor {
	startOffset: number;
	endOffset: number;
	contextFingerprint: string; // ~50 chars before + after, used for stable scroll-to-anchor
}

export interface SheetCellsAnchor {
	sheet: string; // sheet name
	range: string; // A1-style range, e.g. 'B7:F9'
}

export interface ImageRegionAnchor {
	xPct: number;
	yPct: number;
	wPct: number;
	hPct: number;
}

export interface VideoRegionAnchor {
	startSeconds: number;
	endSeconds: number;
	// Optional spatial bbox — populated when the user drags on the video
	// frame in "Select" mode rather than (or in addition to) the timeline.
	// Values are percentages of the rendered <video> element so they survive
	// resolution / aspect changes. When all four are absent, the selection
	// is purely temporal (timeline drag).
	xPct?: number;
	yPct?: number;
	wPct?: number;
	hPct?: number;
}

export interface CodeLinesAnchor {
	startLine: number;
	endLine: number;
	language: string;
}

export type AnchorPayload =
	| DocTextAnchor
	| SheetCellsAnchor
	| ImageRegionAnchor
	| VideoRegionAnchor
	| CodeLinesAnchor;

// ── Discriminated SelectionPayload union ────────────────────────────
export type SelectionPayload =
	| { kind: 'doc-text'; anchor: DocTextAnchor; preview: string; summary: string }
	| { kind: 'sheet-cells'; anchor: SheetCellsAnchor; preview: string[][]; summary: string }
	| {
			kind: 'image-region';
			anchor: ImageRegionAnchor;
			preview: { dataUrl: string };
			summary: string;
	  }
	| {
			kind: 'video-region';
			anchor: VideoRegionAnchor;
			preview: { thumbnailDataUrl: string };
			summary: string;
	  }
	| { kind: 'code-lines'; anchor: CodeLinesAnchor; preview: string; summary: string };

// ── Toolbar contributions ───────────────────────────────────────────
export type ToolbarPlacement = 'top' | 'bottom' | 'overlay-tl' | 'overlay-tr';

export interface ToolbarItem {
	placement: ToolbarPlacement;
	id: string;
	label?: string;
	icon?: string;
	onClick?: () => void;
	// For richer items like sheet tab strips, the renderer can pass a Svelte component
	// (the host mounts it inside the toolbar slot styling).
	component?: unknown;
}

// ── Props every renderer accepts ────────────────────────────────────
export interface RendererProps {
	// Source — exactly one of these is set by the host.
	file_id?: string;
	path?: string;
	content?: Blob | string;

	// Identity
	filename: string;
	mime?: string;

	// Reactive freshness — host updates when artifact mtime changes.
	mtime?: number;

	// Editing
	editable: boolean;

	// Pending diff overlay payload.
	pendingDiff?: { from: string; to: string };
}

// ── Events every renderer can emit ──────────────────────────────────
export interface RendererEvents {
	select: SelectionPayload | null;
	dirty: { isDirty: boolean; diff?: string };
	discard: void;
	error: Error;
	toolbar: { items: ToolbarItem[] };
}

// ── ArtifactFile (used by Open files / explorer / tabs) ─────────────
export interface ArtifactFile {
	// Stable key combining source kind + identifier; used as Map key for pending edits.
	file_key: string; // 'file_id:<uuid>' or 'path:<abs-path>'
	file_id?: string;
	path?: string;
	filename: string;
	mime?: string;
	size?: number;
	mtime?: number;
	// How this file landed in the open-files list. Existing consumers
	// (MarkdownInlineTokens.svelte:48,60 and Chat.svelte:511) already write
	// this field on the legacy currentArtifactFile shape; preserved here so
	// the migration in Task 1.2 doesn't lose the discriminator.
	source: 'agent-tool' | 'user-click' | 'message-attachment';
}
