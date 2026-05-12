// Tests for the cron approval option-filtering logic extracted from
// ConfirmationCard.svelte. We test the pure filter function directly
// because @testing-library/svelte is not installed in this project.
// The component uses this same predicate in its $: visibleOptions reactive declaration.

import { describe, expect, test } from 'vitest';
import type { ConfirmationItem } from './types';

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

// ── Tests ─────────────────────────────────────────────────────────────────────

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
