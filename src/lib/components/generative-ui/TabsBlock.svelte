<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import DeclarativeUI from './DeclarativeUI.svelte';

	export let tabs: Array<{ label: string; blocks: Array<Record<string, unknown>> }> = [];
	export let messageId = '';

	const dispatch = createEventDispatcher();

	let activeIndex = 0;

	function handleInteraction(e: CustomEvent) {
		dispatch('ui-interaction', e.detail);
	}
</script>

<div style="margin-bottom:12px">
	<!-- Tab bar -->
	<div style="display:flex;gap:0;border-bottom:1px solid var(--myah-border);margin-bottom:12px">
		{#each tabs as tab, i}
			{@const isActive = i === activeIndex}
			<button
				style="padding:7px 14px;font-size:13px;font-weight:{isActive
					? '600'
					: '400'};color:{isActive
					? 'var(--myah-text)'
					: 'var(--myah-text-muted)'};background:transparent;border:none;border-bottom:2px solid {isActive
					? 'var(--myah-accent-blue)'
					: 'transparent'};cursor:pointer;font-family:var(--myah-font);margin-bottom:-1px"
				on:click={() => (activeIndex = i)}
			>
				{tab.label}
			</button>
		{/each}
	</div>
	<!-- Active tab content -->
	{#if tabs[activeIndex]}
		<DeclarativeUI
			spec={{ blocks: tabs[activeIndex].blocks }}
			{messageId}
			on:ui-interaction={handleInteraction}
		/>
	{/if}
</div>
