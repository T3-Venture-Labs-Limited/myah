import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import ClarifyInputCard from './ClarifyInputCard.svelte';
import type { ClarifyInputItem } from './types';

function makeClarifyItem(overrides: Partial<ClarifyInputItem> = {}): ClarifyInputItem {
	return {
		type: 'clarify_input',
		id: 'clarify-card-1',
		clarify_id: 'clarify-123',
		run_id: 'stream-abc',
		question: 'Which environment should I deploy to?',
		choices: ['staging', 'production'],
		timeout_seconds: 300,
		status: 'pending',
		response: null,
		...overrides
	};
}

describe('ClarifyInputCard', () => {
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

	test('renders choices and posts selected answer', async () => {
		global.fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
		const onAnswered = vi.fn();
		const { default: Harness } = await import('./__test__/ClarifyInputCardHarness.svelte');

		render(Harness, { props: { item: makeClarifyItem(), onAnswered } });

		expect(screen.getByText('Which environment should I deploy to?')).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'staging' }));

		await waitFor(() => expect(global.fetch).toHaveBeenCalled());
		const [, init] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
		expect(init.method).toBe('POST');
		expect(String(init.body)).toContain('staging');
		expect(JSON.parse(String(init.body))).toEqual({
			run_id: 'stream-abc',
			clarify_id: 'clarify-123',
			response: 'staging'
		});
		expect(onAnswered).toHaveBeenCalledWith({ clarify_id: 'clarify-123', response: 'staging' });
	});

	test('supports Other free-text answer for multiple choice prompts', async () => {
		global.fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
		const onAnswered = vi.fn();
		const { default: Harness } = await import('./__test__/ClarifyInputCardHarness.svelte');

		render(Harness, { props: { item: makeClarifyItem(), onAnswered } });
		await fireEvent.click(screen.getByRole('button', { name: 'Other…' }));
		await fireEvent.input(screen.getByPlaceholderText('Type your answer...'), {
			target: { value: 'qa' }
		});
		await fireEvent.click(screen.getByRole('button', { name: 'Submit' }));

		await waitFor(() => expect(global.fetch).toHaveBeenCalled());
		expect(JSON.parse(String((global.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].body))).toMatchObject({
			response: 'qa'
		});
		expect(onAnswered).toHaveBeenCalledWith({ clarify_id: 'clarify-123', response: 'qa' });
	});

	test('renders inactive timeout state without buttons', () => {
		render(ClarifyInputCard, {
			props: {
				item: makeClarifyItem({ status: 'timeout' }),
				localStatus: 'timeout'
			}
		});

		expect(screen.getByText(/timed out/i)).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'staging' })).not.toBeInTheDocument();
	});
});
