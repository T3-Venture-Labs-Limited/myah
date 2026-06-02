import { describe, expect, it } from 'vitest';
import sidebarSource from './Sidebar.svelte?raw';

describe('Sidebar hosted nav extension point', () => {
	it('renders the hosted-only nav slot from the shared sidebar', () => {
		expect(sidebarSource).toContain("import SidebarHostedNav from './SidebarHostedNav.svelte';");
		expect(sidebarSource).toContain('<SidebarHostedNav variant="collapsed" />');
		expect(sidebarSource).toContain('<SidebarHostedNav variant="expanded" />');
	});
});
