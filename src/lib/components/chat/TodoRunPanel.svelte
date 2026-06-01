<script lang="ts">
	import type { TodoPanelData, TodoPanelItem } from '$lib/utils/todoOutput';

	export let data: TodoPanelData;
	export let onHide: () => void = () => {};

	const statusClass = (item: TodoPanelItem) =>
		item.status === 'completed'
			? 'text-gray-500 line-through dark:text-gray-500'
			: item.status === 'in_progress'
				? 'text-gray-800 dark:text-gray-100'
				: 'text-gray-600 dark:text-gray-300';
</script>

<div
	data-testid="todo-run-panel"
	class="relative z-20 mx-3 mt-12 rounded-2xl border border-gray-100 bg-white/80 px-4 py-3 text-gray-900 shadow-sm backdrop-blur-xl dark:border-gray-800 dark:bg-gray-900/80 dark:text-gray-100 sm:mx-6"
>
	<div class="flex items-center justify-between gap-3 text-xs text-gray-500 dark:text-gray-400">
		<div class="flex min-w-0 flex-1 items-center gap-3">
			<div class="flex h-1.5 w-28 overflow-hidden rounded-full bg-gray-200/80 dark:bg-gray-800">
				<div
					class="h-full rounded-full bg-pink-500 transition-all"
					style="width: {data.total > 0 ? (data.completed / data.total) * 100 : 0}%"
				></div>
			</div>
			<span class="shrink-0 tabular-nums">{data.completed} / {data.total}</span>
			<span class="truncate">{data.complete ? 'All steps complete' : 'Working through steps'}</span>
		</div>

		<button
			type="button"
			data-testid="todo-run-hide"
			class="shrink-0 rounded-full px-2 py-1 text-xs text-gray-500 transition hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100"
			on:click={onHide}
		>
			Hide
		</button>
	</div>

	<ul class="mt-3 space-y-2 text-sm" aria-label="Current todo list">
		{#each data.items as item (item.id)}
			<li class="flex items-start gap-2">
				<span
					class="mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border {item.status ===
					'completed'
						? 'border-pink-500 bg-pink-500 text-white'
						: item.status === 'in_progress'
							? 'border-pink-400 bg-pink-500/10 text-pink-500'
							: 'border-gray-300 text-transparent dark:border-gray-700'}"
					aria-hidden="true"
				>
					{#if item.status === 'completed'}✓{:else if item.status === 'in_progress'}•{/if}
				</span>
				<span class={statusClass(item)}>{item.content}</span>
			</li>
		{/each}
	</ul>
</div>
