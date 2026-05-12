// Every request sent from here is a petition. May it reach
// the one for whom it was intended, and return answered.

import type { SelectionPayload } from '$lib/types/artifact';

// Tag the agent reads. Wrapped in clear sentinels so the model can identify
// where the user's attached content begins and ends, and treat the prose
// after as the actual prompt. Mirrors the [CURRENT_UI_STATE] convention from
// hermes-agent#17 but lives in the message body instead of channel_prompt,
// so it works without the upstream Hermes adapter change. The tag is opaque
// to chat history rendering — the chat bubble shows refs as chips and the
// prose after the END marker as the visible message content.
const REF_BLOCK_OPEN = '[USER_REFERENCED]';
const REF_BLOCK_CLOSE = '[/USER_REFERENCED]';
const REF_PREVIEW_TRUNCATE = 1500;

export interface UIStateRefSerialized {
	id: string;
	kind: SelectionPayload['kind'];
	file_key: string;
	filename: string;
	anchor: SelectionPayload['anchor'];
	preview?: string;
	summary: string;
}

export interface UIStatePendingEdit {
	file_key: string;
	filename: string;
	diff: string;
}

export interface UIState {
	selectionRefs: UIStateRefSerialized[];
	pendingEdits: UIStatePendingEdit[];
}

const PREVIEW_TRUNCATE = 1500;
const DIFF_TRUNCATE = 3000;

/**
 * Build a `[USER_REFERENCED]` block that prepends to the user's prompt when
 * sent to the LLM. Until hermes-agent#17 lands, the agent doesn't read
 * `channel_prompt` from the platform's `ui_state` field — so we surface the
 * referenced content directly in the message body. The agent treats this as
 * pre-prompt context: "the user is asking about X; the X is attached above".
 *
 * Returns the raw string to prepend (with trailing newline) — empty string
 * if there are no refs to include.
 */
export function buildRefContextBlock(
	refs: Array<SelectionPayload & { id: string; filename: string; file_key?: string }>
): string {
	if (!refs || refs.length === 0) return '';
	const parts: string[] = [];
	parts.push(REF_BLOCK_OPEN);
	parts.push(
		'The user has attached the following selections from their workspace ' +
			'as context for the question that follows. Treat these as part of ' +
			'their question — they are referring to this content explicitly.'
	);
	for (const ref of refs) {
		parts.push('');
		parts.push(`— ${ref.filename} · ${ref.summary}`);
		if (ref.kind === 'doc-text' || ref.kind === 'code-lines') {
			let preview = String(ref.preview ?? '');
			if (preview.length > REF_PREVIEW_TRUNCATE) {
				preview =
					preview.slice(0, REF_PREVIEW_TRUNCATE) +
					` ... [content truncated, ${preview.length - REF_PREVIEW_TRUNCATE} chars omitted]`;
			}
			const fence = ref.kind === 'code-lines' ? '```' + (ref.anchor.language || '') : '```';
			parts.push(fence);
			parts.push(preview);
			parts.push('```');
		} else if (ref.kind === 'sheet-cells') {
			const csv = ref.preview.map((row) => row.join('\t')).join('\n');
			const truncated =
				csv.length > REF_PREVIEW_TRUNCATE
					? csv.slice(0, REF_PREVIEW_TRUNCATE) + ` ... [content truncated]`
					: csv;
			parts.push('```tsv');
			parts.push(truncated);
			parts.push('```');
		} else if (ref.kind === 'image-region') {
			parts.push(
				`(image region — ${ref.anchor.wPct.toFixed(0)}% × ${ref.anchor.hPct.toFixed(0)}% at ` +
					`${ref.anchor.xPct.toFixed(0)}%, ${ref.anchor.yPct.toFixed(0)}%)`
			);
		} else if (ref.kind === 'video-region') {
			parts.push(
				`(video region — ${ref.anchor.startSeconds.toFixed(2)}s..${ref.anchor.endSeconds.toFixed(2)}s)`
			);
		}
	}
	parts.push(REF_BLOCK_CLOSE);
	parts.push('');
	return parts.join('\n');
}

export function assembleUIState(
	refs: Array<SelectionPayload & { id: string; filename: string; file_key?: string }>,
	edits: Map<string, { filename: string; diff: string }>
): UIState {
	const selectionRefs: UIStateRefSerialized[] = refs.map((ref) => {
		const fileKey = ref.file_key ?? `path:/unknown/${ref.filename}`;
		const baseRef: UIStateRefSerialized = {
			id: ref.id,
			kind: ref.kind,
			file_key: fileKey,
			filename: ref.filename,
			anchor: ref.anchor,
			summary: ref.summary
		};
		// Preview shape varies by kind — only text-like kinds get the preview field.
		if (ref.kind === 'doc-text' || ref.kind === 'code-lines') {
			const p = String(ref.preview ?? '');
			baseRef.preview =
				p.length > PREVIEW_TRUNCATE
					? p.slice(0, PREVIEW_TRUNCATE) +
						` ... [content truncated, ${p.length - PREVIEW_TRUNCATE} chars omitted]`
					: p;
		} else if (ref.kind === 'sheet-cells') {
			const csv = ref.preview.map((row) => row.join('\t')).join('\n');
			baseRef.preview =
				csv.length > PREVIEW_TRUNCATE
					? csv.slice(0, PREVIEW_TRUNCATE) + ` ... [content truncated]`
					: csv;
		}
		// image-region and video-region intentionally omit preview (they carry binary refs only).
		return baseRef;
	});

	const pendingEdits: UIStatePendingEdit[] = [...edits].map(([file_key, value]) => {
		const diff =
			value.diff.length > DIFF_TRUNCATE
				? value.diff.slice(0, DIFF_TRUNCATE) +
					` ... [diff truncated, ${value.diff.length - DIFF_TRUNCATE} chars omitted]`
				: value.diff;
		return { file_key, filename: value.filename, diff };
	});

	return { selectionRefs, pendingEdits };
}
