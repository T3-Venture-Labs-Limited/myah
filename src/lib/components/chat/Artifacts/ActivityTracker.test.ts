import { describe, it, expect, beforeEach } from 'vitest';
import { ActivityTracker } from './ActivityTracker';

describe('ActivityTracker', () => {
	let tracker: ActivityTracker;

	beforeEach(() => {
		tracker = new ActivityTracker();
	});

	it('write_file marks new file as created', () => {
		tracker.onToolCompleted('write_file', { path: '/tmp/foo.py' });
		expect(tracker.lastOp('path:/tmp/foo.py')).toBe('created');
	});

	it('write_file on existing file marks as edited', () => {
		tracker.onToolCompleted('write_file', { path: '/tmp/foo.py' });
		tracker.onToolCompleted('write_file', { path: '/tmp/foo.py' });
		expect(tracker.lastOp('path:/tmp/foo.py')).toBe('edited');
	});

	it('patch always marks as edited', () => {
		tracker.onToolCompleted('patch', { path: '/tmp/foo.py' });
		expect(tracker.lastOp('path:/tmp/foo.py')).toBe('edited');
	});

	it('execute_code with path-yielding result marks as produced', () => {
		tracker.onToolCompleted('execute_code', {
			output: 'Wrote /tmp/forecast.xlsx'
		});
		expect(tracker.lastOp('path:/tmp/forecast.xlsx')).toBe('produced');
	});

	it('terminal with path-yielding stdout marks as produced', () => {
		tracker.onToolCompleted('terminal', {
			stdout: 'Saved to /tmp/report.pdf'
		});
		expect(tracker.lastOp('path:/tmp/report.pdf')).toBe('produced');
	});

	it('image_generate marks as produced (and recognises media extensions)', () => {
		tracker.onToolCompleted('image_generate', { path: '/tmp/chart.png' });
		expect(tracker.lastOp('path:/tmp/chart.png')).toBe('produced');
	});

	it('isLive=true while a tool is in flight, false after completion', () => {
		tracker.onToolStarted('write_file', { path: '/tmp/foo.py' });
		expect(tracker.isLive('path:/tmp/foo.py')).toBe(true);
		tracker.onToolCompleted('write_file', { path: '/tmp/foo.py' });
		expect(tracker.isLive('path:/tmp/foo.py')).toBe(false);
	});

	it('clears all entries on chat switch', () => {
		tracker.onToolCompleted('write_file', { path: '/tmp/foo.py' });
		tracker.reset();
		expect(tracker.lastOp('path:/tmp/foo.py')).toBeUndefined();
	});

	it('ignores tool names not in the artifact-trigger frozenset', () => {
		tracker.onToolCompleted('web_search', { results: '...' });
		expect(tracker.size()).toBe(0);
	});

	it('ignores results without an extractable artifact-extension path', () => {
		tracker.onToolCompleted('execute_code', { output: 'no path here' });
		expect(tracker.size()).toBe(0);
	});
});
