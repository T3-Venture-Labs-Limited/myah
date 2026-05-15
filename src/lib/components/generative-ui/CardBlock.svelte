<script lang="ts">
	import { createEventDispatcher } from 'svelte';
	import DeclarativeUI from './DeclarativeUI.svelte';

	export let title: string | undefined = undefined;
	export let blocks: Array<Record<string, unknown>> = [];
	export let messageId = '';

	const dispatch = createEventDispatcher();

	function handleInteraction(e: CustomEvent) {
		dispatch('ui-interaction', e.detail);
	}
</script>

<div
	style="background:var(--myah-bg-card);border-radius:var(--myah-radius);padding:14px;margin-bottom:12px;border:1px solid var(--myah-border)"
>
	{#if title}
		<div
			style="font-size:12px;font-weight:600;color:var(--myah-text-muted);text-transform:uppercase;letter-spacing:0.06em;margin-bottom:10px"
		>
			{title}
		</div>
	{/if}
	<DeclarativeUI spec={{ blocks }} {messageId} on:ui-interaction={handleInteraction} />
</div>
