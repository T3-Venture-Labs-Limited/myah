<script lang="ts">
	export let steps: Array<{
		label: string;
		description?: string;
		status?: 'complete' | 'active' | 'pending';
	}> = [];
	export let current: number = -1; // fallback if status per step isn't provided
</script>

<div style="margin-bottom:14px">
	{#each steps as step, i}
		{@const isCompleted = step.status ? step.status === 'complete' : i < current}
		{@const isCurrent = step.status ? step.status === 'active' : i === current}
		{@const stepColor = isCompleted
			? 'var(--myah-accent-green)'
			: isCurrent
				? 'var(--myah-accent-blue)'
				: 'var(--myah-bg-input)'}
		{@const textColor = isCurrent || isCompleted ? 'var(--myah-text)' : 'var(--myah-text-muted)'}
		<div style="display:flex;align-items:flex-start;gap:10px;margin-bottom:10px">
			<div
				style="width:24px;height:24px;border-radius:50%;background:{stepColor};display:flex;align-items:center;justify-content:center;flex-shrink:0;font-size:11px;font-weight:700;color:{isCompleted ||
				isCurrent
					? '#000'
					: 'var(--myah-text-muted)'};margin-top:1px"
			>
				{#if isCompleted}
					✓
				{:else}
					{i + 1}
				{/if}
			</div>
			<div>
				<div style="font-size:13px;font-weight:{isCurrent ? '600' : '400'};color:{textColor}">
					{step.label}
				</div>
				{#if step.description}
					<div style="font-size:11px;color:var(--myah-text-muted);margin-top:2px">
						{step.description}
					</div>
				{/if}
			</div>
		</div>
		{#if i < steps.length - 1}
			<div
				style="width:1px;height:12px;background:{isCompleted
					? 'var(--myah-accent-green)'
					: 'var(--myah-border)'};margin-left:11px;margin-bottom:2px"
			></div>
		{/if}
	{/each}
</div>
