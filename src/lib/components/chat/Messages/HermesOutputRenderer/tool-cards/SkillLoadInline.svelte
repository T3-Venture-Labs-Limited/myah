<script lang="ts">
	import type { FunctionCallItem, FunctionCallOutputItem } from '../types';

	export let call: FunctionCallItem;
	export let result: FunctionCallOutputItem | null = null;
	export let messageDone: boolean = true;

	$: isExecuting = call.status === 'in_progress' && !messageDone;
	$: skillName = (() => {
		try {
			const args = JSON.parse(call.arguments || '{}');
			return args.name ?? args.skill_name ?? '';
		} catch {
			return '';
		}
	})();
</script>

<div
	class="flex items-center gap-1.5 py-1 text-xs text-gray-400 dark:text-gray-500"
	data-has-result={result !== null}
>
	<svg
		class="size-3.5 flex-shrink-0"
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
	>
		<path
			stroke-linecap="round"
			stroke-linejoin="round"
			d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z"
		/>
	</svg>
	{#if isExecuting}
		Loading skill{skillName ? ` ${skillName}` : ''}...
	{:else}
		Loaded skill{skillName ? ` ${skillName}` : ''}
	{/if}
</div>
