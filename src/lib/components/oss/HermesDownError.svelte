<script lang="ts">
	// Full-screen blocking error shown when the OSS probe reports
	// hermes_reachable=false. The platform can't talk to the user's
	// host-side Hermes Agent — chat is non-functional.
	//
	// Remediation text matches spec §8 "Full-screen blocking error —
	// hermes-down" — references `hermes gateway start` (the CLI command
	// to start the running agent, NOT the curl-bash installer, which is
	// for fresh-install).
	import { getContext } from 'svelte';
	import BlockingError from './BlockingError.svelte';

	const i18n = getContext('i18n');

	export let hermesUrl: string;
	export let onRetry: () => void;
</script>

<BlockingError
	title={$i18n.t("Can't reach your Hermes Agent")}
	{onRetry}
>
	<p>
		{$i18n.t('Myah is configured to connect to Hermes at:')}
	</p>
	<pre class="bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-800 rounded-lg p-3 my-3 text-sm break-all"><code
			>{hermesUrl}</code
		></pre>
	<p>{$i18n.t("But Hermes isn't responding there. Two common causes:")}</p>
	<ol class="list-decimal pl-6 space-y-3 my-3">
		<li>
			<div>{$i18n.t("Hermes isn't running. Start it on your host machine:")}</div>
			<pre class="bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-800 rounded-lg p-3 mt-2 text-sm"><code
					>hermes gateway start</code
				></pre>
		</li>
		<li>
			{$i18n.t(
				'Hermes runs on a different port. Edit .env in this repo and update MYAH_HERMES_CHAT_PORT.'
			)}
		</li>
	</ol>
</BlockingError>
