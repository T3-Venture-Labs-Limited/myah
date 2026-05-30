import { describe, expect, it } from 'vitest';
import type { ConfirmationItem } from './types';
import { confirmationKey } from './confirmationKey';

function makeConfirmation(overrides: Partial<ConfirmationItem> = {}): ConfirmationItem {
	return {
		type: 'confirmation',
		id: 'conf-a',
		confirmation_id: '',
		run_id: 'run-1',
		action_type: 'exec_approval',
		description: 'Approve command?',
		options: ['approve', 'deny'],
		metadata: {},
		status: 'pending',
		chosen: null,
		...overrides
	};
}

describe('confirmationKey', () => {
	it('uses item identity for no-id confirmations', () => {
		const a = makeConfirmation({ id: 'conf-a', run_id: 'run-1', confirmation_id: '' });
		const b = makeConfirmation({ id: 'conf-b', run_id: 'run-1', confirmation_id: '' });

		expect(confirmationKey(a)).toBe('run-1:conf-a');
		expect(confirmationKey(b)).toBe('run-1:conf-b');
		expect(confirmationKey(a)).not.toBe(confirmationKey(b));
	});

	it('uses real confirmation id when present', () => {
		expect(confirmationKey(makeConfirmation({ confirmation_id: 'cf-1' }))).toBe('cf-1');
	});
});
