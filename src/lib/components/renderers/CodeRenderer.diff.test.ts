import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import CodeRenderer from './CodeRenderer.svelte';

describe('CodeRenderer pendingDiff branch', () => {
	it('renders MergeView when pendingDiff is set', async () => {
		const { container } = render(CodeRenderer, {
			props: {
				filename: 'foo.py',
				content: 'print("old")\n',
				editable: true,
				pendingDiff: { from: 'print("old")\n', to: 'print("new")\n' }
			}
		});
		// Wait for mount
		for (let i = 0; i < 20; i++) {
			if (container.querySelector('[data-testid="merge-view"], .cm-merge-view, .cm-mergeView'))
				break;
			await new Promise((r) => setTimeout(r, 25));
		}
		// CodeMirror's MergeView renders with .cm-mergeView class; we also
		// tag the wrapper with data-testid="merge-view" for direct selection.
		const mergeView = container.querySelector(
			'[data-testid="merge-view"], .cm-mergeView, .cm-merge-view'
		);
		expect(mergeView).not.toBeNull();
	});

	it('renders normal editor when pendingDiff is undefined', async () => {
		const { container } = render(CodeRenderer, {
			props: { filename: 'foo.py', content: 'print("hello")\n', editable: true }
		});
		for (let i = 0; i < 20; i++) {
			if (container.querySelector('.cm-gutters')) break;
			await new Promise((r) => setTimeout(r, 25));
		}
		expect(container.querySelector('[data-testid="merge-view"], .cm-mergeView')).toBeNull();
		expect(container.querySelector('.cm-gutters')).not.toBeNull();
	});
});
