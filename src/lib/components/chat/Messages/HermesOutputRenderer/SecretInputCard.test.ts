import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { toast } from 'svelte-sonner';
import SecretInputCard from './SecretInputCard.svelte';
import type { SecretInputItem } from './types';

vi.mock('svelte-sonner', () => ({
	toast: {
		info: vi.fn(),
		error: vi.fn()
	}
}));

function makeSecretItem(overrides: Partial<SecretInputItem> = {}): SecretInputItem {
	return {
		type: 'secret_input',
		id: 'secret-card-1',
		var_name: 'OPENROUTER_API_KEY',
		prompt: 'Enter OPENROUTER_API_KEY',
		help: '',
		skill_name: '',
		run_id: 'stream-secret',
		status: 'pending',
		...overrides
	};
}

describe('SecretInputCard', () => {
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

	test('submits secret value and emits stored event', async () => {
		global.fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
		const onStored = vi.fn();
		const { default: Harness } = await import('./__test__/SecretInputCardHarness.svelte');

		render(Harness, { props: { item: makeSecretItem(), onStored } });
		await fireEvent.input(screen.getByLabelText('OPENROUTER_API_KEY'), {
			target: { value: 'sk-redacted' }
		});
		await fireEvent.click(screen.getByRole('button', { name: 'Save & Continue' }));

		await waitFor(() => expect(global.fetch).toHaveBeenCalled());
		expect(JSON.parse(String((global.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].body))).toEqual({
			run_id: 'stream-secret',
			var_name: 'OPENROUTER_API_KEY',
			value: 'sk-redacted'
		});
		expect(onStored).toHaveBeenCalledWith({ var_name: 'OPENROUTER_API_KEY' });
	});

	test('supports cancelling a pending secret request', async () => {
		global.fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
		const { default: Harness } = await import('./__test__/SecretInputCardHarness.svelte');

		render(Harness, { props: { item: makeSecretItem() } });
		await fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

		await waitFor(() => expect(global.fetch).toHaveBeenCalled());
		expect(JSON.parse(String((global.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].body))).toEqual({
			run_id: 'stream-secret',
			var_name: 'OPENROUTER_API_KEY',
			cancel: true
		});
		expect(toast.info).toHaveBeenCalledWith('Secret entry cancelled');
	});

	test('renders cancelled state without input controls', () => {
		render(SecretInputCard, { props: { item: makeSecretItem({ status: 'cancelled' }) } });

		expect(screen.getByText('Secret entry was cancelled.')).toBeInTheDocument();
		expect(screen.queryByLabelText('OPENROUTER_API_KEY')).not.toBeInTheDocument();
	});
});
