<script lang="ts">
	// A small rounded status pill. Mirrors the shadcn <Badge variant="secondary"> pattern
	// used across the AI-element reference components: rounded-full, muted bg, inline-flex
	// with small gap for an optional leading icon.
	export let tone: 'neutral' | 'success' | 'running' | 'error' | 'warning' = 'neutral';
</script>

<span class="badge badge-{tone}">
	<slot />
</span>

<style>
	.badge {
		display: inline-flex;
		align-items: center;
		gap: 0.375rem;
		padding: 0.125rem 0.5rem;
		border-radius: 9999px;
		font-size: 11px;
		line-height: 1.2;
		font-weight: 500;
		white-space: nowrap;
		background: color-mix(in srgb, var(--myah-text-secondary) 12%, transparent);
		color: var(--myah-text-secondary);
	}

	.badge-success {
		background: color-mix(in srgb, var(--myah-accent-green) 14%, transparent);
		color: var(--myah-accent-green);
	}

	.badge-running {
		background: color-mix(in srgb, var(--myah-accent-blue) 14%, transparent);
		color: var(--myah-accent-blue);
	}

	.badge-error {
		background: color-mix(in srgb, var(--myah-accent-red) 14%, transparent);
		color: var(--myah-accent-red);
	}

	.badge-warning {
		background: color-mix(in srgb, var(--myah-accent-amber) 14%, transparent);
		color: var(--myah-accent-amber);
	}
</style>
