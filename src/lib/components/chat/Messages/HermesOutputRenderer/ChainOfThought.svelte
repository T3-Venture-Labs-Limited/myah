<script lang="ts">
	import { getContext } from 'svelte';
	import { slide } from 'svelte/transition';
	import { quintOut } from 'svelte/easing';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';

	import Brain from '$lib/components/icons/Brain.svelte';
	import Wrench from '$lib/components/icons/Wrench.svelte';
	import Code from '$lib/components/icons/Code.svelte';
	import Dot from '$lib/components/icons/Dot.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';

	import ChainOfThoughtStep from './ChainOfThoughtStep.svelte';
	import Reasoning from './Reasoning.svelte';
	import ToolCallCard from './ToolCallCard.svelte';
	import CodeExecutionBlock from './CodeExecutionBlock.svelte';
	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';

	import type { NonMessageItem } from './groupChronologically';
	import type { FunctionCallOutputItem, ReasoningItem } from './types';
	import { scheduleRender } from '$lib/utils/rafScheduler';

	const i18n: Writable<i18nType> = getContext('i18n');

	export let items: NonMessageItem[];
	export let messageId: string = '';
	export let messageDone: boolean = false;
	export let findResult: (callId: string) => FunctionCallOutputItem | undefined;

	// User-controlled open state: auto while running, respect user once toggled.
	let userToggled = false;
	let manualOpen = false;

	$: anyRunning = items.some((i) => i.status === 'in_progress') && !messageDone;
	$: open = userToggled ? manualOpen : anyRunning;

	// Short-circuit: a chain of a single reasoning item renders as a plain Reasoning
	// component (matching the shadcn Reasoning reference exactly).
	$: isSingleReasoning = items.length === 1 && items[0].type === 'reasoning';

	$: totalDurationSec = items.reduce((sum, i) => {
		if (i.type === 'reasoning' && typeof i.duration === 'number') return sum + i.duration;
		return sum;
	}, 0);

	$: toolStepCount = items.filter((i) => i.type !== 'reasoning').length;

	$: summaryLabel = (() => {
		if (anyRunning) return $i18n.t('Thinking and working...');

		const durationPart =
			totalDurationSec === 0
				? $i18n.t('a few seconds')
				: totalDurationSec < 1
					? $i18n.t('less than a second')
					: totalDurationSec < 60
						? $i18n.t('{{count}}s', { count: Math.round(totalDurationSec) })
						: (() => {
								const mins = Math.floor(totalDurationSec / 60);
								const secs = Math.round(totalDurationSec % 60);
								return $i18n.t('{{mins}}m {{secs}}s', { mins, secs });
							})();

		const stepPart =
			toolStepCount === 1
				? $i18n.t('1 step')
				: toolStepCount > 1
					? $i18n.t('{{count}} steps', { count: toolStepCount })
					: '';

		const parts = [
			$i18n.t('Chain of Thought'),
			$i18n.t('Thought for {{duration}}', { duration: durationPart })
		];
		if (stepPart) parts.push(stepPart);
		return parts.join(' · ');
	})();

	// rAF-throttled reasoning text extraction, mirroring Reasoning.svelte logic.
	const STATUS_NOISE = /^(\s*[-•*]\s*)?(agent\s+ready|thinking\.{0,3}|processing\.{0,3})\s*$/i;
	let reasoningTexts: Record<string, string> = {};

	$: {
		// Snapshot item summaries and schedule rAF to update the text.
		for (const item of items) {
			if (item.type === 'reasoning') {
				const itemId = (item as ReasoningItem).id;
				const snapshot = (item as ReasoningItem).summary;
				scheduleRender(`cot-reasoning-${itemId}`, () => {
					const raw = snapshot?.map((p) => p.text).join('').trim() ?? '';
					const lines = raw.split('\n').filter((l) => !STATUS_NOISE.test(l.trim()));
					reasoningTexts = { ...reasoningTexts, [itemId]: lines.join('\n').trim() };
				});
			}
		}
	}

	function stepStatus(item: NonMessageItem): 'complete' | 'active' | 'pending' {
		if (item.status === 'in_progress' && !messageDone) return 'active';
		return 'complete';
	}

	function toggle() {
		if (userToggled) {
			manualOpen = !manualOpen;
		} else {
			userToggled = true;
			manualOpen = !open;
		}
	}
</script>

{#if isSingleReasoning}
	<Reasoning item={items[0] as ReasoningItem} {messageId} {messageDone} />
{:else}
	<div class="cot">
		<button
			class="cot-trigger"
			on:click={toggle}
			type="button"
			aria-expanded={open}
		>
			<span class="cot-icon"><Brain className="size-4" /></span>
			<span class="cot-label" class:shimmer={anyRunning}>{summaryLabel}</span>
			<span class="cot-chevron" class:open>
				<ChevronDown className="size-3.5" />
			</span>
		</button>

		{#if open}
			<div transition:slide={{ duration: 180, easing: quintOut }}>
				<div class="cot-body">
					{#each items as item, i (item.id)}
						{@const last = i === items.length - 1}
						{#if item.type === 'reasoning'}
							<ChainOfThoughtStep icon={Dot} status={stepStatus(item)} isLast={last}>
								{#if reasoningTexts[item.id]}
									<div class="cot-reasoning-text">
										<Markdown
											id="{messageId}-cot-reasoning-{item.id}"
											content={reasoningTexts[item.id]}
										/>
									</div>
								{:else if anyRunning && item.status === 'in_progress'}
									<span class="shimmer cot-pending">{$i18n.t('Thinking...')}</span>
								{/if}
							</ChainOfThoughtStep>
						{:else if item.type === 'function_call'}
							<ChainOfThoughtStep icon={Wrench} status={stepStatus(item)} isLast={last}>
								<ToolCallCard
									call={item}
									result={findResult(item.call_id) ?? null}
									messageDone={messageDone}
								/>
							</ChainOfThoughtStep>
						{:else if item.type === 'open_webui:code_interpreter'}
							<ChainOfThoughtStep icon={Code} status={stepStatus(item)} isLast={last}>
								<CodeExecutionBlock {item} {messageId} messageDone={messageDone} />
							</ChainOfThoughtStep>
						{/if}
					{/each}
				</div>
			</div>
		{/if}
	</div>
{/if}

<style>
	.cot {
		width: 100%;
	}

	.cot-trigger {
		display: inline-flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.25rem 0;
		background: transparent;
		border: none;
		cursor: pointer;
		color: var(--myah-text-muted);
		font-size: 13px;
		transition: color 150ms ease;
	}

	.cot-trigger:hover {
		color: var(--myah-text-secondary);
	}

	.cot-icon {
		flex-shrink: 0;
	}

	.cot-label {
		flex: 1;
		text-align: left;
		min-width: 0;
	}

	.cot-chevron {
		display: inline-flex;
		transition: transform 200ms ease;
	}

	.cot-chevron.open {
		transform: rotate(180deg);
	}

	.cot-body {
		margin-top: 0.75rem;
		display: flex;
		flex-direction: column;
	}

	.cot-reasoning-text {
		white-space: pre-wrap;
		font-size: 13px;
		color: var(--myah-text-secondary);
		line-height: 1.55;
	}

	.cot-pending {
		font-size: 13px;
		color: var(--myah-text-muted);
	}
</style>
