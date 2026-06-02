import { render, waitFor } from '@testing-library/svelte';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const goto = vi.hoisted(() => vi.fn());
const publicEnv = vi.hoisted(() => ({ PUBLIC_DEPLOYMENT_MODE: 'hosted' }));

vi.mock('$app/navigation', () => ({
	goto
}));

vi.mock('$env/dynamic/public', () => ({
	env: publicEnv
}));

import AgentPage from './+page.svelte';

describe('/agent page', () => {
	beforeEach(() => {
		goto.mockClear();
		publicEnv.PUBLIC_DEPLOYMENT_MODE = 'hosted';
	});

	it('redirects hosted top-level Agent route to the first visible tab: skills', async () => {
		render(AgentPage);

		await waitFor(() => {
			expect(goto).toHaveBeenCalledWith('/agent/skills', { replaceState: true });
		});
	});

	it('redirects OSS top-level Agent route to the first visible OSS tab: tools', async () => {
		publicEnv.PUBLIC_DEPLOYMENT_MODE = 'oss';
		render(AgentPage);

		await waitFor(() => {
			expect(goto).toHaveBeenCalledWith('/agent/tools', { replaceState: true });
		});
	});
});
