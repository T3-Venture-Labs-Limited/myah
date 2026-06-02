// Structured output items from the Hermes agent backend.
//
// This file is now a thin re-export wrapper over the generated typed
// contract at ``$lib/types/contract``. The Pydantic source of truth
// lives at ``platform/shared/contract/output_items.py`` and is
// regenerated via ``platform/scripts/generate-ts-contract.sh``.
//
// Subcomponents and consumers (``MessageText.svelte``, ``Reasoning.svelte``,
// ``Tool.svelte``, ``ConfirmationCard.svelte``, ``SecretInputCard.svelte``,
// ``CodeExecutionBlock.svelte``, ``groupChronologically.ts``,
// ``HermesOutputRenderer.svelte``, ``ResponseMessage.svelte``,
// ``CronRunMessage.svelte``, ``$lib/types/index.ts``) keep their existing
// imports unchanged — every name the renderer used pre-Phase 4 is still
// re-exported here.
//
// Note on the ``OutputItem`` discriminated union: pydantic2ts emits the
// constituent ``interface``s but inlines the union under
// ``ContractRoot.output_item`` instead of producing a top-level alias.
// We define the alias locally here so the union name survives the codegen
// boundary without resorting to post-processing the generated file.
import type {
	MessageItem,
	FunctionCallItem,
	FunctionCallOutputItem,
	ReasoningItem,
	CodeInterpreterItem,
	ConfirmationItem,
	SecretInputItem,
	ClarifyInputItem,
	ArtifactCardItem,
	TodoPlanItem
} from '$lib/types/contract';

export type {
	MessageItem,
	FunctionCallItem,
	FunctionCallOutputItem,
	ReasoningItem,
	CodeInterpreterItem,
	ConfirmationItem,
	SecretInputItem,
	ClarifyInputItem,
	ArtifactCardItem,
	TodoPlanItem,
	OutputTextPart,
	InputTextPart,
	SummaryTextPart
} from '$lib/types/contract';

export type OutputItem =
	| MessageItem
	| FunctionCallItem
	| FunctionCallOutputItem
	| ReasoningItem
	| CodeInterpreterItem
	| ConfirmationItem
	| SecretInputItem
	| ClarifyInputItem
	| ArtifactCardItem
	| TodoPlanItem;
