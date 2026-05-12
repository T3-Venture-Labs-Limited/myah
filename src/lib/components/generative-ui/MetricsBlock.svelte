<script lang="ts">
	export let items: Array<{
		label: string;
		value: string;
		change?: string;
		trend?: 'up' | 'down' | 'flat';
	}> = [];
</script>

<div
	style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:14px"
>
	{#each items as m}
		{@const isUp = m.trend === 'up'}
		{@const isDown = m.trend === 'down'}
		{@const trendColor = isUp
			? 'var(--myah-accent-green)'
			: isDown
				? 'var(--myah-accent-red)'
				: 'var(--myah-text-muted)'}
		<div
			style="padding:14px 16px;background:var(--myah-bg-card);border:1px solid var(--myah-border);border-radius:var(--myah-radius)"
		>
			<div
				style="font-size:10px;font-weight:500;color:var(--myah-text-muted);text-transform:uppercase;letter-spacing:0.07em;margin-bottom:6px"
			>
				{m.label}
			</div>
			<div style="font-size:22px;font-weight:700;color:var(--myah-text);line-height:1.1">
				{m.value}
			</div>
			{#if m.change}
				<div
					style="display:flex;align-items:center;gap:3px;margin-top:5px;font-size:12px;font-weight:500;color:{trendColor}"
				>
					{#if isUp}▲{:else if isDown}▼{/if}
					{m.change}
				</div>
			{/if}
		</div>
	{/each}
</div>
