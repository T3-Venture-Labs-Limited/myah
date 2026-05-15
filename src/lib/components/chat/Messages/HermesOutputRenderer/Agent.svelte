<script lang="ts">
	import { getContext } from 'svelte';
	import { slide } from 'svelte/transition';
	import { quintOut } from 'svelte/easing';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';

	import Bot from '$lib/components/icons/Bot.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import CheckCircle from '$lib/components/icons/CheckCircle.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';

	import Badge from './Badge.svelte';
	import type { FunctionCallItem, FunctionCallOutputItem } from './types';
	import { unwrapJSON } from './tool-cards/unwrapJSON';

	const i18n: Writable<i18nType> = getContext('i18n');

	export let call: FunctionCallItem;
	export let result: FunctionCallOutputItem | null = null;
	export let messageDone: boolean = true;

	let open = true;

	$: isRunning = call.status === 'in_progress' && !messageDone;
	$: isFailed = call.status === 'failed';
	$: isDone = call.status === 'completed' && result !== null;

	$: statusLabel = isRunning
		? $i18n.t('Running')
		: isFailed
			? $i18n.t('Error')
			: isDone
				? $i18n.t('Completed')
				: $i18n.t('Pending');

	type Tone = 'neutral' | 'success' | 'running' | 'error' | 'warning';
	$: statusTone = (isRunning
		? 'running'
		: isFailed
			? 'error'
			: isDone
				? 'success'
				: 'neutral') as Tone;

	// Parent task description from call args (for the Instructions section).
	$: parentTask = (() => {
		try {
			const parsed = JSON.parse(call.arguments ?? '{}');
			if (parsed && typeof parsed === 'object') {
				return (parsed.task ?? parsed.prompt ?? parsed.instructions ?? '') as string;
			}
			return '';
		} catch {
			return '';
		}
	})();

	// Subagents list from result output.
	$: rawOutput = result?.output?.map((p) => p.text ?? '').join('') ?? '';
	$: subagents = (() => {
		if (!rawOutput) return [] as Array<{ task: string; result: string }>;
		const parsed = unwrapJSON(rawOutput);
		if (parsed && typeof parsed === 'object') {
			const raw = (parsed as Record<string, unknown>).subagents
				?? (parsed as Record<string, unknown>).children;
			if (Array.isArray(raw)) {
				return raw.map((s: Record<string, unknown>) => ({
					task: (s.task ?? '') as string,
					result: (s.result ?? '') as string
				}));
			}
		}
		return [] as Array<{ task: string; result: string }>;
	})();

	$: hasSubagents = subagents.length > 0;

	$: headerTitle = hasSubagents
		? $i18n.t('Delegating to {{count}} subagents', { count: subagents.length })
		: $i18n.t('Delegate');

	function toggle() {
		open = !open;
	}

	let expandedSub: boolean[] = [];
	$: {
		if (expandedSub.length !== subagents.length) {
			expandedSub = Array.from({ length: subagents.length }, (_, i) => expandedSub[i] ?? false);
		}
	}

	function toggleSub(i: number) {
		expandedSub = expandedSub.map((v, idx) => (idx === i ? !v : v));
	}
</script>

<div class="agent">
	<button
		class="agent-trigger"
		on:click={toggle}
		type="button"
		aria-expanded={open}
	>
		<div class="agent-trigger-left">
			<span class="agent-icon">
				<Bot className="size-4" />
			</span>
			<span class="agent-title">{headerTitle}</span>
			<Badge tone={statusTone}>
				{#if isRunning}
					<Spinner className="size-3" />
				{:else if isFailed}
					<XMark className="size-3" />
				{:else if isDone}
					<CheckCircle className="size-3" strokeWidth="2" />
				{/if}
				<span>{statusLabel}</span>
			</Badge>
		</div>
		<span class="agent-chevron" class:open>
			<ChevronDown className="size-3.5" />
		</span>
	</button>

	{#if open}
		<div transition:slide={{ duration: 180, easing: quintOut }}>
			<div class="agent-body">
				{#if parentTask}
					<div class="agent-section">
						<h4 class="agent-section-label">{$i18n.t('Instructions')}</h4>
						<div class="agent-instructions">{parentTask}</div>
					</div>
				{/if}

				{#if hasSubagents}
					<div class="agent-section">
						<h4 class="agent-section-label">{$i18n.t('Subagents')}</h4>
						<div class="agent-subagents">
							{#each subagents as sub, i}
								<div class="agent-subagent">
									<button
										class="agent-subagent-trigger"
										on:click={() => toggleSub(i)}
										type="button"
										aria-expanded={expandedSub[i]}
									>
										<span class="agent-subagent-task">
											{sub.task || $i18n.t('Subagent {{n}}', { n: i + 1 })}
										</span>
										<span class="agent-subagent-chevron" class:open={expandedSub[i]}>
											<ChevronDown className="size-3" />
										</span>
									</button>
									{#if expandedSub[i]}
										<div transition:slide={{ duration: 150, easing: quintOut }}>
											<div class="agent-subagent-body">
												{#if sub.result}
													<pre class="agent-subagent-result">{sub.result}</pre>
												{:else}
													<span class="agent-subagent-empty">{$i18n.t('No result')}</span>
												{/if}
											</div>
										</div>
									{/if}
								</div>
							{/each}
						</div>
					</div>
				{:else if isRunning}
					<div class="agent-section agent-section-pending">
						<span class="shimmer">{$i18n.t('Subagents working...')}</span>
					</div>
				{:else if isFailed && rawOutput}
					<div class="agent-section">
						<h4 class="agent-section-label error">{$i18n.t('Error')}</h4>
						<pre class="agent-error">{rawOutput}</pre>
					</div>
				{/if}
			</div>
		</div>
	{/if}
</div>

<style>
	.agent {
		border: 1px solid var(--myah-border);
		border-radius: var(--myah-radius-sm);
		overflow: hidden;
		background: transparent;
	}

	.agent-trigger {
		width: 100%;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		padding: 0.5rem 0.75rem;
		background: transparent;
		border: none;
		cursor: pointer;
		text-align: left;
		color: var(--myah-text);
		transition: background-color 150ms ease;
	}

	.agent-trigger:hover {
		background: color-mix(in srgb, var(--myah-text-secondary) 6%, transparent);
	}

	.agent-trigger-left {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		min-width: 0;
	}

	.agent-icon {
		color: var(--myah-text-muted);
		flex-shrink: 0;
	}

	.agent-title {
		font-size: 13px;
		font-weight: 500;
		color: var(--myah-text);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.agent-chevron {
		color: var(--myah-text-muted);
		flex-shrink: 0;
		transition: transform 200ms ease;
		display: inline-flex;
	}

	.agent-chevron.open {
		transform: rotate(180deg);
	}

	.agent-body {
		padding: 0.75rem;
		border-top: 1px solid var(--myah-border);
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.agent-section {
		display: flex;
		flex-direction: column;
		gap: 0.375rem;
	}

	.agent-section-pending {
		font-size: 12px;
		color: var(--myah-text-muted);
	}

	.agent-section-label {
		font-size: 10px;
		font-weight: 600;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--myah-text-muted);
		margin: 0;
	}

	.agent-section-label.error {
		color: var(--myah-accent-red);
	}

	.agent-instructions {
		background: color-mix(in srgb, var(--myah-text-secondary) 8%, transparent);
		color: var(--myah-text-secondary);
		padding: 0.625rem 0.75rem;
		border-radius: var(--myah-radius-sm);
		font-size: 13px;
		line-height: 1.55;
		white-space: pre-wrap;
		word-break: break-word;
	}

	.agent-subagents {
		display: flex;
		flex-direction: column;
		border: 1px solid var(--myah-border);
		border-radius: var(--myah-radius-sm);
		overflow: hidden;
	}

	.agent-subagent:not(:last-child) {
		border-bottom: 1px solid var(--myah-border);
	}

	.agent-subagent-trigger {
		width: 100%;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.5rem;
		padding: 0.5rem 0.75rem;
		background: transparent;
		border: none;
		cursor: pointer;
		text-align: left;
		color: var(--myah-text-secondary);
		font-size: 13px;
		transition: background-color 150ms ease;
	}

	.agent-subagent-trigger:hover {
		background: color-mix(in srgb, var(--myah-text-secondary) 6%, transparent);
	}

	.agent-subagent-task {
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.agent-subagent-chevron {
		display: inline-flex;
		color: var(--myah-text-muted);
		flex-shrink: 0;
		transition: transform 200ms ease;
	}

	.agent-subagent-chevron.open {
		transform: rotate(180deg);
	}

	.agent-subagent-body {
		padding: 0.5rem 0.75rem 0.75rem;
		border-top: 1px solid var(--myah-border);
	}

	.agent-subagent-result {
		font-family: 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', monospace;
		font-size: 12px;
		line-height: 1.5;
		color: var(--myah-text-secondary);
		white-space: pre-wrap;
		word-break: break-word;
		margin: 0;
		max-height: 240px;
		overflow-y: auto;
	}

	.agent-subagent-empty {
		font-size: 12px;
		color: var(--myah-text-muted);
		font-style: italic;
	}

	.agent-error {
		font-family: 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', monospace;
		font-size: 12px;
		line-height: 1.5;
		color: var(--myah-accent-red);
		background: color-mix(in srgb, var(--myah-accent-red) 10%, transparent);
		padding: 0.625rem 0.75rem;
		border-radius: var(--myah-radius-sm);
		white-space: pre-wrap;
		word-break: break-word;
		margin: 0;
		max-height: 240px;
		overflow-y: auto;
	}
</style>
