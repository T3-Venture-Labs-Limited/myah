import * as Sentry from '@sentry/sveltekit';
import { replayIntegration } from '@sentry/browser';
import { env } from '$env/dynamic/public';
import type { HandleClientError } from '@sveltejs/kit';
import { get } from 'svelte/store';
import { chatId, chatTitle, temporaryChatEnabled, theme, mobile } from '$lib/stores';
import { providerStatusV2 } from '$lib/stores/providers';

// APP_BUILD_HASH is injected globally by Vite (see vite.config.ts define block)
declare const APP_BUILD_HASH: string;

function resolveTheme(storeValue: string): 'light' | 'dark' {
	if (storeValue === 'system') {
		return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
	}
	return storeValue === 'dark' ? 'dark' : 'light';
}

if (env.PUBLIC_SENTRY_DSN) {
	Sentry.init({
		dsn: env.PUBLIC_SENTRY_DSN,
		release: typeof APP_BUILD_HASH !== 'undefined' ? APP_BUILD_HASH : undefined,
		environment: import.meta.env.MODE,
		sendDefaultPii: true,

		// Trace every navigation and API call so the full
		// frontend → backend → agent path is visible in one trace.
		tracesSampleRate: 1.0,

		// Propagate Sentry trace headers to the backend API so
		// distributed traces connect across service boundaries.
		tracePropagationTargets: ['localhost', /^https?:\/\/app\.myah\.dev/, /\/api\//],

		integrations: [
			// Session Replay: record all sessions that hit an error,
			// plus a sample of normal sessions for UX review.
			replayIntegration({
				maskAllText: false,
				blockAllMedia: false
			}),
			// Floating User Feedback widget for beta bug reports.
			Sentry.feedbackIntegration({
				autoInject: false,
				colorScheme: resolveTheme(get(theme)),
				showBranding: false,
				useSentryUser: {
					email: 'email',
					name: 'username'
				},
				enableScreenshot: true,
				triggerLabel: 'Report a bug',
				formTitle: 'Report a bug',
				submitButtonLabel: 'Send report',
				messagePlaceholder: 'What happened? What did you expect?',
				successMessageText: 'Thanks — your report is on the way.',
				tags: {
					source: 'widget',
					surface: 'app'
				},
				themeLight: {
					foreground: '#171717',
					background: '#ffffff',
					accentForeground: '#ffffff',
					accentBackground: '#171717',
					successColor: '#525252',
					errorColor: '#dc2626',
					boxShadow: '0px 4px 24px 0px rgba(0, 0, 0, 0.12)',
					outline: '1px auto #171717'
				},
				themeDark: {
					foreground: '#fafafa',
					background: '#141414',
					accentForeground: '#0a0a0a',
					accentBackground: '#fafafa',
					successColor: '#a3a3a3',
					errorColor: '#ef4444',
					boxShadow: '0px 4px 24px 0px rgba(0, 0, 0, 0.5)',
					outline: '1px auto #fafafa'
				}
			})
		],

		// Capture every error session; record 10% of normal sessions
		replaysOnErrorSampleRate: 1.0,
		replaysSessionSampleRate: 0.1,

		// Forward structured logs to Sentry
		enableLogs: true
	});

	// Sync Sentry feedback theme with Myah's theme toggle.
	theme.subscribe((value) => {
		const resolved = resolveTheme(value);
		const feedback = Sentry.getFeedback();
		if (feedback && 'setTheme' in feedback) {
			(feedback as { setTheme(t: 'light' | 'dark'): void }).setTheme(resolved);
		}
	});

	// Enrich every feedback submission with a snapshot of Myah state.
	// All fields are free metadata — they ride on the single event.
	Sentry.getClient()?.on('beforeSendFeedback', (feedbackEvent) => {
		try {
			feedbackEvent.contexts = {
				...feedbackEvent.contexts,
				myah_chat: {
					chat_id: get(chatId) || null,
					chat_title: get(chatTitle) || null,
					temporary: get(temporaryChatEnabled)
				},
				myah_ui: {
					route: window.location.pathname,
					theme: get(theme),
					locale: document.documentElement.lang || 'unknown',
					is_mobile: get(mobile)
				}
			};
			const _provStatuses = get(providerStatusV2) ?? [];
			const _firstValid = _provStatuses.find((p) => p.isValid);
			feedbackEvent.tags = {
				...feedbackEvent.tags,
				chat_id: get(chatId) || 'none',
				provider: _firstValid?.providerId ?? 'none',
				provider_valid: String(_firstValid !== undefined),
				surface: window.location.pathname.split('/')[1] || 'home',
				theme: get(theme) ?? 'unknown',
				is_mobile: String(get(mobile))
			};
		} catch (err) {
			// Hook must not throw — enrichment is best-effort.
			console.warn('[sentry] feedback enrichment failed:', err);
		}
	});
}

export const handleError: HandleClientError = Sentry.handleErrorWithSentry(({ error, event }) => {
	console.error('[myah] client error:', error, event?.url?.pathname ?? '');
	return {
		message: 'An unexpected error occurred'
	};
});
