<!-- CronRunMessage.svelte -->
<!-- A record of what ran while you were away. Each cron run is its own small world — -->
<!-- sealed in time, opened on request. -->
<script lang="ts">
	import { slide } from 'svelte/transition';
	import type { Process } from '$lib/apis/processes';
	import Markdown from './Markdown.svelte';
	import HermesOutputRenderer from './HermesOutputRenderer.svelte';
	import type { OutputItem } from './HermesOutputRenderer/types';

	export let message: any;
	export let linkedProcess: Process | null = null;
	export let output: OutputItem[] | null = null;

	let runExpanded = false;
	let cardExpanded = false;

	// Parse the cron run message content
	// Format: **Cron run** ({ran_at})\n\n{response}
	// Or: ⚠️**Cron run** ({ran_at})\n\n{response}
	$: isError = message?.content?.startsWith('⚠️');
	$: rawContent = isError ? message.content.slice(2) : (message.content ?? '');

	$: parsed = (() => {
		const match = rawContent.match(/^\*\*Cron run\*\* \(([^)]+)\)\n\n([\s\S]*)$/);
		if (match) {
			return { ran_at: match[1], response: match[2].trim() };
		}
		return { ran_at: '', response: rawContent };
	})();

	$: formattedTime = (() => {
		if (!parsed.ran_at) return '';
		try {
			return new Date(parsed.ran_at).toLocaleTimeString(undefined, {
				hour: '2-digit',
				minute: '2-digit'
			});
		} catch {
			return parsed.ran_at;
		}
	})();

	$: processName = linkedProcess?.name ?? 'Scheduled task';
	$: preview = parsed.response.slice(0, 80).replace(/\n/g, ' ');
</script>

<!-- Scheduled task pill (centered) -->
<div class="flex justify-center my-3">
	<div
		class="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium
		       bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 border border-gray-200 dark:border-gray-700"
	>
		<!-- Clock icon -->
		<svg
			class="size-3.5 flex-shrink-0"
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
		<span>Scheduled task: {processName}</span>
		{#if formattedTime}
			<span class="text-gray-400 dark:text-gray-500">{formattedTime}</span>
		{/if}
	</div>
</div>

<!-- Running scheduled task — collapsible section -->
<div class="w-full">
	<button
		class="flex items-center gap-2 w-full text-left text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 transition py-1"
		on:click={() => (runExpanded = !runExpanded)}
	>
		<!-- Expand/collapse chevron -->
		<svg
			class="size-3.5 flex-shrink-0 transition-transform {runExpanded ? 'rotate-90' : ''}"
			fill="none"
			viewBox="0 0 24 24"
			stroke="currentColor"
			stroke-width="2.5"
		>
			<path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
		</svg>

		<span class="font-medium">Running scheduled task</span>

		{#if formattedTime}
			<span class="ml-auto text-gray-400 dark:text-gray-500">{formattedTime}</span>
		{/if}
	</button>

	{#if runExpanded}
		<div transition:slide={{ duration: 200 }} class="mt-1 mb-2">
			<!-- Run card — expandable -->
			<div
				class="rounded-xl border {isError
					? 'border-red-200 dark:border-red-900/50'
					: 'border-gray-200 dark:border-gray-700'} overflow-hidden"
			>
				<!-- Card header — collapsed preview -->
				<button
					class="w-full flex items-center gap-2.5 px-3 py-2.5 text-left hover:bg-gray-50 dark:hover:bg-gray-850 transition"
					on:click={() => (cardExpanded = !cardExpanded)}
				>
					<!-- Terminal / status icon -->
					{#if isError}
						<span class="size-2 rounded-full flex-shrink-0 bg-red-500"></span>
					{:else}
						<svg
							class="size-4 flex-shrink-0 text-gray-400 dark:text-gray-500"
							fill="none"
							viewBox="0 0 24 24"
							stroke="currentColor"
							stroke-width="1.5"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="m6.75 7.5 3 2.25-3 2.25m4.5 0h3m-9 8.25h13.5A2.25 2.25 0 0 0 21 18V6a2.25 2.25 0 0 0-2.25-2.25H5.25A2.25 2.25 0 0 0 3 6v12a2.25 2.25 0 0 0 2.25 2.25Z"
							/>
						</svg>
					{/if}

					<!-- Process name -->
					<span class="text-sm font-medium text-gray-700 dark:text-gray-300 flex-shrink-0">
						{processName}
					</span>

					<!-- Preview text -->
					{#if preview && !cardExpanded}
						<span class="text-xs text-gray-400 dark:text-gray-500 truncate flex-1 min-w-0">
							{preview}
						</span>
					{/if}

					<div class="ml-auto flex-shrink-0">
						<svg
							class="size-4 text-gray-400 transition-transform {cardExpanded ? 'rotate-90' : ''}"
							fill="none"
							viewBox="0 0 24 24"
							stroke="currentColor"
							stroke-width="1.5"
						>
							<path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
						</svg>
					</div>
				</button>

				<!-- Expanded content -->
				{#if cardExpanded}
					<div
						transition:slide={{ duration: 200 }}
						class="border-t border-gray-100 dark:border-gray-800 px-4 py-3"
					>
						<div
							class="text-sm text-gray-700 dark:text-gray-300 prose dark:prose-invert prose-sm max-w-none"
						>
							{#if output && output.length > 0}
								<HermesOutputRenderer {output} messageId={message.id} done={true} />
							{:else}
								<Markdown id={message.id} content={parsed.response} />
							{/if}
						</div>
						{#if parsed.ran_at}
							<p class="mt-3 text-xs text-gray-400">
								{new Date(parsed.ran_at).toLocaleString(undefined, {
									month: 'short',
									day: 'numeric',
									hour: '2-digit',
									minute: '2-digit'
								})}
							</p>
						{/if}
					</div>
				{/if}
			</div>
		</div>
	{/if}
</div>
