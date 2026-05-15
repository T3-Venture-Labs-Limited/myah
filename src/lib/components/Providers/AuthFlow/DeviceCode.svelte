<script lang="ts">
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import type { CatalogEntry } from '$lib/apis/providers';
	import { startDeviceAuth, pollDeviceAuth } from '$lib/apis/providers';
	import { refreshProviderStatus } from '$lib/stores/providers';
	// OAuthStatus is the typed mirror of Hermes' OAuth wire vocabulary
	// (``shared/contract/enums.py``). The backend already translates
	// ``approved`` -> ``complete`` before we see it, so the frontend
	// observes a slightly different vocabulary; the import anchors the
	// contract to its source so a Phase 2+ unification is mechanical.
	import type { OAuthStatus } from '$lib/types/contract';

	let {
		provider,
		onComplete,
		onCancel
	}: {
		provider: CatalogEntry;
		onComplete?: (result: { default_model?: string }) => void;
		onCancel?: () => void;
	} = $props();

	const i18n = getContext('i18n');

	type Status = 'loading' | 'waiting' | 'complete' | 'expired' | 'error';
	let status = $state<Status>('loading');
	let userCode = $state('');
	let verificationUrl = $state('');
	let errorMessage = $state('');

	// Internal tracking — not reactive in the template
	let sessionId = '';
	let pollIntervalSeconds = 5;
	let pollTimer: ReturnType<typeof setInterval> | null = null;

	async function startFlow() {
		status = 'loading';
		sessionId = '';
		userCode = '';
		verificationUrl = '';

		try {
			const token = localStorage.token;
			const session = await startDeviceAuth(token, provider.id);
			sessionId = session.session_id;
			userCode = session.user_code ?? '';
			verificationUrl = session.verification_url ?? '';
			pollIntervalSeconds = session.interval ?? 5;
			status = 'waiting';
			startPolling(token);
		} catch (err: unknown) {
			status = 'error';
			const e = err as Record<string, unknown>;
			errorMessage =
				typeof err === 'string'
					? err
					: typeof e?.detail === 'string'
						? e.detail
						: 'Failed to start OAuth flow';
		}
	}

	// Statuses the frontend recognises. Four values are passed through 1:1
	// from Hermes (``pending``, ``denied``, ``cancelled``, ``expired``,
	// ``error``); ``complete`` is the platform backend's translation of
	// Hermes' ``approved``. Anything outside this set triggers an error
	// rather than continued polling — this is the regression gate against
	// the 2026-04-20 OAuth incident, where an unrecognised status caused
	// the poller to loop indefinitely.
	type FrontendOAuthStatus = Exclude<OAuthStatus, 'approved'> | 'complete';
	const KNOWN_STATUSES: readonly FrontendOAuthStatus[] = [
		'pending',
		'complete',
		'denied',
		'cancelled',
		'expired',
		'error'
	];
	const isKnownStatus = (s: string): s is FrontendOAuthStatus =>
		(KNOWN_STATUSES as readonly string[]).includes(s);

	function startPolling(token: string) {
		stopPolling();
		pollTimer = setInterval(async () => {
			if (!sessionId) return;
			try {
				const result = await pollDeviceAuth(token, provider.id, sessionId);
				// Defence-in-depth against the 2026-04-20 OAuth incident: if the
				// backend forwards a status the frontend doesn't recognise, stop
				// polling and surface an error rather than looping silently. The
				// backend already validates against the contract OAuthStatus enum,
				// so reaching this branch indicates a real protocol drift.
				if (!isKnownStatus(result.status)) {
					stopPolling();
					status = 'error';
					errorMessage = `Unexpected authentication status: ${result.status}`;
					return;
				}
				if (result.status === 'complete') {
					stopPolling();
					status = 'complete';
					await refreshProviderStatus(token);
					onComplete?.({ default_model: result.default_model });
				} else if (result.status === 'expired') {
					stopPolling();
					status = 'expired';
				} else if (
					result.status === 'error' ||
					result.status === 'denied' ||
					result.status === 'cancelled'
				) {
					stopPolling();
					status = 'error';
					errorMessage =
						result.error_message ??
						(result.status === 'denied'
							? 'Authentication denied at provider'
							: result.status === 'cancelled'
								? 'Authentication cancelled'
								: 'Authentication error');
				}
				// 'pending' → keep polling
			} catch {
				// network error — keep polling silently
			}
		}, pollIntervalSeconds * 1000);
	}

	function stopPolling() {
		if (pollTimer !== null) {
			clearInterval(pollTimer);
			pollTimer = null;
		}
	}

	async function copyCode() {
		try {
			await navigator.clipboard.writeText(userCode);
			toast.success($i18n.t('Code copied to clipboard'));
		} catch {
			toast.error($i18n.t('Failed to copy'));
		}
	}

	$effect(() => {
		startFlow();
		return () => stopPolling();
	});
</script>

<div class="flex flex-col gap-4 p-5">
	{#if status === 'loading'}
		<div class="flex justify-center py-8">
			<div
				class="h-7 w-7 border-2 border-neutral-700 border-t-neutral-400 rounded-full animate-spin"
			></div>
		</div>
	{:else if status === 'waiting'}
		<p class="text-sm text-gray-600 dark:text-gray-400 leading-relaxed">
			{$i18n.t('Open the link below and enter the code to connect your account.')}
		</p>

		<div class="flex items-center gap-3 bg-gray-100 dark:bg-neutral-800 rounded-xl px-4 py-3">
			<span
				class="font-mono text-base font-bold tracking-widest text-gray-900 dark:text-gray-100 flex-1"
			>
				{userCode}
			</span>
			<button
				class="w-7 h-7 flex items-center justify-center rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-200 dark:hover:bg-neutral-700 transition-colors"
				onclick={copyCode}
				aria-label={$i18n.t('Copy code')}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					class="h-4 w-4"
					fill="none"
					viewBox="0 0 24 24"
					stroke="currentColor"
					stroke-width="2"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
					/>
				</svg>
			</button>
		</div>

		<a
			href={verificationUrl}
			target="_blank"
			rel="noopener noreferrer"
			class="inline-flex items-center gap-1.5 text-sm text-gray-700 dark:text-gray-300 hover:text-gray-900 dark:hover:text-white underline underline-offset-2 decoration-gray-400 dark:decoration-gray-600 transition-colors break-all"
		>
			{verificationUrl}
			<svg
				xmlns="http://www.w3.org/2000/svg"
				class="h-3 w-3 shrink-0"
				viewBox="0 0 20 20"
				fill="currentColor"
			>
				<path
					d="M11 3a1 1 0 100 2h2.586l-6.293 6.293a1 1 0 101.414 1.414L15 6.414V9a1 1 0 102 0V4a1 1 0 00-1-1h-5z"
				/>
				<path
					d="M5 5a2 2 0 00-2 2v8a2 2 0 002 2h8a2 2 0 002-2v-3a1 1 0 10-2 0v3H5V7h3a1 1 0 000-2H5z"
				/>
			</svg>
		</a>

		<div class="flex items-center gap-2">
			<span
				class="inline-flex h-1.5 w-1.5 rounded-full bg-gray-400 dark:bg-neutral-500 animate-pulse"
			></span>
			<p class="text-xs text-gray-400 dark:text-neutral-500">
				{$i18n.t('Waiting for authorisation…')}
			</p>
		</div>
	{:else if status === 'complete'}
		<div class="flex flex-col items-center gap-2 py-4">
			<svg
				xmlns="http://www.w3.org/2000/svg"
				class="h-10 w-10 text-green-500"
				fill="none"
				viewBox="0 0 24 24"
				stroke="currentColor"
			>
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
			</svg>
			<p class="font-medium">{$i18n.t('Connected!')}</p>
		</div>
	{:else if status === 'expired'}
		<div class="flex flex-col gap-3 items-center py-4">
			<p class="text-red-600 dark:text-red-400 text-sm">
				{$i18n.t('Code expired. Please try again.')}
			</p>
			<button
				class="text-sm font-medium text-gray-900 dark:text-white hover:underline underline-offset-2"
				onclick={startFlow}
			>
				{$i18n.t('Try again')}
			</button>
		</div>
	{:else if status === 'error'}
		<div class="flex flex-col gap-3 items-center py-4">
			<p class="text-red-600 dark:text-red-400 text-sm">
				{errorMessage || $i18n.t('Authentication error')}
			</p>
			<button
				class="text-sm font-medium text-gray-900 dark:text-white hover:underline underline-offset-2"
				onclick={startFlow}
			>
				{$i18n.t('Try again')}
			</button>
		</div>
	{/if}

	{#if status !== 'complete'}
		<div class="flex justify-end pt-1 border-t border-gray-100 dark:border-neutral-800">
			<button
				class="text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 px-3 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-neutral-800 transition-colors"
				onclick={() => onCancel?.()}
			>
				{$i18n.t('Cancel')}
			</button>
		</div>
	{/if}
</div>
