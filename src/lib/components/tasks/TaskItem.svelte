<!-- platform/src/lib/components/tasks/TaskItem.svelte -->
<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	import type { TaskItem as TaskItemType } from '$lib/utils/tasks';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let task: TaskItemType;
	export let selected: boolean = false;
	export let selectionMode: boolean = false;
	export let isSelected: boolean = false;

	let hovered = false;
</script>

<!-- Navigation target: prefer task.chatId (origin chat for cron tasks) so
	multiple crons sharing the same origin chat all link to that chat — the
	Svelte key (task.id) only disambiguates the {#each} loop, it isn't the
	navigation target.  See Bug A in
	docs/superpowers/specs/2026-04-24-cron-origin-and-approval-design.md. -->
<!-- svelte-ignore a11y-no-static-element-interactions -->
<a
	href="/c/{task.chatId ?? task.id}"
	class="group flex items-center gap-2 px-3 py-2.5 rounded-xl cursor-pointer transition-colors
		{isSelected
		? 'bg-blue-50 dark:bg-blue-950/30'
		: selected
			? 'bg-gray-100 dark:bg-gray-850'
			: 'hover:bg-gray-50 dark:hover:bg-gray-900'}"
	on:click|preventDefault={() => {
		if (selectionMode) {
			dispatch('toggle-select', task);
		} else {
			dispatch('select', task);
		}
	}}
	on:mouseenter={() => (hovered = true)}
	on:mouseleave={() => (hovered = false)}
>
	<!-- Status icon / checkbox -->
	<div class="flex-shrink-0 w-5 flex items-center justify-center">
		{#if selectionMode || hovered}
			<!-- svelte-ignore a11y-no-static-element-interactions -->
			<div
				class="size-4 rounded border-2 flex items-center justify-center transition
					{isSelected ? 'bg-blue-500 border-blue-500' : 'border-gray-300 dark:border-gray-600'}"
				on:click|stopPropagation|preventDefault={() => dispatch('toggle-select', task)}
				role="checkbox"
				aria-checked={isSelected}
				tabindex="0"
				on:keydown={(e) => e.key === ' ' && dispatch('toggle-select', task)}
			>
				{#if isSelected}
					<svg class="size-2.5 text-white" fill="currentColor" viewBox="0 0 20 20">
						<path
							fill-rule="evenodd"
							d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
							clip-rule="evenodd"
						/>
					</svg>
				{/if}
			</div>
		{:else if task.status === 'active'}
			<span class="inline-block size-2 rounded-full bg-green-500 animate-pulse"></span>
		{:else if task.status === 'needs_input'}
			<span class="inline-block size-2 rounded-full bg-amber-500"></span>
		{:else if task.status === 'scheduled'}
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
					d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"
				/>
			</svg>
		{:else}
			<svg
				class="size-4 text-gray-400"
				fill="none"
				viewBox="0 0 24 24"
				stroke="currentColor"
				stroke-width="2"
			>
				<path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
			</svg>
		{/if}
	</div>

	<!-- Title -->
	<div class="flex-1 min-w-0">
		<div class="truncate text-sm text-gray-800 dark:text-gray-200">
			{task.title || $i18n.t('New Task')}
		</div>
	</div>

	<!-- File badges -->
	{#if task.files.length > 0}
		<div class="flex-shrink-0 flex gap-1">
			{#each task.files.slice(0, 2) as file}
				<span
					class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-gray-100 dark:bg-gray-800 text-xs text-gray-500 dark:text-gray-400 max-w-[120px]"
				>
					<svg
						class="size-3 flex-shrink-0"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
						stroke-width="1.5"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"
						/>
					</svg>
					<span class="truncate">{file.name}</span>
				</span>
			{/each}
		</div>
	{/if}

	<!-- Context menu trigger -->
	<button
		class="flex-shrink-0 p-1 rounded-lg opacity-0 group-hover:opacity-100 hover:bg-gray-200 dark:hover:bg-gray-700 transition"
		on:click|stopPropagation|preventDefault={(e) => {
			const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
			dispatch('menu', { task, x: rect.left, y: rect.bottom + 4 });
		}}
		aria-label={$i18n.t('Task options')}
	>
		<svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
			<path
				stroke-linecap="round"
				stroke-linejoin="round"
				d="M6.75 12a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0ZM12.75 12a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0ZM18.75 12a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0Z"
			/>
		</svg>
	</button>
</a>
