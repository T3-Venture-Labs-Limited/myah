<script lang="ts">
	import type { FunctionCallItem, FunctionCallOutputItem } from './types';

	import Agent from './Agent.svelte';
	import Tool from './Tool.svelte';
	import SkillLoadInline from './tool-cards/SkillLoadInline.svelte';

	export let call: FunctionCallItem;
	export let result: FunctionCallOutputItem | null = null;
	export let messageDone: boolean = true;

	// Dispatcher: skill loads render as a subtle inline line; delegate shows as an
	// Agent card with subagent tree; every other tool call uses the unified Tool card.
	$: isSkillLoad = call.name === 'skill_view' || call.name === 'view_skill';
	$: isDelegate = call.name === 'delegate' || call.name === 'delegate_tool';
</script>

{#if isSkillLoad}
	<SkillLoadInline {call} {result} {messageDone} />
{:else if isDelegate}
	<Agent {call} {result} {messageDone} />
{:else}
	<Tool {call} {result} {messageDone} />
{/if}
