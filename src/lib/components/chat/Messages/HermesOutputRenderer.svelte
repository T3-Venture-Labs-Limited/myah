<script lang="ts">
	import MessageText from './HermesOutputRenderer/MessageText.svelte';
	import ChainOfThought from './HermesOutputRenderer/ChainOfThought.svelte';
	import ConfirmationCard from './HermesOutputRenderer/ConfirmationCard.svelte';
	import SecretInputCard from './HermesOutputRenderer/SecretInputCard.svelte';
	import ClarifyInputCard from './HermesOutputRenderer/ClarifyInputCard.svelte';
	import InlineArtifactPreview from '../Artifacts/InlineArtifactPreview.svelte';
	import { bumpArtifactExplorerRefresh } from '$lib/stores';

	import type { OutputItem, FunctionCallOutputItem } from './HermesOutputRenderer/types';
	import { groupChronologically } from './HermesOutputRenderer/groupChronologically';
	import { confirmationKey } from './HermesOutputRenderer/confirmationKey';

	export let output: OutputItem[] = [];
	export let messageId: string = '';
	export let done: boolean = true;

	// 2026-05-05 dogfooding: tell the ArtifactExplorer to re-fetch chat
	// files whenever a new artifact_card appears in this message's output.
	// Without this signal the explorer only loads on mount and stays empty
	// forever after the agent creates files mid-session. Tracking by id +
	// file_id avoids re-bumping for the same card on every re-render.
	let _lastSeenArtifactKeys = new Set<string>();
	$: {
		const keys = new Set<string>();
		let novel = false;
		for (const it of output) {
			if (it.type === 'artifact_card') {
				const k = `${it.id}|${it.file_id ?? it.path ?? ''}`;
				keys.add(k);
				if (!_lastSeenArtifactKeys.has(k)) novel = true;
			}
		}
		if (novel) {
			_lastSeenArtifactKeys = keys;
			bumpArtifactExplorerRefresh();
		}
	}

	// Track user-resolved confirmation cards locally so status persists across
	// parent re-renders from continued SSE events (backend still shows 'pending'
	// until run.completed sets it to 'cancelled'). Use the real confirmation_id
	// when present; no-ID exec approvals fall back to run_id:item.id so multiple
	// no-ID approvals in the same run do not collide.
	let resolvedConfirmations = new Map<string, string>(); // confirmationKey(item) → chosen option

	// Track secrets the user has submitted so the card shows 'stored' immediately,
	// without waiting for the backend to re-emit the item with status='stored'.
	let storedSecrets = new Map<string, boolean>(); // var_name → true

	// Track clarify answers locally so the card resolves immediately while the
	// stream waits for Hermes to emit clarify.resolved.
	let answeredClarifies = new Map<string, string>(); // clarify_id → response

	// Find the matching function_call_output for a given call_id.
	// Simple Array.find — no callOutputMap, no synthetic dedup.
	function findResult(callId: string): FunctionCallOutputItem | undefined {
		return output.find(
			(i): i is FunctionCallOutputItem => i.type === 'function_call_output' && i.call_id === callId
		);
	}

	// Group output items chronologically: adjacent reasoning/tool/code items
	// collapse into a single ChainOfThought; messages, confirmations, and
	// secret_input items are rendered as standalone groups.
	$: groups = groupChronologically(output);
</script>

<div class="w-full space-y-1">
	{#each groups as g (g.id)}
		{#if g.kind === 'chain'}
			<ChainOfThought items={g.items} {messageId} messageDone={done} {findResult} />
		{:else if g.kind === 'message'}
			<MessageText item={g.item} {messageId} done={g.item.status === 'completed' || done} />
		{:else if g.kind === 'confirmation'}
			{@const key = confirmationKey(g.item)}
			<ConfirmationCard
				item={g.item}
				{messageId}
				localStatus={resolvedConfirmations.has(key) ? 'resolved' : g.item.status}
				localChosen={resolvedConfirmations.get(key)}
				on:confirmed={(e) => {
					resolvedConfirmations.set(key, e.detail.choice);
					resolvedConfirmations = resolvedConfirmations;
				}}
				on:retry
			/>
		{:else if g.kind === 'secret'}
			<SecretInputCard
				item={g.item}
				{messageId}
				localStatus={storedSecrets.has(g.item.var_name) ? 'stored' : g.item.status}
				on:secretStored={(e) => {
					storedSecrets.set(e.detail.var_name, true);
					storedSecrets = storedSecrets;
				}}
			/>
		{:else if g.kind === 'clarify'}
			<ClarifyInputCard
				item={g.item}
				{messageId}
				localStatus={answeredClarifies.has(g.item.clarify_id) ? 'answered' : g.item.status}
				localResponse={answeredClarifies.get(g.item.clarify_id) ?? g.item.response}
				on:clarifyAnswered={(e) => {
					answeredClarifies.set(e.detail.clarify_id, e.detail.response);
					answeredClarifies = answeredClarifies;
				}}
			/>
		{:else if g.kind === 'artifact'}
			<InlineArtifactPreview item={g.item} />
		{/if}
	{/each}
</div>
