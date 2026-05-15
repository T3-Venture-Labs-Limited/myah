<script lang="ts">
	import { getContext, onDestroy } from 'svelte';
	import { slide } from 'svelte/transition';
	import { quintOut } from 'svelte/easing';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';

	import Brain from '$lib/components/icons/Brain.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';

	import type { ReasoningItem } from './types';
	import { scheduleRender } from '$lib/utils/rafScheduler';

	const i18n: Writable<i18nType> = getContext('i18n');

	export let item: ReasoningItem;
	export let messageId: string = '';
	export let messageDone: boolean = true;

	// Single source of truth for collapsed state. Effects below flip it on
	// streaming start (auto-open) and 1s after streaming ends (auto-close),
	// unless the user has already interacted.
	let open = false;
	let userInteracted = false;
	let hasAutoClosed = false;
	let prevStreaming = false;
	let closeTimer: ReturnType<typeof setTimeout> | null = null;

	$: isStreaming = item.status === 'in_progress' && !messageDone;
	$: duration = item.duration ?? 0;

	// Auto-open on rising edge of isStreaming (if user hasn't acted).
	$: {
		if (isStreaming !== prevStreaming) {
			if (isStreaming && !userInteracted) {
				open = true;
			}
			prevStreaming = isStreaming;
		}
	}

	// Auto-close 1s after streaming ends, once only.
	$: if (!isStreaming && !userInteracted && !hasAutoClosed && closeTimer === null) {
		closeTimer = setTimeout(() => {
			if (!userInteracted) open = false;
			hasAutoClosed = true;
			closeTimer = null;
		}, 1000);
	}

	onDestroy(() => {
		if (closeTimer !== null) clearTimeout(closeTimer);
	});

	$: label = (() => {
		if (isStreaming) return $i18n.t('Thinking...');
		if (duration === 0) return $i18n.t('Thought for a few seconds');
		if (duration < 1) return $i18n.t('Thought for less than a second');
		if (duration < 60) return $i18n.t('Thought for {{count}} seconds', { count: Math.round(duration) });
		const mins = Math.floor(duration / 60);
		const secs = Math.round(duration % 60);
		return $i18n.t('Thought for {{mins}}m {{secs}}s', { mins, secs });
	})();

	// Strip status-only noise that Hermes emits as reasoning summary text
	// (lifecycle updates like "Agent ready", not real chain-of-thought).
	const STATUS_NOISE = /^(\s*[-•*]\s*)?(agent\s+ready|thinking\.{0,3}|processing\.{0,3})\s*$/i;

	let reasoningText = '';

	$: {
		const summarySnapshot = item.summary;
		const itemId = item.id;
		scheduleRender(`reasoning-${itemId}`, () => {
			const raw = summarySnapshot?.map((p) => p.text).join('').trim() ?? '';
			const lines = raw.split('\n').filter((line) => !STATUS_NOISE.test(line.trim()));
			reasoningText = lines.join('\n').trim();
		});
	}

	$: hasContent = reasoningText.length > 0;

	function toggle() {
		if (!hasContent) return;
		userInteracted = true;
		open = !open;
	}
</script>

<div class="reasoning">
	<button
		class="reasoning-trigger"
		on:click={toggle}
		disabled={!hasContent}
		type="button"
		aria-expanded={open}
	>
		<span class="reasoning-icon"><Brain className="size-4" /></span>
		<span class="reasoning-label" class:shimmer={isStreaming}>{label}</span>
		{#if hasContent}
			<span class="reasoning-chevron" class:open>
				<ChevronDown className="size-3.5" />
			</span>
		{/if}
	</button>

	{#if open && hasContent}
		<div transition:slide={{ duration: 180, easing: quintOut }}>
			<div class="reasoning-body">
				<Markdown id="{messageId}-reasoning-{item.id}" content={reasoningText} />
			</div>
		</div>
	{/if}
</div>

<style>
	.reasoning {
		width: 100%;
	}

	.reasoning-trigger {
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

	.reasoning-trigger:not(:disabled):hover {
		color: var(--myah-text-secondary);
	}

	.reasoning-trigger:disabled {
		cursor: default;
	}

	.reasoning-icon {
		flex-shrink: 0;
	}

	.reasoning-label {
		flex: 1;
		text-align: left;
	}

	.reasoning-chevron {
		display: inline-flex;
		transition: transform 200ms ease;
	}

	.reasoning-chevron.open {
		transform: rotate(180deg);
	}

	.reasoning-body {
		margin-top: 0.5rem;
		padding-left: 1.5rem;
		font-size: 13px;
		color: var(--myah-text-muted);
		line-height: 1.55;
	}
</style>
