import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import ArtifactTabs from './ArtifactTabs.svelte';
import ArtifactTabsHarness from './__test__/ArtifactTabsHarness.svelte';

const f = (filename: string) => ({
	file_key: `path:/tmp/${filename}`,
	path: `/tmp/${filename}`,
	filename,
	source: 'agent-tool' as const
});

// Svelte 5 removed component.$on; createEventDispatcher events go to parent
// component listeners (on:event) and not to the DOM. Test cases that need
// to observe dispatched events use ArtifactTabsHarness which forwards them
// via callback props.
describe('ArtifactTabs', () => {
	it('renders one tab per open file plus the folder back button', () => {
		render(ArtifactTabs, {
			props: {
				openFiles: [f('a.py'), f('b.py')],
				activeIdx: 0
			}
		});
		expect(screen.getByText('a.py')).toBeInTheDocument();
		expect(screen.getByText('b.py')).toBeInTheDocument();
		expect(screen.getByLabelText(/back to file explorer/i)).toBeInTheDocument();
	});

	it('clicking a tab fires activate event with index', async () => {
		const events: number[] = [];
		render(ArtifactTabsHarness, {
			props: {
				openFiles: [f('a.py'), f('b.py')],
				activeIdx: 0,
				onActivate: (idx: number) => events.push(idx)
			}
		});
		await fireEvent.click(screen.getByText('b.py'));
		expect(events).toEqual([1]);
	});

	it('clicking close on a tab fires close event with index', async () => {
		const events: number[] = [];
		render(ArtifactTabsHarness, {
			props: {
				openFiles: [f('a.py')],
				activeIdx: 0,
				onClose: (idx: number) => events.push(idx)
			}
		});
		await fireEvent.click(screen.getByLabelText(/close a.py/i));
		expect(events).toEqual([0]);
	});

	it('folder button activates explorer (idx=-1)', async () => {
		const events: number[] = [];
		render(ArtifactTabsHarness, {
			props: {
				openFiles: [f('a.py')],
				activeIdx: 0,
				onActivate: (idx: number) => events.push(idx)
			}
		});
		await fireEvent.click(screen.getByLabelText(/back to file explorer/i));
		expect(events).toEqual([-1]);
	});
});
