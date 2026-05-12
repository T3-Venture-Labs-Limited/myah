<script lang="ts">
	export let content = '';
	export let message = ''; // alias — SOUL.md uses 'message', blocks spec uses 'content'
	export let variant: 'info' | 'warning' | 'error' | 'success' = 'info';

	$: text = content || message;

	$: borderColor =
		variant === 'error'
			? 'var(--myah-accent-red)'
			: variant === 'success'
				? 'var(--myah-accent-green)'
				: variant === 'warning'
					? '#f59e0b'
					: 'var(--myah-accent-blue)';

	$: bg =
		variant === 'error'
			? 'color-mix(in srgb, var(--myah-accent-red) 10%, transparent)'
			: variant === 'success'
				? 'color-mix(in srgb, var(--myah-accent-green) 10%, transparent)'
				: variant === 'warning'
					? 'color-mix(in srgb, #f59e0b 10%, transparent)'
					: 'color-mix(in srgb, var(--myah-accent-blue) 10%, transparent)';
</script>

<div
	style="border-left:3px solid {borderColor};background:{bg};padding:10px 14px;border-radius:0 var(--myah-radius-sm) var(--myah-radius-sm) 0;margin-bottom:10px;font-size:13px;color:var(--myah-text)"
>
	{text}
</div>
