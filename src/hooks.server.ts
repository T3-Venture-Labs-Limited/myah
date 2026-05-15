import * as Sentry from '@sentry/sveltekit';
import { sequence } from '@sveltejs/kit/hooks';
import type { HandleServerError } from '@sveltejs/kit';

// Server-side Sentry init for dev/SSR mode.
// In production the static adapter pre-renders everything so this file is
// unused at runtime — but it still runs during `vite dev` and prerender,
// catching SSR errors before they silently disappear.
if (process.env.SENTRY_DSN_PLATFORM) {
	Sentry.init({
		dsn: process.env.SENTRY_DSN_PLATFORM,
		environment: process.env.NODE_ENV ?? 'development',
		tracesSampleRate: 1.0,
		enableLogs: true
	});
}

// sentryHandle() instruments server-side load functions and API routes,
// creating root spans that connect to the client-side trace.
export const handle = sequence(Sentry.sentryHandle());

export const handleError: HandleServerError = Sentry.handleErrorWithSentry(({ error, event }) => {
	console.error('[myah] SSR error:', error, event?.url?.pathname ?? '');
	return {
		message: 'An unexpected error occurred'
	};
});
