import { defineWorkspace } from 'vitest/config';
import { sveltekit } from '@sveltejs/kit/vite';

export default defineWorkspace([
	// ── Component tests (default) ─────────────────────────────────
	// jsdom + svelteTesting() → browser resolve condition → Svelte 5
	// client build, mount() works, @testing-library/svelte's render()
	// produces a real DOM. Inherits everything from vite.config.ts.
	{
		extends: './vite.config.ts',
		test: {
			name: 'jsdom',
			// The vite.config.ts test block already declares jsdom + globals
			// + setupFiles. The include glob here narrows the project to
			// everything EXCEPT the svelte/server suite.
			include: ['src/**/*.test.ts', 'src/**/*.test.svelte.ts'],
			exclude: ['src/lib/components/generative-ui/__tests__/**', 'node_modules/**']
		}
	},

	// ── svelte/server tests ───────────────────────────────────────
	// No jsdom, no svelteTesting(). Svelte resolves to its server build
	// (lenient createEventDispatcher, no client lifecycle). sveltekit()
	// plugin is still required so $lib/$app aliases resolve. The `define`
	// block mirrors vite.config.ts so APP_VERSION/APP_BUILD_HASH are
	// substituted during the import cascade through $lib/constants.ts.
	{
		extends: false,
		plugins: [sveltekit()],
		define: {
			APP_VERSION: JSON.stringify(process.env.npm_package_version),
			APP_BUILD_HASH: JSON.stringify(process.env.APP_BUILD_HASH || 'dev-build')
		},
		test: {
			name: 'node',
			environment: 'node',
			globals: true,
			include: ['src/lib/components/generative-ui/__tests__/**/*.test.ts']
		}
	}
]);
