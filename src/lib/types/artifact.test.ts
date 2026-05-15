import { describe, it, expect } from 'vitest';
import type {
	RendererProps,
	RendererEvents,
	SelectionPayload,
	ToolbarItem,
	AnchorPayload
} from './artifact';

describe('Renderer Contract types', () => {
	it('SelectionPayload doc-text shape compiles', () => {
		const sel: SelectionPayload = {
			kind: 'doc-text',
			anchor: { startOffset: 0, endOffset: 10, contextFingerprint: 'abc' },
			preview: 'hello',
			summary: '1 paragraph · 5 words'
		};
		expect(sel.kind).toBe('doc-text');
	});

	it('SelectionPayload sheet-cells shape compiles', () => {
		const sel: SelectionPayload = {
			kind: 'sheet-cells',
			anchor: { sheet: 'Sheet1', range: 'B7:F9' },
			preview: [
				['a', 'b'],
				['c', 'd']
			],
			summary: 'B7:F9 · 4 cells'
		};
		expect(sel.kind).toBe('sheet-cells');
	});

	it('ToolbarItem placement variants compile', () => {
		const items: ToolbarItem[] = [
			{ placement: 'top', id: 'discard' },
			{ placement: 'bottom', id: 'pages' },
			{ placement: 'overlay-tl', id: 'reset' },
			{ placement: 'overlay-tr', id: 'zoom' }
		];
		expect(items).toHaveLength(4);
	});

	it('RendererProps requires filename and editable', () => {
		const props: RendererProps = {
			filename: 'foo.py',
			editable: false
		};
		expect(props.filename).toBe('foo.py');
	});

	it('ArtifactFile preserves source discriminator (agent-tool / user-click / message-attachment)', async () => {
		type AF = import('./artifact').ArtifactFile;
		const fromAgent: AF = { file_key: 'path:/tmp/a.py', filename: 'a.py', source: 'agent-tool' };
		const fromClick: AF = { file_key: 'path:/tmp/b.py', filename: 'b.py', source: 'user-click' };
		const fromMsg: AF = {
			file_key: 'file_id:abc',
			filename: 'c.png',
			source: 'message-attachment'
		};
		expect([fromAgent, fromClick, fromMsg].map((f) => f.source)).toEqual([
			'agent-tool',
			'user-click',
			'message-attachment'
		]);
	});
});
