<script lang="ts">
	export let activeCount = 0;
	export let pausedCount = 0;
	export let runsThisWeek = 0;

	import { getContext } from 'svelte';

	const i18n = getContext('i18n');
</script>

<div class="flex gap-3 mb-4">
	<div class="flex-1 rounded-2xl bg-gray-850 border border-gray-800 p-3">
		<div class="text-xs text-gray-500 mb-1">Active</div>
		<div class="text-lg font-primary">{activeCount}</div>
	</div>

	<div class="flex-1 rounded-2xl bg-gray-850 border border-gray-800 p-3">
		<div class="text-xs text-gray-500 mb-1">Paused</div>
		<div class="text-lg font-primary">{pausedCount}</div>
	</div>

	<div class="flex-1 rounded-2xl bg-gray-850 border border-gray-800 p-3">
		<div class="text-xs text-gray-500 mb-1">Runs (7d)</div>
		<div class="text-lg font-primary">{runsThisWeek}</div>
	</div>
</div>
