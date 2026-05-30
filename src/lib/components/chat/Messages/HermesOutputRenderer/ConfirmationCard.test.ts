// Tests for ConfirmationCard.svelte.
//
// Two suites:
//   1. The pure cron-approval option-filtering predicate (no DOM).
//   2. Component-level tests of the 404 "stuck confirmation" recovery
//      behavior introduced by Task 2.1 of the OSS post-launch reliability
//      plan — when POST /openai/chat/confirm returns 404 we now render a
//      Retry button + "interrupted" message instead of silently flipping
//      localStatus to 'cancelled'.

import { describe, expect, test, vi, beforeEach, afterEach } from 'vitest';
import { render, fireEvent, screen, waitFor } from '@testing-library/svelte';
import type { ConfirmationItem } from './types';
import ConfirmationCard from './ConfirmationCard.svelte';

// ── Helper that mirrors the component's $: visibleOptions logic ───────────────

function visibleOptions(item: Pick<ConfirmationItem, 'options' | 'metadata'>): string[] {
	return item.metadata?.schedule_display
		? item.options.filter((opt) => opt !== 'approve_session')
		: item.options;
}

// ── Fixtures ──────────────────────────────────────────────────────────────────

const baseItem: Pick<ConfirmationItem, 'options' | 'metadata'> = {
	options: ['approve', 'approve_session', 'deny'],
	metadata: {}
};

function makeConfirmationItem(overrides: Partial<ConfirmationItem> = {}): ConfirmationItem {
	return {
		type: 'confirmation',
		id: 'conf-1',
		confirmation_id: 'cf-abc',
		run_id: 'run-xyz',
		action_type: 'tool',
		description: 'Run the dangerous tool?',
		options: ['approve', 'deny'],
		metadata: {},
		status: 'pending',
		chosen: null,
		...overrides
	};
}

// ── Pure predicate tests ──────────────────────────────────────────────────────

describe('ConfirmationCard cron approval filter', () => {
	test('non-cron approval: renders all 3 options', () => {
		const result = visibleOptions(baseItem);
		expect(result).toEqual(['approve', 'approve_session', 'deny']);
	});

	test('cron approval: filters out approve_session', () => {
		const cronItem: Pick<ConfirmationItem, 'options' | 'metadata'> = {
			...baseItem,
			metadata: { schedule_display: '0 12 * * *' }
		};
		const result = visibleOptions(cronItem);
		expect(result).toEqual(['approve', 'deny']);
		expect(result).not.toContain('approve_session');
	});

	test('cron approval without approve_session in options: idempotent', () => {
		const cronItem: Pick<ConfirmationItem, 'options' | 'metadata'> = {
			options: ['approve', 'deny'],
			metadata: { schedule_display: '0 12 * * *' }
		};
		const result = visibleOptions(cronItem);
		expect(result).toEqual(['approve', 'deny']);
	});

	test('non-cron approval with empty metadata: all options preserved', () => {
		const result = visibleOptions({ ...baseItem, metadata: {} });
		expect(result).toContain('approve_session');
	});

	test('non-cron approval with null-ish metadata values: all options preserved', () => {
		const result = visibleOptions({ ...baseItem, metadata: { schedule_display: null } });
		// null is falsy — should NOT filter
		expect(result).toContain('approve_session');
	});
});

	// ── 404 / Retry behavior (Task 2.1) ───────────────────────────────────────────
	describe('ConfirmationCard confirm submission', () => {
		const originalFetch = global.fetch;

		beforeEach(() => {
			Object.defineProperty(window, 'localStorage', {
				value: {
					getItem: () => 'test-token',
					setItem: () => {},
					removeItem: () => {},
					token: 'test-token'
				},
				configurable: true
			});
		});

		afterEach(() => {
			global.fetch = originalFetch;
			vi.restoreAllMocks();
		});

		test('omits confirmation_id key for empty confirmation id', async () => {
			global.fetch = vi.fn().mockResolvedValue(new Response(null, { status: 200 }));
			const { default: Harness } = await import('./__test__/ConfirmationCardHarness.svelte');
			const onConfirmed = vi.fn();

			render(Harness, {
				props: {
					item: makeConfirmationItem({ confirmation_id: '' }),
					messageId: 'msg-1',
					onConfirmed
				}
			});

			await fireEvent.click(screen.getByRole('button', { name: /^approve$/i }));

			await waitFor(() => expect(global.fetch).toHaveBeenCalled());
			const body = JSON.parse(String((global.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].body));
			expect(body).toEqual({ run_id: 'run-xyz', choice: 'approve' });
			expect(body).not.toHaveProperty('confirmation_id');
			expect(onConfirmed).toHaveBeenCalledWith(
				expect.objectContaining({ confirmation_id: '', choice: 'approve' })
			);
		});

		test('includes confirmation_id for action confirmations', async () => {
			global.fetch = vi.fn().mockResolvedValue(new Response(null, { status: 200 }));

			render(ConfirmationCard, { props: { item: makeConfirmationItem(), messageId: 'msg-1' } });
			await fireEvent.click(screen.getByRole('button', { name: /^approve$/i }));

			await waitFor(() => expect(global.fetch).toHaveBeenCalled());
			const body = JSON.parse(String((global.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].body));
			expect(body).toMatchObject({
				run_id: 'run-xyz',
				choice: 'approve',
				confirmation_id: 'cf-abc'
			});
		});
	});

	describe('ConfirmationCard exec approval display', () => {
		test('renders metadata command and cwd for exec approvals', () => {
			render(ConfirmationCard, {
				props: {
					item: makeConfirmationItem({
						action_type: 'exec_approval',
						description: 'Command requires approval',
						metadata: { command: 'rm -rf /tmp/example', cwd: '/home/user/project' }
					}),
					messageId: 'msg-1'
				}
			});

			expect(screen.getByText('rm -rf /tmp/example')).toBeInTheDocument();
			expect(screen.getByText(/cwd: \/home\/user\/project/)).toBeInTheDocument();
		});

		test('renders metadata risk and reason for exec approvals', () => {
			render(ConfirmationCard, {
				props: {
					item: makeConfirmationItem({
						action_type: 'exec_approval',
						description: 'Command requires approval',
						metadata: {
							command: 'sudo reboot',
							risk_level: 'high',
							reason: 'restarts the machine'
						}
					}),
					messageId: 'msg-1'
				}
			});

			expect(screen.getByText('sudo reboot')).toBeInTheDocument();
			expect(screen.getByText(/Risk: high/)).toBeInTheDocument();
			expect(screen.getByText(/Reason: restarts the machine/)).toBeInTheDocument();
		});

		test('falls back to plain description when exec approval has no command metadata', () => {
			render(ConfirmationCard, {
				props: {
					item: makeConfirmationItem({
						action_type: 'exec_approval',
						description: 'Approve this action?',
						metadata: {}
					}),
					messageId: 'msg-1'
				}
			});

			expect(screen.getByText('Approve this action?')).toBeInTheDocument();
			expect(screen.getByRole('button', { name: /^approve$/i })).toBeInTheDocument();
		});

		test('parses only the known plugin fallback format', () => {
			render(ConfirmationCard, {
				props: {
					item: makeConfirmationItem({
						action_type: 'exec_approval',
						description: 'Command requires approval:\nnpm install\n\nReason: installs dependencies',
						metadata: {}
					}),
					messageId: 'msg-1'
				}
			});

			expect(screen.getByText('npm install')).toBeInTheDocument();
			expect(screen.getByText(/Reason: installs dependencies/)).toBeInTheDocument();
		});

		test('does not broadly parse arbitrary multiline descriptions', () => {
			const description = 'Please approve:\nnpm install\nReason: maybe needed';
			render(ConfirmationCard, {
				props: {
					item: makeConfirmationItem({
						action_type: 'exec_approval',
						description,
						metadata: {}
					}),
					messageId: 'msg-1'
				}
			});

			expect(screen.getByText((_, node) => node?.textContent === description)).toBeInTheDocument();
		});
	});

	// ── 404 / Retry behavior (Task 2.1) ───────────────────────────────────────────

describe('ConfirmationCard 404 handling', () => {
	const originalFetch = global.fetch;

	beforeEach(() => {
		// localStorage.token is read by ConfirmationCard for the auth header
		Object.defineProperty(window, 'localStorage', {
			value: {
				getItem: () => 'test-token',
				setItem: () => {},
				removeItem: () => {},
				token: 'test-token'
			},
			configurable: true
		});
	});

	afterEach(() => {
		global.fetch = originalFetch;
		vi.restoreAllMocks();
	});

	test('renders Retry button when /confirm returns 404', async () => {
		global.fetch = vi.fn().mockResolvedValue(new Response(null, { status: 404 }));

		const item = makeConfirmationItem();
		render(ConfirmationCard, { props: { item, messageId: 'msg-1' } });

		const approveBtn = screen.getByRole('button', { name: /^approve$/i });
		await fireEvent.click(approveBtn);

		await waitFor(() => {
			expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
		});
		expect(screen.getByText(/interrupted/i)).toBeInTheDocument();
		// The legacy "no longer active" cancellation copy must be gone.
		expect(screen.queryByText(/no longer active/i)).not.toBeInTheDocument();
	});

	test('dispatches retry event when Retry is clicked', async () => {
		global.fetch = vi.fn().mockResolvedValue(new Response(null, { status: 404 }));

		const { default: Harness } = await import('./__test__/ConfirmationCardHarness.svelte');
		const item = makeConfirmationItem();
		const onRetry = vi.fn();
		render(Harness, { props: { item, messageId: 'msg-1', onRetry } });

		const approveBtn = screen.getByRole('button', { name: /^approve$/i });
		await fireEvent.click(approveBtn);

		await waitFor(() => {
			expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
		});

		const retryBtn = screen.getByRole('button', { name: /retry/i });
		await fireEvent.click(retryBtn);

		expect(onRetry).toHaveBeenCalled();
		expect(onRetry.mock.calls[0][0]).toMatchObject({
			confirmation_id: 'cf-abc',
			run_id: 'run-xyz'
		});
	});

	test('confirmed event includes unique output item id for no-id approvals', async () => {
		global.fetch = vi.fn().mockResolvedValue(new Response(null, { status: 200 }));

		const { default: Harness } = await import('./__test__/ConfirmationCardHarness.svelte');
		const item = makeConfirmationItem({ id: 'conf-no-id-1', confirmation_id: '' });
		const onConfirmed = vi.fn();
		render(Harness, { props: { item, messageId: 'msg-1', onConfirmed } });

		const approveBtn = screen.getByRole('button', { name: /^approve$/i });
		await fireEvent.click(approveBtn);

		await waitFor(() => {
			expect(onConfirmed).toHaveBeenCalled();
		});
		expect(onConfirmed.mock.calls[0][0]).toMatchObject({
			item_id: 'conf-no-id-1',
			confirmation_id: '',
			choice: 'approve'
		});
	});

	test('non-404 errors still surface inline (not interrupted state)', async () => {
		global.fetch = vi.fn().mockResolvedValue(
			new Response(JSON.stringify({ detail: 'Server exploded' }), {
				status: 500,
				headers: { 'Content-Type': 'application/json' }
			})
		);

		const item = makeConfirmationItem();
		render(ConfirmationCard, { props: { item, messageId: 'msg-1' } });

		const approveBtn = screen.getByRole('button', { name: /^approve$/i });
		await fireEvent.click(approveBtn);

		await waitFor(() => {
			expect(screen.getByText(/Server exploded/i)).toBeInTheDocument();
		});
		expect(screen.queryByRole('button', { name: /retry/i })).not.toBeInTheDocument();
		expect(screen.queryByText(/interrupted/i)).not.toBeInTheDocument();
	});
});
