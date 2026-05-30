<!-- ConfirmationCard.svelte -->
<!-- The moment of decision. The agent pauses. The user speaks. -->
<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import type { ApprovalOption } from '$lib/types/contract';
	import type { ConfirmationItem } from './types';

	export let item: ConfirmationItem;
	export let messageId: string = '';
	export let localStatus: 'pending' | 'resolved' | 'cancelled' = item.status;
	export let localChosen: ApprovalOption | string | null | undefined = item.chosen;

	const dispatch = createEventDispatcher<{
		confirmed: { item_id: string; confirmation_id: string; choice: ApprovalOption };
		retry: { confirmation_id: string; run_id: string };
	}>();

	let submitting = false;
	let error = '';
	// ── Stuck-confirmation recovery (Task 2.1) ───────────────────────────
	// When /confirm returns 404 the agent's pending-confirmation registry
	// has no record of this confirmation_id — the buttons can never
	// succeed. Rather than silently flipping to 'cancelled' (which leaves
	// the user with no recourse), we expose a Retry affordance that
	// re-sends the original prompt via the parent chain.
	let interrupted = false;

	// Keys are typed as ``ApprovalOption`` so adding a new approval option
	// upstream lights up a TS error here until we provide a label for it.
	const optionLabels: Record<ApprovalOption, string> = {
		approve: 'Approve',
		approve_session: 'Approve for session',
		deny: 'Deny'
	};

	// ── Cron approvals show only Approve / Deny ────────────────────────
	// "Approve for session" is conceptually meaningless for autonomous
	// cron runs (there's no chat "session" for the approval to scope to).
	// Detect cron approvals via the presence of metadata.schedule_display
	// (set by Hermes for cron-typed confirmations) and filter the options.
	$: visibleOptions = item.metadata?.schedule_display
		? item.options.filter((opt) => opt !== 'approve_session')
		: item.options;
	// ────────────────────────────────────────────────────────────────────

	async function choose(choice: ApprovalOption) {
		if (submitting || localStatus !== 'pending') return;
		submitting = true;
		error = '';

		try {
			const res = await fetch('/openai/chat/confirm', {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					Authorization: `Bearer ${localStorage.token}`
				},
				body: JSON.stringify({
					run_id: item.run_id,
					// Bug B follow-on: include confirmation_id so the
					// agent can resolve action confirmations precisely
					// instead of relying on the session_key fallback.
					confirmation_id: item.confirmation_id,
					choice
				})
			});

			if (!res.ok) {
				const body = await res.json().catch(() => ({}));
				const detail = body?.detail ?? `Request failed (${res.status})`;
				// ── Stuck-confirmation recovery (Task 2.1) ───────────────
				// A 404 from /openai/chat/confirm means the agent's pending
				// confirmation registry has no record of this confirmation_id
				// — typically because the agent container was restarted or
				// the run timed out. The buttons can never succeed. Surface
				// a Retry affordance instead of silently cancelling so the
				// user can resume the conversation with one click.
				if (res.status === 404) {
					interrupted = true;
					error = '';
				} else {
					error = detail;
				}
				// ─────────────────────────────────────────────────────────
				submitting = false;
				return;
			}

			dispatch('confirmed', { item_id: item.id, confirmation_id: item.confirmation_id, choice });
		} catch {
			error = 'Network error. Please try again.';
			submitting = false;
		}
	}

	function retry() {
		// The parent component owns the chat history and the actual
		// message-resend helper (Chat.svelte::submitMessage). All we know
		// here is the identity of the dead run; let upstream resolve it
		// to the original user prompt.
		dispatch('retry', {
			confirmation_id: item.confirmation_id,
			run_id: item.run_id
		});
	}
</script>

<div
	class="my-2 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-850 overflow-hidden text-sm"
>
	<!-- Header -->
	<div class="px-4 py-3 border-b border-gray-100 dark:border-gray-700/60">
		<p class="font-medium text-gray-900 dark:text-gray-100">{item.description}</p>
		{#if item.metadata?.schedule_display}
			<p class="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
				Schedule: {String(item.metadata.schedule_display)}
			</p>
		{/if}
		{#if item.metadata?.prompt_preview}
			<p class="mt-0.5 text-xs text-gray-500 dark:text-gray-400 line-clamp-1">
				Task: {String(item.metadata.prompt_preview)}
			</p>
		{/if}
	</div>

	<!-- Actions / resolved state -->
	<div class="px-4 py-3">
		{#if interrupted}
			<!-- The run is gone; resume by re-sending the original prompt. -->
			<p class="text-gray-500 dark:text-gray-400 mb-2">
				The agent was interrupted — tap retry to continue.
			</p>
			<button
				class="px-3 py-1.5 rounded-lg text-sm border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-700/50 font-medium transition-colors"
				on:click={retry}
			>
				Retry
			</button>
		{:else if localStatus === 'pending'}
			<div class="flex flex-wrap gap-2">
				{#each visibleOptions as option}
					<button
						class="px-3 py-1.5 rounded-lg text-sm border transition-colors
							{option === 'deny'
							? 'border-gray-200 dark:border-gray-600 text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700/50'
							: 'border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-700/50 font-medium'}
							disabled:opacity-40 disabled:cursor-not-allowed"
						disabled={submitting}
						on:click={() => choose(option as ApprovalOption)}
					>
						{optionLabels[option as ApprovalOption] ?? option}
					</button>
				{/each}
			</div>
			{#if error}
				<p class="mt-2 text-xs text-red-500">{error}</p>
			{/if}
		{:else if localStatus === 'resolved'}
			<p class="text-gray-500 dark:text-gray-400">
				{localChosen === 'deny'
					? 'Denied.'
					: `${optionLabels[localChosen as ApprovalOption] ?? localChosen} — continuing...`}
			</p>
		{:else if localStatus === 'cancelled'}
			<p class="text-gray-400 dark:text-gray-500">
				This run is no longer active. Please re-send your message or start a new chat.
			</p>
		{/if}
	</div>

	<!-- Pulsing "Awaiting user input" indicator -->
	{#if localStatus === 'pending' && !interrupted}
		<div class="px-4 pb-3 flex items-center gap-1.5 text-xs text-blue-500 dark:text-blue-400">
			<span class="relative flex h-2 w-2 flex-shrink-0">
				<span
					class="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"
				></span>
				<span class="relative inline-flex rounded-full h-2 w-2 bg-blue-500"></span>
			</span>
			Awaiting user input
		</div>
	{/if}
</div>
