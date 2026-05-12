<script lang="ts">
	// A card that demands attention — the agent has a question
	// and will not proceed until you answer.

	import type { Process } from '$lib/apis/processes';
	import { WEBUI_API_BASE_URL } from '$lib/constants';
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	const i18n = getContext('i18n');

	export let process: Process;
	export let onUpdate: () => void;

	let answer = '';
	let sending = false;

	function extractQuestion(): string {
		if (process.last_run_headline) {
			const match = process.last_run_headline.match(/\[PENDING_INPUT:\s*(.*?)\]/);
			if (match) return match[1];
			return process.last_run_headline;
		}
		return process.prompt ?? '';
	}

	async function handleSend(e: Event) {
		e.preventDefault();
		if (!answer.trim() || sending) return;
		sending = true;
		let error = null;
		const res = await fetch(`${WEBUI_API_BASE_URL}/processes/${process.id}/respond`, {
			method: 'POST',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${localStorage.token}`
			},
			body: JSON.stringify({ answer: answer.trim() })
		})
			.then(async (res) => {
				if (!res.ok) throw await res.json();
				return res.json();
			})
			.catch((err) => {
				console.error(err);
				error = 'detail' in err ? err.detail : err;
				return null;
			});
		if (error) {
			toast.error(`${error}`);
		} else {
			answer = '';
			toast.success('Answer sent');
			onUpdate();
		}
		sending = false;
	}
</script>

<div
	class="rounded-2xl border border-amber-500/20 border-l-[2px] border-l-amber-500 bg-neutral-900/50 p-4"
>
	<div class="flex items-center justify-between mb-2">
		<span class="text-sm font-medium text-gray-100 truncate">
			{process.name}
		</span>
		<span
			class="flex-shrink-0 text-xs bg-amber-500/10 text-amber-400 border border-amber-500/20 rounded-lg px-2 py-0.5"
		>
			Needs your input
		</span>
	</div>

	<p class="text-sm text-gray-300 mb-3 line-clamp-3">
		{extractQuestion()}
	</p>

	<form on:submit={handleSend} class="flex items-center gap-2">
		<input
			type="text"
			bind:value={answer}
			placeholder="Type your answer…"
			disabled={sending}
			class="flex-1 rounded-xl bg-neutral-900 border border-neutral-700 px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-amber-500/50 transition disabled:opacity-50"
		/>
		<button
			type="submit"
			disabled={!answer.trim() || sending}
			class="flex-shrink-0 rounded-xl bg-amber-500 text-white text-sm font-medium px-3 py-2 hover:bg-amber-600 transition disabled:opacity-50 disabled:cursor-not-allowed"
		>
			{#if sending}
				<div
					class="size-4 border-2 border-white/30 border-t-transparent rounded-full animate-spin"
				></div>
			{:else}
				<svg
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					stroke-width="2"
					stroke="currentColor"
					class="size-4"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						d="M6 12 3.269 3.125A59.769 59.769 0 0 1 21.485 12 59.768 59.768 0 0 1 3.27 20.875L5.999 12Zm0 0h7.5"
					/>
				</svg>
			{/if}
		</button>
	</form>
</div>
