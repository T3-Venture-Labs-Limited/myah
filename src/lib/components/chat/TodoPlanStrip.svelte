<script lang="ts">
	import type { TodoPlanItem } from '$lib/types/contract';

	export let plan: TodoPlanItem | null = null;
	export let initiallyExpanded = true;

	let expanded = initiallyExpanded;
	let lastPlanId = '';

	$: todos = plan?.todos ?? [];
	$: total = todos.length;
	$: done = todos.filter((todo) => todo.status === 'completed').length;
	$: active = todos.find((todo) => todo.status === 'in_progress') ?? null;
	$: percent = total > 0 ? Math.round((done / total) * 100) : 0;
	$: if ((plan?.id ?? '') !== lastPlanId) {
		lastPlanId = plan?.id ?? '';
		expanded = initiallyExpanded;
	}

	function toggle() {
		expanded = !expanded;
	}
</script>

{#if plan && total > 0}
	<section class="todo-plan-strip" aria-label="Agent plan">
		<div class="todo-plan-header">
			<div
				class="progress-ring"
				style={`--todo-plan-progress: ${percent * 3.6}deg`}
				aria-label={`${done} of ${total} plan steps complete`}
			>
				<span>{done}/{total}</span>
			</div>

			<div class="plan-title">{plan.title || 'Plan'}</div>

			<div class="segments" aria-hidden="true">
				{#each todos as todo (todo.id)}
					<span data-testid="todo-plan-segment" class="segment" data-status={todo.status}></span>
				{/each}
			</div>

			<div class="divider" aria-hidden="true"></div>

			<div class="active-label">
				{#if active}
					{active.content}
				{:else}
					All steps complete
				{/if}
			</div>

			<div class="count">{done}/{total}</div>

			<button
				type="button"
				class="toggle"
				aria-expanded={expanded}
				aria-label={expanded ? 'Hide plan steps' : 'Show plan steps'}
				on:click={toggle}
			>
				{expanded ? 'Hide' : 'Steps'}
				<span class:open={expanded}>⌄</span>
			</button>
		</div>

		{#if expanded}
			<div class="todo-plan-dropdown">
				<div role="list" aria-label="Plan steps" class="todo-list">
					{#each todos as todo (todo.id)}
						<div
							role="listitem"
							class="todo-row"
							class:active={todo.status === 'in_progress'}
							class:completed={todo.status === 'completed'}
							class:cancelled={todo.status === 'cancelled'}
							data-testid={`todo-plan-row-${todo.id}`}
							data-status={todo.status}
							data-active={todo.status === 'in_progress' ? 'true' : undefined}
						>
							<span class="mark" data-status={todo.status} aria-hidden="true">
								{#if todo.status === 'completed'}✓{:else if todo.status === 'cancelled'}!{/if}
							</span>
							<span class="content">{todo.content}</span>
							{#if todo.status === 'in_progress'}
								<span class="working">Working</span>
							{/if}
						</div>
					{/each}
				</div>
			</div>
		{/if}
	</section>
{/if}

<style>
	.todo-plan-strip {
		flex-shrink: 0;
		width: 100%;
		border-bottom: 1px solid var(--myah-border, #e8e2dc);
		background: var(--myah-bg-elev-2, #fbfaf8);
		z-index: 5;
	}

	.todo-plan-header {
		display: flex;
		align-items: center;
		gap: 12px;
		min-height: 38px;
		padding: 7px 16px;
	}

	.progress-ring {
		width: 24px;
		height: 24px;
		border-radius: 999px;
		background: conic-gradient(var(--myah-accent, #ff3f86) var(--todo-plan-progress), var(--myah-bg-inset, #eeeae5) 0deg);
		display: grid;
		place-items: center;
		font: 700 8.5px ui-monospace, SFMono-Regular, monospace;
		color: var(--myah-text-secondary, #534d48);
		position: relative;
		flex-shrink: 0;
	}

	.progress-ring::after {
		content: '';
		position: absolute;
		inset: 3px;
		border-radius: 999px;
		background: var(--myah-bg-elev-2, #fbfaf8);
	}

	.progress-ring span {
		position: relative;
		z-index: 1;
	}

	.plan-title {
		font-size: 12.5px;
		font-weight: 650;
		color: var(--myah-text-primary, #26211d);
		white-space: nowrap;
	}

	.segments {
		display: flex;
		align-items: center;
		gap: 4px;
		flex-shrink: 0;
	}

	.segment {
		width: 12px;
		height: 4px;
		border-radius: 999px;
		background: var(--myah-bg-inset, #e6e1dc);
	}

	.segment[data-status='completed'],
	.segment[data-status='in_progress'] {
		background: var(--myah-accent, #ff3f86);
	}

	.divider {
		width: 1px;
		height: 16px;
		background: var(--myah-border, #e8e2dc);
		flex-shrink: 0;
	}

	.active-label {
		min-width: 0;
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 12.5px;
		font-weight: 500;
		color: var(--myah-text-secondary, #534d48);
	}

	.count,
	.toggle {
		font-size: 11px;
		color: var(--myah-text-muted, #8d8580);
		white-space: nowrap;
	}

	.count {
		font-family: ui-monospace, SFMono-Regular, monospace;
	}

	.toggle {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		border: 0;
		background: transparent;
		border-radius: 6px;
		padding: 4px 8px;
		cursor: pointer;
	}

	.toggle:hover {
		background: color-mix(in srgb, var(--myah-accent, #ff3f86) 8%, transparent);
	}

	.toggle span {
		transition: transform 150ms ease;
	}

	.toggle span.open {
		transform: rotate(180deg);
	}

	.todo-plan-dropdown {
		border-top: 1px solid var(--myah-border-inset, #eee8e1);
		background: var(--myah-bg-elev-1, #fffdfb);
		padding: 5px 8px 7px;
	}

	.todo-list {
		display: flex;
		flex-direction: column;
		gap: 1px;
	}

	.todo-row {
		display: flex;
		align-items: center;
		gap: 11px;
		border-radius: 8px;
		padding: 7px 8px;
		font-size: 12.5px;
		color: var(--myah-text-primary, #26211d);
	}

	.todo-row.active {
		background: color-mix(in srgb, var(--myah-accent, #ff3f86) 12%, transparent);
		font-weight: 650;
	}

	.todo-row.completed .content {
		color: var(--myah-text-muted, #8d8580);
		text-decoration: line-through;
		text-decoration-color: var(--myah-text-muted, #8d8580);
	}

	.todo-row.cancelled .content {
		color: var(--myah-text-muted, #8d8580);
	}

	.mark {
		width: 16px;
		height: 16px;
		border-radius: 999px;
		border: 2px solid var(--myah-border-strong, #d8d0c8);
		flex-shrink: 0;
		display: grid;
		place-items: center;
		font-size: 10px;
		line-height: 1;
	}

	.mark[data-status='completed'] {
		background: var(--myah-accent, #ff3f86);
		border-color: var(--myah-accent, #ff3f86);
		color: white;
	}

	.mark[data-status='in_progress'] {
		border-color: var(--myah-accent, #ff3f86);
		box-shadow: inset 0 0 0 4px var(--myah-bg-elev-1, #fffdfb);
		background: var(--myah-accent, #ff3f86);
	}

	.mark[data-status='cancelled'] {
		border-color: #f5a524;
		color: #b7791f;
		background: #f5a52422;
	}

	.content {
		min-width: 0;
		flex: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.working {
		font-size: 11px;
		font-weight: 650;
		color: #b7791f;
		white-space: nowrap;
	}
</style>
