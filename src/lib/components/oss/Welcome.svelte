<script lang="ts">
	// First-run welcome screen for OSS (Workstream C Task C.3).
	//
	// Shown once, when /api/v1/oss/probe returns first_run=true AND
	// hermes_reachable=true. After Continue, the parent layout calls
	// markFirstRunComplete() — the probe will return first_run=false on
	// subsequent loads and this screen never appears again.
	//
	// Dumb component: doesn't fetch, doesn't navigate. Parent owns both.
	import { getContext } from 'svelte';
	import { MYAH_BASE_URL } from '$lib/constants';
	import { MYAH_NAME } from '$lib/stores';
	import type { OssProbe } from '$lib/apis/oss';

	const i18n = getContext('i18n');

	export let probe: OssProbe;
	export let onContinue: () => void;
</script>

<div class="welcome-screen flex flex-col items-center justify-center min-h-screen w-full bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 px-6 py-12">
	<div class="max-w-md w-full text-center">
		<img
			src="{MYAH_BASE_URL}/static/favicon.png"
			alt="logo"
			class="w-16 h-16 mx-auto mb-8 rounded-2xl"
		/>

		<h1 class="text-3xl font-semibold mb-3">
			{$i18n.t('Welcome to {{name}}', { name: $MYAH_NAME ?? 'Myah' })}
		</h1>

		<p class="text-sm text-gray-600 dark:text-gray-400 mb-8">
			{$i18n.t(
				'A single-user web platform for your Hermes Agent. No accounts, no cloud — just you and your agent.'
			)}
		</p>

		<div
			class="rounded-2xl border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-800/40 p-4 mb-8 text-left"
		>
			<div class="flex items-start gap-3">
				<span class="text-emerald-500 text-lg leading-none mt-0.5" aria-hidden="true"
					>✓</span
				>
				<div class="text-sm">
					<div class="font-medium mb-1">{$i18n.t('Connected to your Hermes Agent')}</div>
					<code
						class="text-xs bg-white dark:bg-gray-900 px-2 py-1 rounded border border-gray-200 dark:border-gray-800 break-all"
						>{probe.hermes_url}</code
					>
					{#if probe.plugin_version}
						<div class="text-xs text-gray-500 dark:text-gray-400 mt-2">
							{$i18n.t('Myah plugin v{{version}} detected', {
								version: probe.plugin_version
							})}
						</div>
					{/if}
				</div>
			</div>

			{#if probe.providers_configured.length > 0}
				<div class="flex items-start gap-3 mt-3 pt-3 border-t border-gray-200 dark:border-gray-800">
					<span class="text-emerald-500 text-lg leading-none mt-0.5" aria-hidden="true"
						>✓</span
					>
					<div class="text-sm">
						<div class="font-medium mb-1">{$i18n.t('Provider configured')}</div>
						<div class="text-xs text-gray-500 dark:text-gray-400">
							{probe.providers_configured.join(', ')}
						</div>
					</div>
				</div>
			{/if}
		</div>

		<p class="text-sm mb-8">
			{$i18n.t('You can start chatting right away.')}
		</p>

		<button
			type="button"
			class="w-full bg-gray-900 dark:bg-white text-white dark:text-gray-900 rounded-2xl py-3 px-6 font-medium hover:bg-gray-800 dark:hover:bg-gray-100 transition"
			on:click={() => onContinue()}
		>
			{$i18n.t('Continue')}
		</button>
	</div>
</div>
