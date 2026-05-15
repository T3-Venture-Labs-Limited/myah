import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/svelte';
import { get } from 'svelte/store';
import { tick } from 'svelte';
import ArtifactPane from './ArtifactPane.svelte';
import {
	artifactOpenFiles,
	artifactActiveTabIdx,
	artifactPaneOpen,
	artifactSelection
} from '$lib/stores';

// ArtifactExplorer fetches getChatFiles on mount; mock to keep tests fast and offline.
vi.mock('$lib/apis/chats', () => ({
	getChatFiles: vi.fn(async () => [])
}));

// ArtifactViewer pulls in lots of dependencies (renderers, panzoom, codemirror, etc.).
// For ArtifactPane unit tests we only care about the state-machine wiring, so stub
// the viewer to a tiny placeholder that just renders the filename for assertions.
vi.mock('./ArtifactViewer.svelte', async () => {
	const StubViewer = (await import('./__test__/ArtifactViewerStub.svelte')).default;
	return { default: StubViewer };
});

describe('ArtifactPane', () => {
	it('renders nothing when artifactPaneOpen=false', () => {
		artifactOpenFiles.set([]);
		artifactActiveTabIdx.set(-1);
		artifactPaneOpen.set(false);
		const { container } = render(ArtifactPane, { props: { chatId: 'c', token: 't' } });
		expect(container.querySelector('[data-testid="artifact-pane"]')).toBeNull();
	});

	it('shows explorer empty state when activeIdx=-1 and chat has no files', async () => {
		artifactOpenFiles.set([]);
		artifactActiveTabIdx.set(-1);
		artifactPaneOpen.set(true);
		render(ArtifactPane, { props: { chatId: 'c', token: 't' } });
		expect(await screen.findByText(/no files yet/i)).toBeInTheDocument();
	});

	it('shows tabs + viewer when activeIdx >= 0', async () => {
		artifactOpenFiles.set([
			{ file_key: 'path:/tmp/a.py', filename: 'a.py', path: '/tmp/a.py', source: 'agent-tool' }
		]);
		artifactActiveTabIdx.set(0);
		artifactPaneOpen.set(true);
		render(ArtifactPane, { props: { chatId: 'c', token: 't' } });
		// Both the tab strip and the stub viewer render the filename — use
		// findAllByText to assert both presences, then check the viewer testid.
		const matches = await screen.findAllByText('a.py');
		expect(matches.length).toBeGreaterThanOrEqual(2);
		expect(await screen.findByTestId('artifact-viewer-stub')).toBeInTheDocument();
	});

	it('closing a tab pops it from openFiles and shifts activeIdx', async () => {
		artifactOpenFiles.set([
			{ file_key: 'path:/tmp/a.py', filename: 'a.py', path: '/tmp/a.py', source: 'agent-tool' },
			{ file_key: 'path:/tmp/b.py', filename: 'b.py', path: '/tmp/b.py', source: 'agent-tool' }
		]);
		artifactActiveTabIdx.set(1);
		artifactPaneOpen.set(true);
		render(ArtifactPane, { props: { chatId: 'c', token: 't' } });
		await fireEvent.click(screen.getByLabelText(/close b.py/i));
		expect(get(artifactOpenFiles)).toHaveLength(1);
		expect(get(artifactActiveTabIdx)).toBe(0);
	});

	it('flushes open tabs + selection when chatId changes', async () => {
		// Mount with chat A and an open tab pointing at A's file.
		artifactOpenFiles.set([
			{
				file_key: 'path:/tmp/chat-a.py',
				filename: 'chat-a.py',
				path: '/tmp/chat-a.py',
				source: 'agent-tool'
			}
		]);
		artifactActiveTabIdx.set(0);
		artifactPaneOpen.set(true);
		artifactSelection.set({
			kind: 'code-lines',
			anchor: { startLine: 1, endLine: 2, language: 'py' },
			preview: 'x',
			summary: 'chat-a.py · L1-L2'
		});

		// Svelte 5 deprecates component.$set; use a harness component whose own
		// reactive prop drives ArtifactPane's chatId, so we just rebind the
		// harness prop and let Svelte propagate.
		const { default: Harness } = await import('./__test__/ArtifactPaneHarness.svelte');
		const { rerender } = render(Harness, { props: { chatId: 'chat-a', token: 't' } });
		// First mount must NOT clobber the tab list — that's the user's
		// just-opened tab, not a stale leak from another chat.
		expect(get(artifactOpenFiles)).toHaveLength(1);

		// Simulate the user navigating to a different chat; rerender with the
		// new chatId. All per-chat state should reset so chat B doesn't see
		// chat A's tabs.
		await rerender({ chatId: 'chat-b', token: 't' });
		await tick();
		await waitFor(() => {
			expect(get(artifactOpenFiles)).toHaveLength(0);
			expect(get(artifactActiveTabIdx)).toBe(-1);
			expect(get(artifactSelection)).toBeNull();
		});
	});
});
