<script lang="ts">
	import { cubicOut } from 'svelte/easing';
	import type { TransitionConfig } from 'svelte/transition';
	import type { TodoPlanItem } from '$lib/types/contract';

	export let plan: TodoPlanItem | null = null;
	export let initiallyExpanded = false;

	let expanded = initiallyExpanded;
	let lastPlanId = '';

	$: todos = plan?.todos ?? [];
	$: total = todos.length;
	$: done = todos.filter((todo) => todo.status === 'completed').length;
	$: activeIndex = todos.findIndex((todo) => todo.status === 'in_progress');
	$: active = activeIndex >= 0 ? todos[activeIndex] : null;
	$: nextPending = todos.find((todo) => todo.status === 'pending');
	$: currentStep = activeIndex >= 0 ? activeIndex + 1 : Math.min(done + 1, total);
	$: percent = total > 0 ? Math.round((done / total) * 100) : 0;
	$: statusText = active
		? `Working · step ${currentStep} of ${total}`
		: done === total
			? `Complete · ${done} of ${total}`
			: `Planned · ${done} of ${total}`;
	$: activeText = active?.content ?? nextPending?.content ?? 'All steps complete';

	$: if ((plan?.id ?? '') !== lastPlanId) {
		lastPlanId = plan?.id ?? '';
		expanded = initiallyExpanded;
	}

	function toggle() {
		expanded = !expanded;
	}

	function morphPanel(_node: Element, { duration = 260 } = {}): TransitionConfig {
		return {
			duration,
			easing: cubicOut,
			css: (t, u) => `
				opacity: ${t};
				transform: translateX(-50%) translateY(${u * -10}px) scale(${0.92 + t * 0.08});
				border-radius: ${999 - t * 981}px;
				clip-path: inset(${u * 42}% ${u * 26}% ${u * 42}% ${u * 26}% round ${18 + u * 999}px);
				filter: blur(${u * 2}px);
			`
		};
	}
</script>

{#if plan && total > 0}
	<section class="todo-plan-shell" class:expanded aria-label="Agent plan">
		<button
			type="button"
			class="todo-plan-island"
			aria-expanded={expanded}
			aria-label={expanded ? 'Collapse plan to current task pill' : 'Show plan steps'}
			on:click={toggle}
		>
			<span
				class="progress-ring"
				style={`--todo-plan-progress: ${percent * 3.6}deg`}
				aria-label={`${done} of ${total} plan steps complete`}
			>
				<span>{done}/{total}</span>
			</span>

			<span class="island-copy" aria-live="polite">
				<span class="status-line">{statusText}</span>
				<span class="task-line">{activeText}</span>
			</span>

			<span class="chevron" class:open={expanded} aria-hidden="true">›</span>
		</button>

		{#if expanded}
			<div
				class="todo-plan-panel"
				data-motion="dynamic-island-morph"
				transition:morphPanel={{ duration: 260 }}
			>
				<div class="panel-header">
					<div class="plan-title-wrap">
						<div class="plan-title">{plan.title || 'Plan'}</div>
						<div class="plan-summary">
							<span>{done} / {total}</span>
							<span>{active ? active.content : 'All steps complete'}</span>
						</div>
					</div>
					<button type="button" class="hide-button" aria-label="Hide plan steps" on:click={toggle}>
						Hide
					</button>
				</div>

				<div class="segments" aria-hidden="true">
					{#each todos as todo (todo.id)}
						<span data-testid="todo-plan-segment" class="segment" data-status={todo.status}></span>
					{/each}
				</div>

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
	.todo-plan-shell {
		position: relative;
		z-index: 40;
		width: min(620px, calc(100vw - 9rem));
		max-width: 100%;
		margin: 0 auto;
		padding: 2px 0;
		pointer-events: auto;
		flex-shrink: 1;
		min-width: 0;
		transition: width 260ms cubic-bezier(0.22, 1, 0.36, 1);
		will-change: width;
	}

	.todo-plan-shell.expanded {
		width: min(760px, calc(100vw - 9rem));
	}

	.todo-plan-island {
		width: 100%;
		min-width: 0;
		display: flex;
		align-items: center;
		gap: 12px;
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: 999px;
		padding: 7px 14px 7px 10px;
		background:
			linear-gradient(180deg, rgba(255, 255, 255, 0.05), rgba(255, 255, 255, 0.02)),
			var(--myah-bg-elev-2, #202020);
		box-shadow:
			0 12px 28px rgba(0, 0, 0, 0.22),
			inset 0 1px 0 rgba(255, 255, 255, 0.06);
		color: var(--myah-text-primary, #f3f3f3);
		cursor: pointer;
		transition:
			transform 220ms cubic-bezier(0.22, 1, 0.36, 1),
			border-color 180ms ease,
			background 180ms ease,
			box-shadow 220ms ease;
		will-change: transform;
		text-align: left;
	}

	.todo-plan-shell.expanded .todo-plan-island {
		transform: scale(0.985);
		border-color: color-mix(in srgb, var(--myah-accent, #ff3f86) 34%, rgba(255, 255, 255, 0.12));
		box-shadow:
			0 10px 24px rgba(0, 0, 0, 0.18),
			inset 0 1px 0 rgba(255, 255, 255, 0.07);
	}

	.todo-plan-island:hover {
		transform: translateY(-1px);
		border-color: color-mix(in srgb, var(--myah-accent, #ff3f86) 45%, rgba(255, 255, 255, 0.1));
		background:
			linear-gradient(180deg, rgba(255, 255, 255, 0.07), rgba(255, 255, 255, 0.03)),
			var(--myah-bg-elev-2, #202020);
	}

	.progress-ring {
		width: 34px;
		height: 34px;
		border-radius: 999px;
		background: conic-gradient(
			var(--myah-accent, #ff3f86) var(--todo-plan-progress),
			rgba(255, 255, 255, 0.16) 0deg
		);
		display: grid;
		place-items: center;
		font:
			800 10px ui-monospace,
			SFMono-Regular,
			monospace;
		color: var(--myah-text-primary, #f3f3f3);
		position: relative;
		flex-shrink: 0;
	}

	.progress-ring::after {
		content: '';
		position: absolute;
		inset: 4px;
		border-radius: 999px;
		background: var(--myah-bg-elev-1, #292929);
	}

	.progress-ring span {
		position: relative;
		z-index: 1;
	}

	.island-copy {
		display: flex;
		flex-direction: column;
		min-width: 0;
		flex: 1;
		line-height: 1.15;
	}

	.status-line {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 13.5px;
		font-weight: 750;
		letter-spacing: -0.01em;
		color: var(--myah-text-primary, #f3f3f3);
	}

	.task-line {
		margin-top: 3px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: 13px;
		font-weight: 450;
		color: var(--myah-text-muted, #a5a5a5);
	}

	.chevron {
		font-size: 28px;
		line-height: 1;
		color: var(--myah-text-muted, #a5a5a5);
		transition: transform 160ms ease;
		flex-shrink: 0;
	}

	.chevron.open {
		transform: rotate(90deg);
	}

	.todo-plan-panel {
		position: absolute;
		top: calc(100% + 8px);
		left: 50%;
		transform: translateX(-50%);
		transform-origin: top center;
		width: min(760px, calc(100vw - 9rem));
		max-height: min(52vh, 420px);
		overflow: auto;
		border: 1px solid rgba(255, 255, 255, 0.1);
		border-radius: 18px;
		background: color-mix(in srgb, var(--myah-bg-elev-1, #171717) 94%, transparent);
		box-shadow: 0 24px 70px rgba(0, 0, 0, 0.42);
		backdrop-filter: blur(18px);
		padding: 14px;
		will-change: opacity, transform, clip-path, border-radius, filter;
	}

	.panel-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 12px;
		margin-bottom: 12px;
	}

	.plan-title-wrap {
		min-width: 0;
	}

	.plan-title {
		font-size: 13.5px;
		font-weight: 750;
		color: var(--myah-text-primary, #f3f3f3);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.plan-summary {
		margin-top: 3px;
		display: flex;
		align-items: center;
		gap: 8px;
		min-width: 0;
		font-size: 12px;
		color: var(--myah-text-muted, #a5a5a5);
	}

	.plan-summary span:last-child {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.hide-button {
		border: 0;
		border-radius: 999px;
		padding: 6px 10px;
		background: rgba(255, 255, 255, 0.06);
		color: var(--myah-text-muted, #a5a5a5);
		font-size: 12px;
		font-weight: 650;
		cursor: pointer;
		flex-shrink: 0;
	}

	.hide-button:hover {
		background: color-mix(in srgb, var(--myah-accent, #ff3f86) 16%, rgba(255, 255, 255, 0.06));
		color: var(--myah-text-primary, #f3f3f3);
	}

	.segments {
		display: flex;
		align-items: center;
		gap: 4px;
		margin-bottom: 12px;
	}

	.segment {
		min-width: 10px;
		flex: 1;
		height: 5px;
		border-radius: 999px;
		background: rgba(255, 255, 255, 0.12);
	}

	.segment[data-status='completed'],
	.segment[data-status='in_progress'] {
		background: var(--myah-accent, #ff3f86);
	}

	.todo-list {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.todo-row {
		display: flex;
		align-items: center;
		gap: 11px;
		border-radius: 12px;
		padding: 8px 9px;
		font-size: 13px;
		color: var(--myah-text-primary, #f3f3f3);
	}

	.todo-row.active {
		background: color-mix(in srgb, var(--myah-accent, #ff3f86) 18%, transparent);
		font-weight: 650;
	}

	.todo-row.completed .content {
		color: var(--myah-text-muted, #a5a5a5);
		text-decoration: line-through;
		text-decoration-color: var(--myah-text-muted, #a5a5a5);
	}

	.todo-row.cancelled .content {
		color: var(--myah-text-muted, #a5a5a5);
	}

	.mark {
		width: 17px;
		height: 17px;
		border-radius: 999px;
		border: 2px solid rgba(255, 255, 255, 0.24);
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
		box-shadow: inset 0 0 0 4px var(--myah-bg-elev-1, #171717);
		background: var(--myah-accent, #ff3f86);
	}

	.mark[data-status='cancelled'] {
		border-color: #f5a524;
		color: #f5a524;
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
		font-weight: 700;
		color: #f5a524;
		white-space: nowrap;
	}

	:global(.dark) .todo-plan-island {
		background:
			linear-gradient(180deg, rgba(255, 255, 255, 0.06), rgba(255, 255, 255, 0.025)), #1f1f1f;
	}

	:global(.dark) .todo-plan-panel {
		background: rgba(18, 18, 18, 0.94);
	}

	:global(.dark) .progress-ring::after {
		background: #1f1f1f;
	}

	:global(.dark) .status-line,
	:global(.dark) .plan-title,
	:global(.dark) .todo-row {
		color: #f3f3f3;
	}

	:global(.dark) .task-line,
	:global(.dark) .chevron,
	:global(.dark) .plan-summary,
	:global(.dark) .hide-button,
	:global(.dark) .todo-row.completed .content,
	:global(.dark) .todo-row.cancelled .content {
		color: #a5a5a5;
	}

	:global(.dark) .mark[data-status='in_progress'] {
		box-shadow: inset 0 0 0 4px #121212;
	}

	.todo-plan-island:focus-visible,
	.hide-button:focus-visible {
		outline: 2px solid var(--myah-accent, #ff3f86);
		outline-offset: 3px;
	}

	.todo-plan-model-fallback {
		margin: 8px auto 0;
		display: flex;
		max-width: min(520px, 100%);
		justify-content: center;
		overflow: hidden;
	}

	@media (prefers-color-scheme: light) {
		.todo-plan-island {
			border-color: rgba(20, 20, 20, 0.08);
			background:
				linear-gradient(180deg, rgba(255, 255, 255, 0.9), rgba(250, 248, 246, 0.86)), #fbfaf8;
			color: var(--myah-text-primary, #26211d);
			box-shadow:
				0 10px 26px rgba(32, 26, 22, 0.12),
				inset 0 1px 0 rgba(255, 255, 255, 0.8);
		}

		.progress-ring {
			color: var(--myah-text-primary, #26211d);
			background: conic-gradient(
				var(--myah-accent, #ff3f86) var(--todo-plan-progress),
				#e9e5df 0deg
			);
		}

		.progress-ring::after {
			background: #fbfaf8;
		}

		.status-line,
		.plan-title,
		.todo-row {
			color: var(--myah-text-primary, #26211d);
		}

		.task-line,
		.chevron,
		.plan-summary,
		.hide-button {
			color: var(--myah-text-muted, #6f6862);
		}

		.todo-plan-panel {
			border-color: rgba(20, 20, 20, 0.08);
			background: rgba(251, 250, 248, 0.96);
			box-shadow: 0 24px 70px rgba(32, 26, 22, 0.18);
		}

		.hide-button {
			background: rgba(20, 20, 20, 0.05);
		}

		.segment {
			background: rgba(20, 20, 20, 0.1);
		}

		.mark {
			border-color: rgba(20, 20, 20, 0.22);
		}

		.mark[data-status='in_progress'] {
			box-shadow: inset 0 0 0 4px #fbfaf8;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.todo-plan-shell,
		.todo-plan-island,
		.chevron {
			transition-duration: 1ms;
		}
	}

	@media (max-width: 720px) {
		.todo-plan-shell,
		.todo-plan-shell.expanded {
			width: min(100%, calc(100vw - 5.5rem));
		}

		.todo-plan-panel {
			width: min(100vw - 1.5rem, 640px);
		}

		.status-line,
		.task-line {
			font-size: 12.5px;
		}
	}
</style>
