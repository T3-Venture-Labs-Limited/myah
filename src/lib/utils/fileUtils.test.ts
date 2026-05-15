// Tests for the client-side file size validation logic used in MessageInput
import { describe, it, expect } from 'vitest';

const MAX_PER_FILE = 20 * 1024 * 1024; // 20 MB
const MAX_AGGREGATE = 80 * 1024 * 1024; // 80 MB

function preflightCheck(
	files: Array<{ name: string; size: number }>,
	currentAggregate: number
): { rejected: string[]; accepted: Array<{ name: string; size: number }> } {
	const rejected: string[] = [];
	const accepted: Array<{ name: string; size: number }> = [];
	let tentativeTotal = currentAggregate;
	for (const file of files) {
		if (file.size > MAX_PER_FILE) {
			rejected.push(`${file.name} is larger than 20 MB`);
			continue;
		}
		if (tentativeTotal + file.size > MAX_AGGREGATE) {
			rejected.push(`${file.name} would exceed the 80 MB total limit`);
			continue;
		}
		accepted.push(file);
		tentativeTotal += file.size;
	}
	return { rejected, accepted };
}

describe('preflightCheck', () => {
	it('accepts files within limits', () => {
		const { accepted, rejected } = preflightCheck(
			[{ name: 'a.pdf', size: 5 * 1024 * 1024 }],
			0
		);
		expect(accepted).toHaveLength(1);
		expect(rejected).toHaveLength(0);
	});

	it('rejects single file over 20 MB', () => {
		const { accepted, rejected } = preflightCheck(
			[{ name: 'big.bin', size: 21 * 1024 * 1024 }],
			0
		);
		expect(accepted).toHaveLength(0);
		expect(rejected).toHaveLength(1);
		expect(rejected[0]).toContain('20 MB');
	});

	it('rejects file that would exceed 80 MB aggregate', () => {
		const { accepted, rejected } = preflightCheck(
			[{ name: 'c.bin', size: 15 * 1024 * 1024 }],
			70 * 1024 * 1024
		);
		expect(accepted).toHaveLength(0);
		expect(rejected).toHaveLength(1);
		expect(rejected[0]).toContain('80 MB');
	});

	it('accepts multiple files within aggregate limit', () => {
		const { accepted, rejected } = preflightCheck(
			[
				{ name: 'a.pdf', size: 10 * 1024 * 1024 },
				{ name: 'b.pdf', size: 10 * 1024 * 1024 }
			],
			0
		);
		expect(accepted).toHaveLength(2);
		expect(rejected).toHaveLength(0);
	});

	it('accepts some and rejects others in mixed batch', () => {
		const { accepted, rejected } = preflightCheck(
			[
				{ name: 'ok.pdf', size: 5 * 1024 * 1024 },
				{ name: 'big.bin', size: 25 * 1024 * 1024 }
			],
			0
		);
		expect(accepted).toHaveLength(1);
		expect(accepted[0].name).toBe('ok.pdf');
		expect(rejected).toHaveLength(1);
		expect(rejected[0]).toContain('20 MB');
	});

	it('counts previously accepted files toward tentative total', () => {
		// Four 19 MB files: first four sum to 76 MB (< 80), the fifth (19 MB) would
		// push to 95 MB, exceeding the aggregate cap.
		const { accepted, rejected } = preflightCheck(
			[
				{ name: 'a.bin', size: 19 * 1024 * 1024 },
				{ name: 'b.bin', size: 19 * 1024 * 1024 },
				{ name: 'c.bin', size: 19 * 1024 * 1024 },
				{ name: 'd.bin', size: 19 * 1024 * 1024 },
				{ name: 'e.bin', size: 19 * 1024 * 1024 }
			],
			0
		);
		expect(accepted).toHaveLength(4);
		expect(rejected).toHaveLength(1);
		expect(rejected[0]).toContain('80 MB');
	});
});
