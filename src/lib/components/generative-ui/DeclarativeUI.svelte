<script lang="ts">
	import { createEventDispatcher, onMount } from 'svelte';
	import MetricsBlock from './MetricsBlock.svelte';
	import TableBlock from './TableBlock.svelte';
	import EntriesBlock from './EntriesBlock.svelte';
	import ActionsBlock from './ActionsBlock.svelte';
	import FormBlock from './FormBlock.svelte';
	import TextBlock from './TextBlock.svelte';
	import ChartBlock from './ChartBlock.svelte';
	import ImageBlock from './ImageBlock.svelte';
	import ColumnsBlock from './ColumnsBlock.svelte';
	import CardBlock from './CardBlock.svelte';
	import TabsBlock from './TabsBlock.svelte';
	import AccordionBlock from './AccordionBlock.svelte';
	import BadgeBlock from './BadgeBlock.svelte';
	import AvatarBlock from './AvatarBlock.svelte';
	import AlertBlock from './AlertBlock.svelte';
	import StepperBlock from './StepperBlock.svelte';
	import SparklineBlock from './SparklineBlock.svelte';
	import CarouselBlock from './CarouselBlock.svelte';
	import ToggleBlock from './ToggleBlock.svelte';

	export let spec: { title?: string; blocks: Array<Record<string, unknown>> } = { blocks: [] };
	export let messageId = '';
	export let componentId: string | undefined = undefined;

	const dispatch = createEventDispatcher();

	onMount(() => {
		if (spec.blocks.length > 0) {
			const blockTypes = spec.blocks.map((b) => b.type ?? 'unknown');
			console.debug('[render] DeclarativeUI mounted', {
				messageId,
				blockCount: spec.blocks.length,
				blockTypes
			});
		}
	});

	function handleInteraction(e: CustomEvent) {
		dispatch('ui-interaction', { ...e.detail, componentId });
	}
</script>

<div style="font-family:var(--myah-font);color:var(--myah-text)">
	{#if spec.title}
		<h2 style="font-size:15px;font-weight:600;margin-bottom:14px">{spec.title}</h2>
	{/if}
	{#each spec.blocks as block}
		{#if block.type === 'metrics'}
			<MetricsBlock items={block.items} />
		{:else if block.type === 'table'}
			<TableBlock columns={block.columns} rows={block.rows} />
		{:else if block.type === 'entries'}
			<EntriesBlock items={block.items} />
		{:else if block.type === 'actions'}
			<ActionsBlock
				items={block.items}
				{messageId}
				{componentId}
				on:ui-interaction={handleInteraction}
			/>
		{:else if block.type === 'form'}
			<FormBlock
				fields={block.fields}
				formId={block.id}
				submitLabel={block.submitLabel}
				submitAction={block.submitAction}
				{messageId}
				{componentId}
				on:ui-interaction={handleInteraction}
			/>
		{:else if block.type === 'text'}
			<TextBlock content={block.content} />
		{:else if block.type === 'chart'}
			<ChartBlock
				chartType={block.chartType}
				labels={block.labels}
				datasets={block.datasets}
				title={block.title}
				description={block.description}
			/>
		{:else if block.type === 'image'}
			<ImageBlock src={block.src} alt={block.alt} caption={block.caption} />
		{:else if block.type === 'divider'}
			<hr style="border:none;border-top:1px solid var(--myah-border);margin:12px 0" />
		{:else if block.type === 'columns'}
			<ColumnsBlock
				blocks={block.blocks}
				widths={block.widths}
				{messageId}
				on:ui-interaction={handleInteraction}
			/>
		{:else if block.type === 'card'}
			<CardBlock
				title={block.title}
				blocks={block.blocks}
				{messageId}
				on:ui-interaction={handleInteraction}
			/>
		{:else if block.type === 'tabs'}
			<TabsBlock tabs={block.tabs} {messageId} on:ui-interaction={handleInteraction} />
		{:else if block.type === 'accordion'}
			<AccordionBlock items={block.items} {messageId} on:ui-interaction={handleInteraction} />
		{:else if block.type === 'badge'}
			<BadgeBlock label={block.label} variant={block.variant} />
		{:else if block.type === 'avatar'}
			<AvatarBlock name={block.name} subtitle={block.subtitle} src={block.src} />
		{:else if block.type === 'alert'}
			<AlertBlock content={block.content} message={block.message} variant={block.variant} />
		{:else if block.type === 'stepper'}
			<StepperBlock steps={block.steps} current={block.current} />
		{:else if block.type === 'sparkline'}
			<SparklineBlock values={block.values} color={block.color} />
		{:else if block.type === 'carousel'}
			<CarouselBlock items={block.items} />
		{:else if block.type === 'toggle'}
			<ToggleBlock
				label={block.label}
				checked={block.checked}
				action={block.action}
				{messageId}
				on:ui-interaction={handleInteraction}
			/>
		{:else}
			<!-- Unknown block type: surface it rather than silently render nothing -->
			<div
				class="my-1 rounded border border-amber-300 bg-amber-50 p-2 text-xs text-amber-700 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-400"
			>
				Unknown block type: <code class="font-mono">{block.type ?? 'undefined'}</code>
			</div>
		{/if}
	{/each}
</div>
