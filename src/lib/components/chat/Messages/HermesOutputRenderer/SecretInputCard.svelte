<!-- SecretInputCard.svelte -->
<!-- A secret asked for quietly. The key, given once, opens everything. -->
<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import type { SecretInputItem } from './types';

	export let item: SecretInputItem;
	export let messageId: string = '';
	export let localStatus: 'pending' | 'stored' | 'timeout' = item.status;

	const dispatch = createEventDispatcher<{
		secretStored: { var_name: string };
	}>();

	let inputValue = '';
	let loading = false;
	let error = '';

	async function handleSubmit() {
		if (!inputValue.trim()) return;
		loading = true;
		error = '';

		try {
			const response = await fetch('/openai/chat/secret', {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					Authorization: `Bearer ${localStorage.token}`
				},
				body: JSON.stringify({
					run_id: item.run_id,
					var_name: item.var_name,
					value: inputValue
				})
			});

			if (!response.ok) {
				const data = await response.json().catch(() => ({}));
				error = data.detail || 'Failed to save secret';
				return;
			}

			dispatch('secretStored', { var_name: item.var_name });
		} catch (e) {
			error = 'Network error — please try again';
		} finally {
			loading = false;
		}
	}
</script>

<div
	class="my-2 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-850 overflow-hidden text-sm"
>
	<!-- Header -->
	<div class="px-4 py-3 border-b border-gray-100 dark:border-gray-700/60">
		{#if item.skill_name}
			<p class="text-xs text-gray-500 dark:text-gray-400 mb-0.5">{item.skill_name}</p>
		{/if}
		<p class="font-medium text-gray-900 dark:text-gray-100">{item.prompt}</p>
	</div>

	<!-- Body -->
	<div class="px-4 py-3">
		{#if localStatus === 'pending'}
			<div class="space-y-3">
				<div>
					<label
						for="secret-input-{item.id}"
						class="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1"
					>
						{item.var_name}
					</label>
					<input
						id="secret-input-{item.id}"
						type="password"
						autocomplete="new-password"
						bind:value={inputValue}
						placeholder="Enter value..."
						disabled={loading}
						class="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-600
							bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100
							placeholder-gray-400 dark:placeholder-gray-500
							focus:outline-none focus:ring-2 focus:ring-blue-500/40 focus:border-blue-400
							disabled:opacity-50 disabled:cursor-not-allowed text-sm"
						on:keydown={(e) => e.key === 'Enter' && handleSubmit()}
					/>
				</div>

				{#if item.help}
					<a
						href={item.help}
						target="_blank"
						rel="noopener noreferrer"
						class="inline-flex items-center gap-1 text-xs text-blue-500 dark:text-blue-400 hover:underline"
					>
						<svg
							xmlns="http://www.w3.org/2000/svg"
							class="h-3 w-3"
							viewBox="0 0 20 20"
							fill="currentColor"
						>
							<path
								fill-rule="evenodd"
								d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-8-3a1 1 0 00-.867.5 1 1 0 11-1.731-1A3 3 0 0113 8a3.001 3.001 0 01-2 2.83V11a1 1 0 11-2 0v-1a1 1 0 011-1 1 1 0 100-2zm0 8a1 1 0 100-2 1 1 0 000 2z"
								clip-rule="evenodd"
							/>
						</svg>
						Where do I find this?
					</a>
				{/if}

				<button
					class="px-4 py-1.5 rounded-lg text-sm font-medium border
						border-gray-200 dark:border-gray-600
						bg-white dark:bg-gray-800
						text-gray-900 dark:text-gray-100
						hover:bg-gray-50 dark:hover:bg-gray-700/50
						disabled:opacity-40 disabled:cursor-not-allowed
						transition-colors"
					disabled={loading || !inputValue.trim()}
					on:click={handleSubmit}
				>
					{loading ? 'Saving…' : 'Save & Continue'}
				</button>

				{#if error}
					<p class="text-xs text-red-500">{error}</p>
				{/if}
			</div>
		{:else if localStatus === 'stored'}
			<p class="text-gray-500 dark:text-gray-400">Secret stored securely.</p>
		{:else if localStatus === 'timeout'}
			<p class="text-gray-400 dark:text-gray-500">Setup timed out — skill may not work.</p>
		{/if}
	</div>

	<!-- Pulsing "Awaiting input" indicator -->
	{#if localStatus === 'pending'}
		<div class="px-4 pb-3 flex items-center gap-1.5 text-xs text-blue-500 dark:text-blue-400">
			<span class="relative flex h-2 w-2 flex-shrink-0">
				<span
					class="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"
				></span>
				<span class="relative inline-flex rounded-full h-2 w-2 bg-blue-500"></span>
			</span>
			Awaiting input
		</div>
	{/if}
</div>
