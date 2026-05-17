<script lang="ts">
	// Full-screen blocking error for "hermes dashboard isn't running".
	//
	// Companion of HermesDownError.svelte (gateway-down) and
	// PluginMissingError.svelte. Rendered when probe.hermes_reachable is
	// true, probe.plugin_installed is true, and probe.dashboard_running
	// is false — i.e. the gateway is fine but the dashboard process
	// isn't bound to its port.
	//
	// Dumb component: no fetches, no navigation. Parent owns both.
	import { getContext } from 'svelte';
	import { MYAH_BASE_URL } from '$lib/constants';
	import { MYAH_NAME } from '$lib/stores';
	import type { OssProbe } from '$lib/apis/oss';

	const i18n = getContext('i18n');

	export let probe: OssProbe;
	export let onRetry: () => void;
</script>

<div
	class="dashboard-down-screen flex flex-col items-center justify-center min-h-screen w-full bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 px-6 py-12"
>
	<div class="max-w-md w-full text-center">
		<img
			src="{MYAH_BASE_URL}/static/favicon.png"
			alt="logo"
			class="w-16 h-16 mx-auto mb-8 rounded-2xl opacity-50"
		/>

		<h1 class="text-2xl font-semibold mb-3">
			{$i18n.t('Hermes dashboard is not running')}
		</h1>

		<p class="text-sm text-gray-600 dark:text-gray-400 mb-6">
			{$i18n.t(
				'{{name}} talks to the dashboard for providers, toolsets, and model lists. The dashboard runs as a second Hermes process alongside the gateway.',
				{ name: $MYAH_NAME }
			)}
		</p>

		<div
			class="rounded-2xl border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20 p-4 mb-6 text-left"
		>
			<div class="text-sm font-medium mb-2">
				{$i18n.t('Expected dashboard at:')}
			</div>
			<code
				class="text-xs bg-white dark:bg-gray-900 px-2 py-1 rounded border border-gray-200 dark:border-gray-800 break-all block mb-4"
				>{probe.dashboard_url}</code
			>

			<div class="text-sm font-medium mb-2">
				{$i18n.t('To start it, run:')}
			</div>
			<code
				class="text-xs bg-white dark:bg-gray-900 px-2 py-1 rounded border border-gray-200 dark:border-gray-800 block"
				>hermes dashboard --no-open --insecure --host 0.0.0.0 &amp;</code
			>

			<p class="text-xs text-gray-500 dark:text-gray-400 mt-3">
				{$i18n.t(
					'The --insecure --host 0.0.0.0 flags are required so the Myah docker container can reach the dashboard. See docs/gotchas/2026-05-17-oss-dashboard-lan-exposure.md for the security implications.'
				)}
			</p>
			<p class="text-xs text-gray-500 dark:text-gray-400 mt-2">
				{$i18n.t('Or simpler: ./scripts/dev-oss.sh dashboard start')}
			</p>
		</div>

		<button
			type="button"
			class="w-full bg-gray-900 dark:bg-white text-white dark:text-gray-900 rounded-2xl py-3 px-6 font-medium hover:bg-gray-800 dark:hover:bg-gray-100 transition"
			on:click={() => onRetry()}
		>
			{$i18n.t('Try again')}
		</button>
	</div>
</div>
