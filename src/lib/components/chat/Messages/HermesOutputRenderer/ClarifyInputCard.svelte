<!-- ClarifyInputCard.svelte -->
<!-- The agent asks. The user chooses. -->
<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import type { ClarifyInputItem } from './types';

	export let item: ClarifyInputItem;
	export let messageId: string = '';
	export let localStatus: 'pending' | 'answered' | 'timeout' | 'cancelled' = item.status;
	export let localResponse: string | null | undefined = item.response;

	const dispatch = createEventDispatcher<{
		clarifyAnswered: { clarify_id: string; response: string };
	}>();

	let submitting = false;
	let error = '';
	let otherOpen = false;
	let otherValue = '';
	let freeTextValue = '';

	$: choices = item.choices ?? [];
	$: hasChoices = choices.length > 0;
	$: isInactive = localStatus !== 'pending';

	function requestBody(response: string): Record<string, unknown> {
		return {
			run_id: item.run_id,
			clarify_id: item.clarify_id,
			response
		};
	}

	async function submit(response: string) {
		const trimmed = response.trim();
		if (!trimmed || submitting || isInactive) return;
		submitting = true;
		error = '';

		try {
			const res = await fetch('/openai/chat/clarify', {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					Authorization: `Bearer ${localStorage.token}`
				},
				body: JSON.stringify(requestBody(trimmed))
			});

			if (!res.ok) {
				const body = await res.json().catch(() => ({}));
				error = body?.detail ?? `Request failed (${res.status})`;
				return;
			}

			dispatch('clarifyAnswered', { clarify_id: item.clarify_id, response: trimmed });
		} catch {
			error = 'Network error. Please try again.';
		} finally {
			submitting = false;
		}
	}
</script>

<div
	class="my-2 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-850 overflow-hidden text-sm {isInactive
		? 'opacity-70 grayscale-[20%]'
		: ''}"
>
	<div class="px-4 py-3 border-b border-gray-100 dark:border-gray-700/60">
		<p class="text-xs uppercase tracking-wide text-blue-500 dark:text-blue-400 mb-1">Clarification needed</p>
		<p class="font-medium text-gray-900 dark:text-gray-100">{item.question}</p>
	</div>

	<div class="px-4 py-3">
		{#if localStatus === 'pending'}
			<div class="space-y-3">
				{#if hasChoices}
					<div class="flex flex-wrap gap-2">
						{#each choices as choice}
							<button
								class="px-3 py-1.5 rounded-lg text-sm border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-700/50 font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
								disabled={submitting}
								on:click={() => submit(choice)}
							>
								{choice}
							</button>
						{/each}
						<button
							class="px-3 py-1.5 rounded-lg text-sm border border-gray-200 dark:border-gray-600 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
							disabled={submitting}
							on:click={() => (otherOpen = !otherOpen)}
						>
							Other…
						</button>
					</div>

					{#if otherOpen}
						<div class="flex gap-2">
							<input
								type="text"
								bind:value={otherValue}
								placeholder="Type your answer..."
								disabled={submitting}
								class="min-w-0 flex-1 px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
								on:keydown={(e) => e.key === 'Enter' && submit(otherValue)}
							/>
							<button
								class="px-4 py-1.5 rounded-lg text-sm font-medium border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-700/50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
								disabled={submitting || !otherValue.trim()}
								on:click={() => submit(otherValue)}
							>
								Submit
							</button>
						</div>
					{/if}
				{:else}
					<div class="flex gap-2">
						<input
							type="text"
							bind:value={freeTextValue}
							placeholder="Type your answer..."
							disabled={submitting}
							class="min-w-0 flex-1 px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
							on:keydown={(e) => e.key === 'Enter' && submit(freeTextValue)}
						/>
						<button
							class="px-4 py-1.5 rounded-lg text-sm font-medium border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-700/50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
							disabled={submitting || !freeTextValue.trim()}
							on:click={() => submit(freeTextValue)}
						>
							Submit
						</button>
					</div>
				{/if}

				{#if error}
					<p class="text-xs text-red-500">{error}</p>
				{/if}
			</div>
		{:else if localStatus === 'answered'}
			<p class="text-gray-500 dark:text-gray-400">
				Answered{localResponse ? `: ${localResponse}` : '.'}
			</p>
		{:else if localStatus === 'timeout'}
			<p class="text-gray-400 dark:text-gray-500">
				This clarification request timed out. Please re-send your message if it is still needed.
			</p>
		{:else if localStatus === 'cancelled'}
			<p class="text-gray-400 dark:text-gray-500">
				This clarification request is no longer active.
			</p>
		{/if}
	</div>

	{#if localStatus === 'pending'}
		<div class="px-4 pb-3 flex items-center gap-1.5 text-xs text-blue-500 dark:text-blue-400">
			<span class="relative flex h-2 w-2 flex-shrink-0">
				<span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
				<span class="relative inline-flex rounded-full h-2 w-2 bg-blue-500"></span>
			</span>
			Awaiting user input
		</div>
	{/if}
</div>
