import type {
	OutputItem,
	FunctionCallItem,
	FunctionCallOutputItem
} from '$lib/components/chat/Messages/HermesOutputRenderer/types';

export type TodoStatus = 'pending' | 'in_progress' | 'completed' | 'cancelled';

export interface TodoPanelItem {
	id: string;
	content: string;
	status: TodoStatus;
}

export interface TodoPanelData {
	key: string;
	items: TodoPanelItem[];
	completed: number;
	total: number;
	complete: boolean;
}

function normalizeStatus(status: unknown): TodoStatus {
	const raw = String(status ?? 'pending').toLowerCase();
	if (['completed', 'complete', 'done', 'success'].includes(raw)) return 'completed';
	if (['in_progress', 'in-progress', 'running', 'active'].includes(raw)) return 'in_progress';
	if (['cancelled', 'canceled', 'skipped'].includes(raw)) return 'cancelled';
	return 'pending';
}

function todoTextFromResult(result: FunctionCallOutputItem): string | null {
	for (const part of result.output ?? []) {
		if (part?.type === 'input_text' && typeof part.text === 'string') return part.text;
	}
	return null;
}

function itemsFromPayload(payload: unknown): unknown[] | null {
	if (Array.isArray(payload)) return payload;
	if (payload && typeof payload === 'object') {
		const record = payload as Record<string, unknown>;
		if (Array.isArray(record.todos)) return record.todos;
		if (Array.isArray(record.items)) return record.items;
	}
	return null;
}

function normalizeItems(items: unknown[]): TodoPanelItem[] {
	return items
		.map((item, index) => {
			if (typeof item === 'string') {
				return { id: String(index), content: item, status: 'pending' as TodoStatus };
			}
			if (!item || typeof item !== 'object') return null;
			const record = item as Record<string, unknown>;
			const content = record.content ?? record.text ?? record.title ?? record.task;
			if (typeof content !== 'string' || content.trim() === '') return null;
			return {
				id: String(record.id ?? index),
				content,
				status: normalizeStatus(record.status)
			};
		})
		.filter((item): item is TodoPanelItem => Boolean(item));
}

function isTodoCall(item: OutputItem): item is FunctionCallItem {
	return item.type === 'function_call' && item.name === 'todo' && Boolean(item.call_id);
}

function isFunctionCallOutput(item: OutputItem): item is FunctionCallOutputItem {
	return item.type === 'function_call_output';
}

export function extractTodoListFromOutput(output: OutputItem[] | undefined | null): TodoPanelData | null {
	if (!Array.isArray(output)) return null;

	const todoCalls = output.filter(isTodoCall);
	for (const call of todoCalls.toReversed()) {
		const result = output.find(
			(item): item is FunctionCallOutputItem =>
				isFunctionCallOutput(item) && item.call_id === call.call_id
		);
		if (!result) continue;
		const text = todoTextFromResult(result);
		if (!text) continue;

		try {
			const payload = JSON.parse(text);
			const rawItems = itemsFromPayload(payload);
			if (!rawItems) continue;
			const items = normalizeItems(rawItems);
			if (items.length === 0) continue;
			const completed = items.filter((item) => item.status === 'completed').length;
			return {
				key: call.call_id,
				items,
				completed,
				total: items.length,
				complete: completed === items.length
			};
		} catch {
			continue;
		}
	}

	return null;
}

export function filterTodoToolOutput(output: OutputItem[] | undefined | null): OutputItem[] {
	if (!Array.isArray(output)) return [];
	const todoCallIds = new Set(output.filter(isTodoCall).map((item) => item.call_id));
	if (todoCallIds.size === 0) return output;
	return output.filter((item) => {
		if (isTodoCall(item)) return false;
		if (isFunctionCallOutput(item) && todoCallIds.has(item.call_id)) return false;
		return true;
	});
}
