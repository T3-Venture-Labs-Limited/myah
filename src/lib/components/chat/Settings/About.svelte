<script lang="ts">
	import { MYAH_BUILD_HASH, MYAH_VERSION } from '$lib/constants';
	import { WEBUI_NAME, config } from '$lib/stores';
	import { getContext } from 'svelte';

	import Tooltip from '$lib/components/common/Tooltip.svelte';

	const i18n = getContext('i18n');
</script>

<div id="tab-about" class="flex flex-col h-full justify-between space-y-3 text-sm mb-6">
	<div class=" space-y-3 overflow-y-scroll max-h-[28rem] md:max-h-full">
		<div>
			<div class=" mb-2.5 text-sm font-medium flex space-x-2 items-center">
				<div>
					{$WEBUI_NAME}
					{$i18n.t('Version')}
				</div>
			</div>
			<div class="flex w-full justify-between items-center">
				<div class="flex flex-col text-xs text-gray-700 dark:text-gray-200">
					<div class="flex gap-1">
						<Tooltip content={MYAH_BUILD_HASH}>
							v{MYAH_VERSION}
						</Tooltip>
					</div>
				</div>
			</div>
		</div>

		<hr class=" border-gray-100/30 dark:border-gray-850/30" />

		{#if $config?.license_metadata}
			<div class="mb-2 text-xs">
				{#if !$WEBUI_NAME.includes('Myah')}
					<span class=" text-gray-500 dark:text-gray-300 font-medium">{$WEBUI_NAME}</span> -
				{/if}

				<span class=" capitalize">{$config?.license_metadata?.type}</span> license purchased by
				<span class=" capitalize">{$config?.license_metadata?.organization_name}</span>
			</div>
		{/if}

		<div class="mt-2 text-xs text-gray-400 dark:text-gray-500">
			Emoji graphics provided by
			<a href="https://github.com/jdecked/twemoji" target="_blank">Twemoji</a>, licensed under
			<a href="https://creativecommons.org/licenses/by/4.0/" target="_blank">CC-BY 4.0</a>.
		</div>

		<div>
			<pre
				class="text-xs text-gray-400 dark:text-gray-500">Copyright (c) {new Date().getFullYear()} Myah Inc. All rights reserved.
</pre>
		</div>

		<div class="mt-2 text-xs text-gray-400 dark:text-gray-500">
			{$i18n.t('Built by')}
			<a
				class=" text-gray-500 dark:text-gray-300 font-medium"
				href="https://t3venturelabs.com"
				target="_blank">T3 Venture Labs</a
			>
		</div>
	</div>
</div>
