<script lang="ts">
	// Full-screen blocking error shown when the OSS probe reports
	// hermes_reachable=true AND plugin_installed=false. The user's
	// Hermes is alive, but the Myah plugin isn't loaded inside it.
	//
	// Canonical install path per locked decision (supermemory):
	//   hermes plugins install T3-Venture-Labs-Limited/myah-hermes-plugin
	// NOT `pip install myah-hermes-plugin` (which is plugin-dev only).
	import { getContext } from 'svelte';
	import BlockingError from './BlockingError.svelte';

	const i18n = getContext('i18n');

	export let hermesUrl: string;
	export let onRetry: () => void;
</script>

<BlockingError
	title={$i18n.t("Hermes is running, but the Myah plugin isn't installed")}
	{onRetry}
>
	<p>
		{$i18n.t('Myah needs its hermes-side plugin to coordinate with your agent.')}
	</p>
	<p class="mt-3">
		{$i18n.t('Hermes is reachable at:')}
	</p>
	<pre class="bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-800 rounded-lg p-3 my-3 text-sm break-all"><code
			>{hermesUrl}</code
		></pre>
	<p>{$i18n.t('Install the plugin with one command:')}</p>
	<pre class="bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-800 rounded-lg p-3 my-3 text-sm whitespace-pre-wrap"><code
			>hermes plugins install \
  T3-Venture-Labs-Limited/myah-hermes-plugin</code
		></pre>
	<p>{$i18n.t('Then restart Hermes:')}</p>
	<pre class="bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-800 rounded-lg p-3 my-3 text-sm"><code
			>hermes gateway restart</code
		></pre>
</BlockingError>
