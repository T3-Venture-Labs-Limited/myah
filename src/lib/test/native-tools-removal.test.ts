import { describe, expect, it } from 'vitest';

describe('native frontend tools removal', () => {
	it('fails to import $lib/apis/tools', async () => {
		const moduleId = '$lib/apis/tools';
		await expect(import(moduleId)).rejects.toThrow();
	});

	it('fails to import $lib/apis/functions', async () => {
		const moduleId = '$lib/apis/functions';
		await expect(import(moduleId)).rejects.toThrow();
	});

	it('does not export tools or functions stores', async () => {
		const stores = await import('$lib/stores');

		expect(stores).not.toHaveProperty('tools');
		expect(stores).not.toHaveProperty('functions');
	});
});
