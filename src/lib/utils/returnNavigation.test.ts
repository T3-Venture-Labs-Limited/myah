import { describe, it, expect, vi } from 'vitest';

import { navigateToReturnUrl, resolveReturnNavigation } from './returnNavigation';

describe('return navigation', () => {
	it('routes same-origin return URLs through SvelteKit goto', () => {
		const goto = vi.fn();
		const assign = vi.fn();

		navigateToReturnUrl(
			'http://localhost/agent/skills?installed=1#done',
			goto,
			assign,
			'http://localhost'
		);

		expect(goto).toHaveBeenCalledWith('/agent/skills?installed=1#done');
		expect(assign).not.toHaveBeenCalled();
	});

	it('routes marketplace return URLs back to the local skills page', () => {
		const goto = vi.fn();
		const assign = vi.fn();

		navigateToReturnUrl('https://myah.dev/marketplace', goto, assign, 'http://localhost');

		expect(goto).toHaveBeenCalledWith('/agent/skills');
		expect(assign).not.toHaveBeenCalled();
	});

	it('falls back to home for non-marketplace external return URLs', () => {
		const goto = vi.fn();
		const assign = vi.fn();

		navigateToReturnUrl('https://example.com/done', goto, assign, 'http://localhost');

		expect(goto).toHaveBeenCalledWith('/');
		expect(assign).not.toHaveBeenCalled();
	});

	it('falls back to home for malformed return URLs', () => {
		expect(resolveReturnNavigation('http://[bad', 'http://localhost')).toEqual({
			kind: 'internal',
			url: '/'
		});
	});
});
