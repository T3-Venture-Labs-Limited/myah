import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
import { sentryVitePlugin } from '@sentry/vite-plugin';
import { svelteTesting } from '@testing-library/svelte/vite';

const BACKEND_PORT = process.env.BACKEND_PORT || '8082';
const BACKEND_BASE_URL = `http://localhost:${BACKEND_PORT}`;

export default defineConfig({
	plugins: [
		// sentryVitePlugin MUST come before sveltekit() so source maps are
		// uploaded before the plugin processes them.
		// Only active when SENTRY_AUTH_TOKEN is present (i.e. CI / prod builds).
		...(process.env.SENTRY_AUTH_TOKEN
			? [
					sentryVitePlugin({
						org: process.env.SENTRY_ORG,
						project: process.env.SENTRY_PROJECT,
						authToken: process.env.SENTRY_AUTH_TOKEN,
						telemetry: false
					})
				]
			: []),
		sveltekit(),
		// Required for Svelte 5 component mounts in jsdom (sets resolve.conditions: ['browser']).
		svelteTesting()
	],
	server: {
		host: true, // bind to 0.0.0.0 — accessible over Tailscale
		port: 5173,
		fs: {
			// Allow serving files from symlinked node_modules in git worktrees,
			// which resolve to the main workspace path outside the worktree root.
			allow: ['..', '/Users/admin/Repos/myah/platform']
		},
		watch: {
			// Don't watch the Python venv — pip installs would trigger Vite reloads
			// Don't watch emoji assets — thousands of files exhaust inotify limits
			ignored: ['**/.venv/**', '**/static/assets/emojis/**']
		},
		proxy: {
			// Forward all API and WebSocket traffic to the FastAPI backend
			'/api': { target: BACKEND_BASE_URL, changeOrigin: true, ws: true },
			// Socket.IO lives at /ws — proxy both HTTP polling and WebSocket upgrades
			'/ws': { target: BACKEND_BASE_URL, changeOrigin: true, ws: true },
			'/openai': { target: BACKEND_BASE_URL, changeOrigin: true },
			'/oauth': { target: BACKEND_BASE_URL, changeOrigin: true },
			'/static': { target: BACKEND_BASE_URL, changeOrigin: true }
		}
	},
	define: {
		APP_VERSION: JSON.stringify(process.env.npm_package_version),
		APP_BUILD_HASH: JSON.stringify(process.env.APP_BUILD_HASH || 'dev-build')
	},
	build: {
		sourcemap: true
	},
	worker: {
		format: 'es'
	},
	esbuild: {
		pure: process.env.ENV === 'dev' ? [] : ['console.log', 'console.debug', 'console.error']
	},
	test: {
		environment: 'jsdom',
		globals: true,
		setupFiles: ['./src/test-setup.ts'],
		include: ['src/**/*.test.ts', 'src/**/*.test.svelte.ts']
	}
});
