<script lang="ts">
	// Supports both legacy {action,detail,time,status} and new {label,value,description,status} formats
	export let items: Array<Record<string, unknown>> = [];

	$: safeItems = Array.isArray(items) ? items : [];
</script>

<div
	style="background:var(--myah-bg-card);border-radius:var(--myah-radius);padding:4px 14px;margin-bottom:12px"
>
	{#each safeItems as e}
		{@const statusStr = String(e.status ?? '')}
		{@const statusColor =
			statusStr === 'ok' || statusStr === 'completed' || statusStr === 'done'
				? 'var(--myah-accent-green)'
				: statusStr === 'error' || statusStr === 'failed'
					? 'var(--myah-accent-red)'
					: statusStr === 'pending' || statusStr === 'in_progress'
						? '#f59e0b'
						: 'var(--myah-text-muted)'}
		{@const primaryText = String(e.label ?? e.action ?? '')}
		{@const secondaryText = String(e.description ?? e.detail ?? '')}
		{@const sideText = String(e.value ?? e.time ?? '')}
		<div
			style="display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid var(--myah-border)"
		>
			<div
				style="width:6px;height:6px;border-radius:50%;background:{statusColor};flex-shrink:0"
			></div>
			<div style="flex:1;min-width:0">
				<div style="font-size:13px;color:var(--myah-text)">{primaryText}</div>
				{#if secondaryText}
					<div style="font-size:11px;color:var(--myah-text-muted);margin-top:2px">
						{secondaryText}
					</div>
				{/if}
			</div>
			{#if sideText}
				<div style="font-size:11px;color:var(--myah-text-muted);flex-shrink:0">{sideText}</div>
			{/if}
		</div>
	{/each}
</div>
