// Groups output items into chronological render groups.
// Adjacent reasoning, function_call, and code_interpreter items are collapsed
// into a single 'chain' group (ChainOfThought). Messages, confirmations, and
// secret_input items are standalone and break any open chain.

import type {
	OutputItem,
	MessageItem,
	FunctionCallItem,
	ReasoningItem,
	CodeInterpreterItem,
	ConfirmationItem,
	SecretInputItem,
	ClarifyInputItem,
	ArtifactCardItem,
	TodoPlanItem
} from './types';

export type NonMessageItem = FunctionCallItem | ReasoningItem | CodeInterpreterItem;

export type RenderGroup =
	| { kind: 'chain'; id: string; items: NonMessageItem[] }
	| { kind: 'message'; id: string; item: MessageItem }
	| { kind: 'confirmation'; id: string; item: ConfirmationItem }
	| { kind: 'secret'; id: string; item: SecretInputItem }
	| { kind: 'clarify'; id: string; item: ClarifyInputItem }
	| { kind: 'artifact'; id: string; item: ArtifactCardItem };

// Type guard: is the item one that belongs inside a chain?
function isChainItem(item: OutputItem): item is NonMessageItem {
	return (
		item.type === 'reasoning' ||
		item.type === 'myah:code_interpreter' ||
		(item.type === 'function_call' && Boolean(item.call_id))
	);
}

// A reasoning item is "useful to render" only if it has non-empty summary text.
// Backend de-dup can leave a reasoning item with an empty summary array; without
// this filter the UI renders a phantom "Thought for N seconds" row with nothing
// inside. Filter defensively at group time.
function hasVisibleReasoningContent(item: ReasoningItem): boolean {
	if (!item.summary || item.summary.length === 0) return false;
	const joined = item.summary
		.map((p) => (p.type === 'summary_text' ? p.text : ''))
		.join('')
		.trim();
	return joined.length > 0;
}

export function groupChronologically(output: OutputItem[]): RenderGroup[] {
	const groups: RenderGroup[] = [];
	let currentChain: NonMessageItem[] | null = null;
	const todoPlanCallIds = new Set(
		output
			.filter((item): item is TodoPlanItem => item.type === 'todo_plan')
			.map((item) => item.call_id)
			.filter(Boolean)
	);

	function flushChain() {
		if (currentChain && currentChain.length > 0) {
			groups.push({ kind: 'chain', id: currentChain[0].id, items: currentChain });
		}
		currentChain = null;
	}

	for (const item of output) {
		// Skip items that are rendered inline by their parent
		if (item.type === 'function_call_output') continue;
		// Skip todo_plan; the pinned strip consumes it outside transcript groups.
		if (item.type === 'todo_plan') continue;
		// Defensively hide generic todo rows when a first-class plan for the same
		// call exists. Backend normally removes these after successful parsing.
		if (item.type === 'function_call' && item.name === 'todo' && todoPlanCallIds.has(item.call_id)) {
			continue;
		}
		// Skip phantom function_call items (no call_id)
		if (item.type === 'function_call' && !item.call_id) continue;
		// Skip empty reasoning items (defensive guard against de-dup leftovers
		// or events that never carried summary text). Keep in_progress ones so
		// the "Thinking..." shimmer can render while streaming hasn't filled
		// any summary text yet.
		if (
			item.type === 'reasoning' &&
			item.status !== 'in_progress' &&
			!hasVisibleReasoningContent(item)
		) {
			continue;
		}

		if (isChainItem(item)) {
			// Extend or start a chain
			if (currentChain === null) {
				currentChain = [item];
			} else {
				currentChain.push(item);
			}
		} else if (item.type === 'message') {
			flushChain();
			groups.push({ kind: 'message', id: item.id, item: item as MessageItem });
		} else if (item.type === 'confirmation') {
			flushChain();
			groups.push({ kind: 'confirmation', id: item.id, item: item as ConfirmationItem });
		} else if (item.type === 'secret_input') {
			flushChain();
			groups.push({ kind: 'secret', id: item.id, item: item as SecretInputItem });
		} else if (item.type === 'clarify_input') {
			flushChain();
			groups.push({ kind: 'clarify', id: item.id, item: item as ClarifyInputItem });
		} else if (item.type === 'artifact_card') {
			flushChain();
			groups.push({ kind: 'artifact', id: item.id, item: item as ArtifactCardItem });
		}
	}

	// Flush any trailing chain
	flushChain();

	return groups;
}
