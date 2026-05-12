<script lang="ts">
	export let label = '';
	export let variant: 'default' | 'success' | 'warning' | 'error' | 'info' = 'default';

	// Resolve background and text color from variant
	$: bg =
		variant === 'success'
			? 'color-mix(in srgb, var(--myah-accent-green) 20%, transparent)'
			: variant === 'error'
				? 'color-mix(in srgb, var(--myah-accent-red) 20%, transparent)'
				: variant === 'warning'
					? 'color-mix(in srgb, #f59e0b 20%, transparent)'
					: variant === 'info'
						? 'color-mix(in srgb, var(--myah-accent-blue) 20%, transparent)'
						: 'var(--myah-bg-input)';

	$: color =
		variant === 'success'
			? 'var(--myah-accent-green)'
			: variant === 'error'
				? 'var(--myah-accent-red)'
				: variant === 'warning'
					? '#f59e0b'
					: variant === 'info'
						? 'var(--myah-accent-blue)'
						: 'var(--myah-text-muted)';
</script>

<span
	style="display:inline-flex;align-items:center;padding:2px 8px;border-radius:99px;font-size:11px;font-weight:600;background:{bg};color:{color};letter-spacing:0.03em"
>
	{label}
</span>
