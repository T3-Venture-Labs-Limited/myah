import { describe, it, expect, beforeAll, beforeEach } from 'vitest';
import { render } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { EditorView } from '@codemirror/view';
import CodeRenderer from './CodeRenderer.svelte';
import { artifactSelection } from '$lib/stores';
import type { ToolbarItem, SelectionPayload } from '$lib/types/artifact';

beforeAll(() => {
	// jsdom polyfills (mirrors the pattern in DocxRenderer.test.ts).
	if (!Blob.prototype.text) {
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		(Blob.prototype as any).text = function () {
			return new Promise((resolve) => {
				const reader = new FileReader();
				reader.onload = () => resolve(reader.result as string);
				reader.readAsText(this as Blob);
			});
		};
	}
});

describe('CodeRenderer', () => {
	const baseProps = {
		filename: 'extract.py',
		content: 'print("hello")\nprint("world")\n',
		editable: true
	};

	it('renders the editor + status bar', async () => {
		const { container } = render(CodeRenderer, { props: baseProps });
		// CodeMirror mounts asynchronously; poll until both the status bar AND
		// the gutter are present (gutter mounts a tick after the status bar).
		for (let i = 0; i < 40; i++) {
			if (
				container.querySelector('[data-testid="code-status-bar"]') &&
				container.querySelector('.cm-gutters')
			)
				break;
			await new Promise((r) => setTimeout(r, 25));
		}
		expect(container.querySelector('[data-testid="code-status-bar"]')).toBeInTheDocument();
		expect(container.querySelector('.cm-gutters')).toBeInTheDocument();
	});

	it('status bar shows language label and line count', async () => {
		const { container } = render(CodeRenderer, { props: baseProps });
		for (let i = 0; i < 20; i++) {
			const bar = container.querySelector('[data-testid="code-status-bar"]');
			if (bar?.textContent?.includes('Python')) break;
			await new Promise((r) => setTimeout(r, 25));
		}
		const bar = container.querySelector('[data-testid="code-status-bar"]');
		expect(bar?.textContent).toContain('Python');
		expect(bar?.textContent).toContain('2 lines');
	});

	it('emits toolbar event with format item on mount', async () => {
		const { default: Harness } = await import('./__test__/CodeRendererHarness.svelte');
		const items: ToolbarItem[] = [];
		render(Harness, {
			props: {
				codeProps: baseProps,
				onToolbar: (e: ToolbarItem[]) => {
					items.length = 0; // toolbar fires on every state change; capture the latest set
					items.push(...e);
				}
			}
		});
		// Wait for the initial dispatch.
		for (let i = 0; i < 20; i++) {
			if (items.find((x) => x.id === 'format')) break;
			await new Promise((r) => setTimeout(r, 25));
		}
		expect(items.find((i) => i.id === 'format')?.placement).toBe('top');
	});

	it('does NOT emit Discard toolbar item until dirty', async () => {
		const { default: Harness } = await import('./__test__/CodeRendererHarness.svelte');
		const items: ToolbarItem[] = [];
		render(Harness, {
			props: {
				codeProps: baseProps,
				onToolbar: (e: ToolbarItem[]) => {
					items.length = 0;
					items.push(...e);
				}
			}
		});
		for (let i = 0; i < 20; i++) {
			if (items.length > 0) break;
			await new Promise((r) => setTimeout(r, 25));
		}
		// Format yes, Discard no (until edits).
		expect(items.find((i) => i.id === 'format')).toBeDefined();
		expect(items.find((i) => i.id === 'discard')).toBeUndefined();
	});

	it('non-editable mode disables editor input', async () => {
		const { container } = render(CodeRenderer, {
			props: { ...baseProps, editable: false }
		});
		for (let i = 0; i < 20; i++) {
			if (container.querySelector('.cm-editor')) break;
			await new Promise((r) => setTimeout(r, 25));
		}
		const cm = container.querySelector('.cm-editor');
		// CodeMirror v6 read-only mode adds the .cm-readonly class on the wrapper, but
		// the visible signal is contenteditable=false on the .cm-content.
		const content = cm?.querySelector('.cm-content');
		expect(content?.getAttribute('contenteditable')).toBe('false');
	});

	describe('selection → artifactSelection store', () => {
		beforeEach(() => artifactSelection.set(null));

		// Locate the CodeMirror EditorView attached to the rendered <div>.
		// CodeMirror 6 doesn't expose `cmView` on the DOM node — use
		// EditorView.findFromDOM, which walks up looking for the view's root.
		async function waitForView(container: HTMLElement): Promise<EditorView> {
			for (let i = 0; i < 40; i++) {
				const cm = container.querySelector('.cm-editor');
				if (cm) {
					const view = EditorView.findFromDOM(cm as HTMLElement);
					if (view) return view;
				}
				await new Promise((r) => setTimeout(r, 25));
			}
			throw new Error('CodeMirror EditorView did not mount');
		}

		it('writes a code-lines payload to artifactSelection on selection', async () => {
			const events: (SelectionPayload | null)[] = [];
			const { default: Harness } = await import('./__test__/CodeRendererHarness.svelte');
			const { container } = render(Harness, {
				props: {
					codeProps: baseProps,
					onSelect: (e: SelectionPayload | null) => events.push(e)
				}
			});
			const view = await waitForView(container);
			view.dispatch({ selection: { anchor: 0, head: 5 } });
			await new Promise((r) => setTimeout(r, 25));

			const stored = get(artifactSelection);
			expect(stored).not.toBeNull();
			expect(stored?.kind).toBe('code-lines');
			// Belt-and-suspenders: dispatch fires too, so the harness sees it.
			expect(events.find((e) => e?.kind === 'code-lines')).toBeTruthy();
		});

		it('clears artifactSelection when the selection collapses to a cursor', async () => {
			const { default: Harness } = await import('./__test__/CodeRendererHarness.svelte');
			const { container } = render(Harness, { props: { codeProps: baseProps } });
			const view = await waitForView(container);
			view.dispatch({ selection: { anchor: 0, head: 5 } });
			await new Promise((r) => setTimeout(r, 25));
			expect(get(artifactSelection)).not.toBeNull();
			view.dispatch({ selection: { anchor: 5, head: 5 } });
			await new Promise((r) => setTimeout(r, 25));
			expect(get(artifactSelection)).toBeNull();
		});
	});
});
