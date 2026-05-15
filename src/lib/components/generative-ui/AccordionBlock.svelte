<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import DeclarativeUI from './DeclarativeUI.svelte';

	export let items: Array<{
		label: string;
		blocks: Array<Record<string, unknown>>;
		open?: boolean;
	}> = [];
	export let messageId = '';

	const dispatch = createEventDispatcher();

	// Track open state per item, initialised from the `open` prop
	$: openStates = items.map((item) => item.open ?? false);

	function toggle(i: number) {
		openStates[i] = !openStates[i];
	}

	function handleInteraction(e: CustomEvent) {
		dispatch('ui-interaction', e.detail);
	}
</script>

<div style="margin-bottom:12px">
	{#each items as item, i}
		<div
			style="border:1px solid var(--myah-border);border-radius:var(--myah-radius);margin-bottom:6px;overflow:hidden"
		>
			<button
				style="width:100%;display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:var(--myah-bg-card);border:none;color:var(--myah-text);font-size:13px;font-weight:500;cursor:pointer;font-family:var(--myah-font);text-align:left"
				on:click={() => toggle(i)}
			>
				<span>{item.label}</span>
				<span style="font-size:11px;color:var(--myah-text-muted)">{openStates[i] ? '▲' : '▼'}</span>
			</button>
			{#if openStates[i]}
				<div style="padding:10px 14px;border-top:1px solid var(--myah-border)">
					<DeclarativeUI
						spec={{ blocks: item.blocks }}
						{messageId}
						on:ui-interaction={handleInteraction}
					/>
				</div>
			{/if}
		</div>
	{/each}
</div>
