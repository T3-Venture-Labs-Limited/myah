<script lang="ts">
	export let space: any;
	export let taskCount: number = 0;
</script>

<a
	href="/spaces/{space.id}"
	class="block p-4 rounded-2xl border border-gray-200 dark:border-gray-800 hover:border-gray-300 dark:hover:border-gray-700 hover:shadow-sm transition bg-white dark:bg-gray-950"
>
	<div class="flex items-center gap-3 mb-2">
		{#if space.meta?.icon}
			<span class="text-xl">{space.meta.icon}</span>
		{:else}
			<div
				class="size-8 rounded-lg bg-gray-100 dark:bg-gray-800 flex items-center justify-center flex-shrink-0"
			>
				<svg
					class="size-4 text-gray-400"
					fill="none"
					viewBox="0 0 24 24"
					stroke="currentColor"
					stroke-width="1.5"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						d="M2.25 12.75V12A2.25 2.25 0 0 1 4.5 9.75h15A2.25 2.25 0 0 1 21.75 12v.75m-8.69-6.44-2.12-2.12a1.5 1.5 0 0 0-1.061-.44H4.5A2.25 2.25 0 0 0 2.25 6v12a2.25 2.25 0 0 0 2.25 2.25h15A2.25 2.25 0 0 0 21.75 18V9a2.25 2.25 0 0 0-2.25-2.25h-5.379a1.5 1.5 0 0 1-1.06-.44Z"
					/>
				</svg>
			</div>
		{/if}
		<div class="font-medium text-sm text-gray-800 dark:text-gray-200 truncate">{space.name}</div>
	</div>
	<div class="text-xs text-gray-400">
		{taskCount}
		{taskCount === 1 ? 'task' : 'tasks'}
	</div>
</a>
