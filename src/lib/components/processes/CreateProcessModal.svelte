<script lang="ts">
	// The gateway to a new standing commitment.
	// The user describes what they want in plain language.
	// We turn it into a structured cron job the agent can keep.

	import { createEventDispatcher, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { generateOpenAIChatCompletion } from '$lib/apis/openai';
	import { createProcess } from '$lib/apis/processes';

	const dispatch = createEventDispatcher();
	const i18n = getContext('i18n');

	// Optional: when this modal is opened from inside a chat surface, pass
	// the active chat's UUID so the platform can synthesise an `origin`
	// object for the agent.  The platform rejects `local:`-prefixed
	// temporary IDs — only forward real UUIDs (Bug C-frontend).
	export let chatId: string | undefined = undefined;

	let step: 'describe' | 'confirm' = 'describe';
	let description = '';
	let parsing = false;
	let creating = false;

	// Parsed / editable fields
	let name = '';
	let schedule = '';
	let prompt = '';
	let parseError = '';

	async function handleParse() {
		if (!description.trim()) return;
		parsing = true;
		parseError = '';

		try {
			const res = await generateOpenAIChatCompletion(localStorage.token, {
				model: 'myah',
				messages: [
					{
						role: 'system',
						content: `You are a cron job parser. The user will describe a recurring automated task.
Extract a cron job definition and return ONLY valid JSON with exactly these fields:
{
  "name": "short-kebab-case-name",
  "schedule": "interval string like '15m', 'every 1h', '0 9 * * *'",
  "prompt": "the full self-contained prompt the agent should execute on each run, with enough detail to act autonomously"
}
Rules:
- name: max 40 chars, kebab-case, descriptive
- schedule: use interval format (30m, every 2h) for simple repeats, cron for specific times
- prompt: must be fully self-contained — the agent has no memory of the conversation when it runs`
					},
					{
						role: 'user',
						content: description
					}
				],
				temperature: 0.2
			});

			const raw = res?.choices?.[0]?.message?.content ?? '';
			// Extract JSON from the response
			const match = raw.match(/\{[\s\S]*\}/);
			if (!match) throw new Error('No JSON found in response');

			const parsed = JSON.parse(match[0]);
			name = (parsed.name ?? '').trim();
			schedule = (parsed.schedule ?? '').trim();
			prompt = (parsed.prompt ?? '').trim();

			if (!name || !schedule || !prompt) throw new Error('Incomplete fields returned');

			step = 'confirm';
		} catch (err) {
			parseError = `Couldn't parse your description. Try being more specific, e.g. "Check my inbox every hour and summarise new emails".`;
			console.error(err);
		} finally {
			parsing = false;
		}
	}

	async function handleCreate() {
		if (!name || !schedule || !prompt) return;
		creating = true;
		try {
			// Only forward chat_id when it's a real DB UUID — never the
			// `local:` temporary-chat shape (matches the platform's
			// link-chat ownership policy and the agent's
			// _KNOWN_DELIVERY_PLATFORMS guard).
			const payload: { name: string; schedule: string; prompt: string; chat_id?: string } = {
				name,
				schedule,
				prompt
			};
			if (chatId && !chatId.startsWith('local:')) {
				payload.chat_id = chatId;
			}
			const process = await createProcess(localStorage.token, payload);
			toast.success(`Process "${process.name}" created`);
			dispatch('created', process);
		} catch (err) {
			toast.error(`${err}`);
		} finally {
			creating = false;
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') dispatch('close');
	}
</script>

<svelte:window on:keydown={handleKeydown} />

<!-- Backdrop -->
<div
	class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
	on:click|self={() => dispatch('close')}
	role="dialog"
	aria-modal="true"
>
	<div
		class="w-full max-w-lg bg-white dark:bg-gray-900 rounded-3xl shadow-2xl border border-gray-200 dark:border-gray-800 overflow-hidden"
	>
		<!-- Header -->
		<div
			class="flex items-center justify-between px-6 pt-5 pb-4 border-b border-gray-100 dark:border-gray-800"
		>
			<div>
				<h2 class="text-base font-primary text-gray-900 dark:text-gray-100">
					{step === 'describe' ? 'New Process' : 'Confirm Process'}
				</h2>
				<p class="text-xs text-gray-500 mt-0.5">
					{step === 'describe'
						? 'Describe what you want Myah to do automatically'
						: 'Review and adjust before creating'}
				</p>
			</div>
			<button
				class="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 text-gray-500 transition"
				on:click={() => dispatch('close')}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					stroke-width="1.5"
					stroke="currentColor"
					class="size-4"
				>
					<path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12" />
				</svg>
			</button>
		</div>

		<div class="px-6 py-5">
			{#if step === 'describe'}
				<div class="space-y-4">
					<textarea
						bind:value={description}
						placeholder="e.g. Check my inbox every hour and send me a summary of important emails. Flag anything that looks like a sales inquiry."
						rows={4}
						class="w-full rounded-2xl bg-gray-50 dark:bg-gray-850 border border-gray-200 dark:border-gray-800 px-4 py-3 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-600 resize-none focus:outline-none focus:border-gray-400 dark:focus:border-gray-600 transition"
						on:keydown={(e) => {
							if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleParse();
						}}
					/>

					{#if parseError}
						<p class="text-xs text-red-400">{parseError}</p>
					{/if}

					<!-- Example prompts -->
					<div class="space-y-1.5">
						<p class="text-xs text-gray-500 dark:text-gray-600">Try something like:</p>
						{#each ['Monitor my Google Ads every hour and pause any ad with ROAS below 2x', 'Find 5 new enterprise leads every weekday morning and draft cold emails', 'Build out the website continuously until I say stop'] as example}
							<button
								class="block w-full text-left text-xs text-gray-500 dark:text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition py-0.5"
								on:click={() => (description = example)}
							>
								"{example}"
							</button>
						{/each}
					</div>
				</div>
			{:else}
				<!-- Confirm step — editable fields -->
				<div class="space-y-4">
					<div>
						<label class="text-xs text-gray-500 dark:text-gray-500 block mb-1.5">Name</label>
						<input
							type="text"
							bind:value={name}
							class="w-full rounded-xl bg-gray-50 dark:bg-gray-850 border border-gray-200 dark:border-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:border-gray-400 dark:focus:border-gray-600"
						/>
					</div>

					<div>
						<label class="text-xs text-gray-500 dark:text-gray-500 block mb-1.5">
							Schedule
							<span class="text-gray-400 ml-1">e.g. 30m · every 2h · 0 9 * * *</span>
						</label>
						<input
							type="text"
							bind:value={schedule}
							class="w-full rounded-xl bg-gray-50 dark:bg-gray-850 border border-gray-200 dark:border-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 font-mono focus:outline-none focus:border-gray-400 dark:focus:border-gray-600"
						/>
					</div>

					<div>
						<label class="text-xs text-gray-500 dark:text-gray-500 block mb-1.5">
							Prompt
							<span class="text-gray-400 ml-1">What Myah will do each run</span>
						</label>
						<textarea
							bind:value={prompt}
							rows={5}
							class="w-full rounded-xl bg-gray-50 dark:bg-gray-850 border border-gray-200 dark:border-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 resize-none focus:outline-none focus:border-gray-400 dark:focus:border-gray-600"
						/>
					</div>

					<button
						class="text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition"
						on:click={() => (step = 'describe')}
					>
						← Back to description
					</button>
				</div>
			{/if}
		</div>

		<!-- Footer -->
		<div class="px-6 pb-5 flex justify-end gap-2">
			<button
				class="px-4 py-2 rounded-xl text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
				on:click={() => dispatch('close')}
			>
				Cancel
			</button>

			{#if step === 'describe'}
				<button
					class="px-4 py-2 rounded-xl bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 text-sm font-medium hover:bg-gray-700 dark:hover:bg-white transition disabled:opacity-40"
					disabled={!description.trim() || parsing}
					on:click={handleParse}
				>
					{#if parsing}
						<span class="flex items-center gap-2">
							<div
								class="size-3.5 border-2 border-current border-t-transparent rounded-full animate-spin"
							/>
							Thinking…
						</span>
					{:else}
						Continue →
					{/if}
				</button>
			{:else}
				<button
					class="px-4 py-2 rounded-xl bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 text-sm font-medium hover:bg-gray-700 dark:hover:bg-white transition disabled:opacity-40"
					disabled={!name || !schedule || !prompt || creating}
					on:click={handleCreate}
				>
					{#if creating}
						<span class="flex items-center gap-2">
							<div
								class="size-3.5 border-2 border-current border-t-transparent rounded-full animate-spin"
							/>
							Creating…
						</span>
					{:else}
						Create process
					{/if}
				</button>
			{/if}
		</div>
	</div>
</div>
