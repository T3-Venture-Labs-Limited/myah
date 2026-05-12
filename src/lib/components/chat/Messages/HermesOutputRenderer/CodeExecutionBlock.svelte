<script lang="ts">
	import { getContext } from 'svelte';
	import { slide } from 'svelte/transition';
	import { quintOut } from 'svelte/easing';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';

	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import CheckCircle from '$lib/components/icons/CheckCircle.svelte';
	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';

	import type { CodeInterpreterItem } from './types';

	const i18n: Writable<i18nType> = getContext('i18n');

	export let item: CodeInterpreterItem;
	export let messageId: string = '';
	export let messageDone: boolean = true;

	let open = false;

	$: isRunning = item.status === 'in_progress' && !messageDone;
	$: label = isRunning ? $i18n.t('Analyzing...') : $i18n.t('Analyzed');
	$: codeContent = '```' + (item.lang ?? 'python') + '\n' + (item.code ?? '') + '\n```';
	$: outputText = item.output?.result ?? item.output?.output ?? item.output?.error ?? '';
</script>

<div class="w-full my-0.5">
	<button
		class="w-fit text-left text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition cursor-pointer"
		on:click={() => {
			open = !open;
		}}
	>
		<div class="flex items-center gap-1.5 py-0.5">
			{#if isRunning}
				<Spinner className="size-3.5" />
			{:else}
				<div class="text-emerald-500 dark:text-emerald-400">
					<CheckCircle className="size-3.5" strokeWidth="2" />
				</div>
			{/if}
			<span class="text-sm {isRunning ? 'shimmer' : ''}">{label}</span>
			<div class="self-center">
				{#if open}
					<ChevronUp className="size-3" />
				{:else}
					<ChevronDown className="size-3" />
				{/if}
			</div>
		</div>
	</button>

	{#if open}
		<div transition:slide={{ duration: 300, easing: quintOut }}>
			<div class="ml-5 my-1 border-l border-gray-200 dark:border-gray-700 pl-3 space-y-2">
				<Markdown id="{messageId}-code-{item.id}" content={codeContent} />
				{#if outputText}
					<div>
						<div class="text-xs font-medium text-gray-400 dark:text-gray-500 uppercase mb-1">
							{$i18n.t('Output')}
						</div>
						<pre
							class="text-xs overflow-auto max-h-40 whitespace-pre-wrap text-gray-600 dark:text-gray-300">{outputText}</pre>
					</div>
				{/if}
			</div>
		</div>
	{/if}
</div>
