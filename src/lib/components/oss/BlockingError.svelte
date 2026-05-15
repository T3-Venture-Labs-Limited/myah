<script lang="ts">
	// Shared full-screen blocking-error shell. Used by HermesDownError +
	// PluginMissingError + (eventually) any other unrecoverable boot state.
	//
	// The user CANNOT bypass this — it replaces the entire UI. The only
	// way forward is to fix the underlying issue and click Retry (which
	// re-runs the probe).
	//
	// Spec ref: §8 'Full-screen blocking error' subsections.
	import { getContext } from 'svelte';

	const i18n = getContext('i18n');

	export let title: string;
	export let onRetry: () => void;
	export let docsUrl: string =
		'https://github.com/T3-Venture-Labs-Limited/myah/blob/master/docs/troubleshooting.md';
</script>

<div class="blocking-error fixed inset-0 z-50 flex items-center justify-center bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 px-6 py-12 overflow-y-auto">
	<div class="max-w-lg w-full">
		<div class="text-center mb-8">
			<div
				class="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 mb-4"
				aria-hidden="true"
			>
				<span class="text-3xl leading-none">!</span>
			</div>
			<h1 class="text-2xl font-semibold mb-2">{title}</h1>
		</div>

		<div class="prose dark:prose-invert max-w-none text-sm mb-8">
			<slot />
		</div>

		<div class="flex flex-col sm:flex-row gap-3">
			<button
				type="button"
				class="flex-1 bg-gray-900 dark:bg-white text-white dark:text-gray-900 rounded-2xl py-3 px-6 font-medium hover:bg-gray-800 dark:hover:bg-gray-100 transition"
				on:click={() => onRetry()}
			>
				{$i18n.t('Retry')}
			</button>
			<a
				href="/diagnostics"
				class="flex-1 text-center border border-gray-200 dark:border-gray-800 rounded-2xl py-3 px-6 font-medium hover:bg-gray-50 dark:hover:bg-gray-800 transition"
			>
				{$i18n.t('View diagnostics')}
			</a>
			<a
				href={docsUrl}
				target="_blank"
				rel="noopener noreferrer"
				class="flex-1 text-center border border-gray-200 dark:border-gray-800 rounded-2xl py-3 px-6 font-medium hover:bg-gray-50 dark:hover:bg-gray-800 transition"
			>
				{$i18n.t('Read docs')}
			</a>
		</div>
	</div>
</div>
