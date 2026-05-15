<script lang="ts">
	// Shadcn-modeled: icon on left with absolute vertical line below connecting to next step.
	// Content on right: label + optional children (rendered via slot).
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	export let icon: any = null;
	export let status: 'complete' | 'active' | 'pending' = 'complete';
	export let isLast: boolean = false;
</script>

<div class="step step-{status}">
	<div class="step-icon-col">
		{#if icon}
			<svelte:component this={icon} className="size-4" />
		{:else}
			<span class="step-dot" aria-hidden="true"></span>
		{/if}
		{#if !isLast}
			<span class="step-line" aria-hidden="true"></span>
		{/if}
	</div>
	<div class="step-content">
		<slot />
	</div>
</div>

<style>
	.step {
		display: flex;
		gap: 0.5rem;
		font-size: 13px;
		line-height: 1.55;
	}

	.step-complete { color: var(--myah-text-secondary); }
	.step-active { color: var(--myah-text); }
	.step-pending { color: color-mix(in srgb, var(--myah-text-muted) 60%, transparent); }

	.step-icon-col {
		position: relative;
		margin-top: 0.125rem;
		display: flex;
		justify-content: center;
		flex-shrink: 0;
		width: 1rem;
		color: var(--myah-text-muted);
	}

	.step-active .step-icon-col {
		color: var(--myah-text);
	}

	.step-dot {
		width: 0.5rem;
		height: 0.5rem;
		border-radius: 9999px;
		background: currentColor;
		margin-top: 0.25rem;
	}

	.step-line {
		position: absolute;
		top: 1.75rem;
		bottom: -0.5rem;
		left: 50%;
		width: 1px;
		margin-left: -0.5px;
		background: var(--myah-border);
	}

	.step-content {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 0.375rem;
		padding-bottom: 0.75rem;
	}
</style>
