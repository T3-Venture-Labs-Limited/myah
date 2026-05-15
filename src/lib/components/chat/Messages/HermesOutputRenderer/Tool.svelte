<script lang="ts">
	import { getContext } from 'svelte';
	import { slide } from 'svelte/transition';
	import { quintOut } from 'svelte/easing';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';

	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import Wrench from '$lib/components/icons/Wrench.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import CheckCircle from '$lib/components/icons/CheckCircle.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';

	import Badge from './Badge.svelte';
	import type { FunctionCallItem, FunctionCallOutputItem } from './types';
	import { getToolLabel } from './toolLabels';
	import { unwrapJSON } from './tool-cards/unwrapJSON';

	const i18n: Writable<i18nType> = getContext('i18n');

	export let call: FunctionCallItem;
	export let result: FunctionCallOutputItem | null = null;
	export let messageDone: boolean = true;
	export let defaultOpen: boolean = false;

	let open = defaultOpen;

	$: isRunning = call.status === 'in_progress' && !messageDone;
	$: isFailed = call.status === 'failed';
	$: isDone = call.status === 'completed' && result !== null;

	$: toolLabel = getToolLabel(call.name);

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

	// Input — parse args and pretty-print if object-like.
	$: parsedInput = (() => {
		const raw = call.arguments ?? '';
		if (!raw.trim()) return null;
		try {
			const v = JSON.parse(raw);
			return typeof v === 'object' && v !== null ? v : null;
		} catch {
			return null;
		}
	})();

	$: inputJson = parsedInput ? JSON.stringify(parsedInput, null, 2) : '';

	// Output — concatenate result parts, optionally unwrap JSON.
	$: rawOutput = result?.output?.map((p) => p.text ?? '').join('') ?? '';
	$: parsedOutput = rawOutput ? unwrapJSON(rawOutput) : null;
	$: outputText = (() => {
		if (!rawOutput) return '';
		if (typeof parsedOutput === 'string') return parsedOutput;
		if (parsedOutput === null || parsedOutput === undefined) return rawOutput;
		try {
			return JSON.stringify(parsedOutput, null, 2);
		} catch {
			return rawOutput;
		}
	})();

	$: hasInput = parsedInput != null && Object.keys(parsedInput).length > 0;
	$: hasOutput = outputText.length > 0;
	$: outputTone = isFailed ? 'error' : 'default';

	function toggle() {
		open = !open;
	}
</script>

<div class="tool">
	<button
		class="tool-trigger"
		on:click={toggle}
		type="button"
		aria-expanded={open}
	>
		<div class="tool-trigger-left">
			<span class="tool-icon">
				<Wrench className="size-3.5" />
			</span>
			<span class="tool-title">{toolLabel.label}</span>
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
		<span class="tool-chevron" class:open>
			<ChevronDown className="size-3.5" />
		</span>
	</button>

	{#if open}
		<div transition:slide={{ duration: 180, easing: quintOut }}>
			<div class="tool-body">
				{#if hasInput}
					<div class="tool-section">
						<h4 class="tool-section-label">{$i18n.t('Parameters')}</h4>
						<pre class="tool-code">{inputJson}</pre>
					</div>
				{/if}
				{#if hasOutput}
					<div class="tool-section">
						<h4 class="tool-section-label" class:error={outputTone === 'error'}>
							{outputTone === 'error' ? $i18n.t('Error') : $i18n.t('Result')}
						</h4>
						<pre class="tool-code" class:error={outputTone === 'error'}>{outputText}</pre>
					</div>
				{/if}
				{#if !hasInput && !hasOutput && isRunning}
					<div class="tool-section tool-section-empty">
						<span class="shimmer">{$i18n.t('Working...')}</span>
					</div>
				{/if}
			</div>
		</div>
	{/if}
</div>

<style>
	.tool {
		border: 1px solid var(--myah-border);
		border-radius: var(--myah-radius-sm);
		overflow: hidden;
		background: transparent;
	}

	.tool-trigger {
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

	.tool-trigger:hover {
		background: color-mix(in srgb, var(--myah-text-secondary) 6%, transparent);
	}

	.tool-trigger-left {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		min-width: 0;
	}

	.tool-icon {
		color: var(--myah-text-muted);
		flex-shrink: 0;
	}

	.tool-title {
		font-size: 13px;
		font-weight: 500;
		color: var(--myah-text);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.tool-chevron {
		color: var(--myah-text-muted);
		flex-shrink: 0;
		transition: transform 200ms ease;
		display: inline-flex;
	}

	.tool-chevron.open {
		transform: rotate(180deg);
	}

	.tool-body {
		padding: 0.75rem;
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		border-top: 1px solid var(--myah-border);
	}

	.tool-section {
		display: flex;
		flex-direction: column;
		gap: 0.375rem;
	}

	.tool-section-empty {
		padding: 0.25rem 0;
		font-size: 12px;
		color: var(--myah-text-muted);
	}

	.tool-section-label {
		font-size: 10px;
		font-weight: 600;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--myah-text-muted);
		margin: 0;
	}

	.tool-section-label.error {
		color: var(--myah-accent-red);
	}

	.tool-code {
		font-family: 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', monospace;
		font-size: 12px;
		line-height: 1.5;
		color: var(--myah-text-secondary);
		background: color-mix(in srgb, var(--myah-text-secondary) 8%, transparent);
		border-radius: var(--myah-radius-sm);
		padding: 0.625rem 0.75rem;
		margin: 0;
		overflow-x: auto;
		white-space: pre-wrap;
		word-break: break-word;
		max-height: 320px;
		overflow-y: auto;
	}

	.tool-code.error {
		color: var(--myah-accent-red);
		background: color-mix(in srgb, var(--myah-accent-red) 10%, transparent);
	}
</style>
