import type { TodoPlanItem } from '$lib/types/contract';

type MessageLike = {
	id?: string;
	role?: string;
	done?: boolean;
	output?: unknown;
};

type HistoryLike = {
	currentId?: string | null;
	messages?: Record<string, MessageLike | undefined>;
};

function isTodoPlanItem(item: unknown): item is TodoPlanItem {
	return Boolean(
		item &&
		typeof item === 'object' &&
		(item as { type?: unknown }).type === 'todo_plan' &&
		Array.isArray((item as { todos?: unknown }).todos)
	);
}

function shouldShowPlan(plan: TodoPlanItem, message: MessageLike): boolean {
	const hasOpenStep = plan.todos.some(
		(todo) => todo.status === 'pending' || todo.status === 'in_progress'
	);
	return hasOpenStep || message.done !== true;
}

export function getPinnedTodoPlan(history: HistoryLike | null | undefined): TodoPlanItem | null {
	if (!history?.currentId || !history.messages) return null;
	const message = history.messages[history.currentId];
	if (!message || message.role !== 'assistant' || !Array.isArray(message.output)) return null;

	for (let i = message.output.length - 1; i >= 0; i -= 1) {
		const item = message.output[i];
		if (isTodoPlanItem(item)) {
			return shouldShowPlan(item, message) ? item : null;
		}
	}

	return null;
}
