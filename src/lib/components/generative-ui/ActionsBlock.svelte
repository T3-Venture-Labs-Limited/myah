<script lang="ts">
	import { createEventDispatcher } from 'svelte';

	type ActionItem = {
		label: string;
		action: string;
		payload?: Record<string, unknown>;
		variant?: 'primary' | 'secondary' | 'ghost';
	};

	export let items: Array<ActionItem | string> = [];
	export let messageId = '';
	export let componentId: string | undefined = undefined;

	const dispatch = createEventDispatcher();
	let chosenAction: string | null = null;

	$: normalizedItems = (Array.isArray(items) ? items : []).map(
		(it, i): ActionItem =>
			typeof it === 'string'
				? { label: it, action: it, variant: i === 0 ? 'primary' : 'secondary' }
				: (it as ActionItem)
	);

	function handleClick(item: ActionItem) {
		if (chosenAction) return;
		chosenAction = item.action;
		dispatch('ui-interaction', {
			type: 'TOOL_CALL_RESULT',
			toolCallId: messageId,
			componentId: componentId || '',
			action: item.action,
			label: item.label,
			result: {
				action: item.action,
				label: item.label,
				payload: item.payload || {},
				timestamp: Date.now()
			}
		});
	}
</script>

<div style="display:flex;gap:8px;margin:12px 0;flex-wrap:wrap">
	{#each normalizedItems as item}
		{@const isChosen = chosenAction === item.action}
		{@const isDisabled = chosenAction !== null}
		{@const bg = isChosen
			? 'var(--myah-accent-green)'
			: item.variant === 'primary'
				? 'var(--myah-accent-blue)'
				: item.variant === 'ghost'
					? 'transparent'
					: 'var(--myah-bg-card)'}
		{@const border =
			item.variant === 'ghost'
				? 'none'
				: item.variant === 'primary' || isChosen
					? 'none'
					: '1px solid var(--myah-border-input)'}
		{@const textColor = isChosen || item.variant === 'primary' ? '#000' : 'var(--myah-text)'}
		<button
			style="padding:8px 18px;border-radius:var(--myah-radius-sm);background:{bg};border:{border};color:{textColor};font-size:13px;font-weight:500;cursor:{isDisabled
				? 'default'
				: 'pointer'};opacity:{isDisabled && !isChosen
				? '0.35'
				: '1'};font-family:var(--myah-font);transition:all 0.15s"
			on:click={() => handleClick(item)}
			disabled={isDisabled}
		>
			{#if isChosen}
				✓ {item.label}
			{:else}
				{item.label}
			{/if}
		</button>
	{/each}
</div>
