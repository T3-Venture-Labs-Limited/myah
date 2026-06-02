import { describe, it, expect } from 'vitest';
import { groupChronologically } from './groupChronologically';
import type {
	MessageItem,
	FunctionCallItem,
	FunctionCallOutputItem,
	ReasoningItem,
	CodeInterpreterItem,
	ConfirmationItem,
	SecretInputItem,
	ClarifyInputItem,
	ArtifactCardItem,
	TodoPlanItem
} from './types';
// ── Helpers ──────────────────────────────────────────────────────────────────

let _id = 0;
function uid() {
	return `id-${++_id}`;
}

function msg(overrides?: Partial<MessageItem>): MessageItem {
	return {
		type: 'message',
		id: uid(),
		status: 'completed',
		role: 'assistant',
		content: [],
		...overrides
	};
}

function reasoning(overrides?: Partial<ReasoningItem>): ReasoningItem {
	return {
		type: 'reasoning',
		id: uid(),
		status: 'completed',
		summary: [{ type: 'summary_text', text: 'some reasoning text' }],
		...overrides
	};
}

function tool(overrides?: Partial<FunctionCallItem>): FunctionCallItem {
	return {
		type: 'function_call',
		id: uid(),
		call_id: uid(),
		name: 'some_tool',
		arguments: '{}',
		status: 'completed',
		...overrides
	};
}

function toolOutput(callId: string, overrides?: Partial<FunctionCallOutputItem>): FunctionCallOutputItem {
	return {
		type: 'function_call_output',
		id: uid(),
		call_id: callId,
		output: [],
		status: 'completed',
		...overrides
	};
}

function codeInterp(overrides?: Partial<CodeInterpreterItem>): CodeInterpreterItem {
	return {
		type: 'myah:code_interpreter',
		id: uid(),
		code: 'print("hi")',
		lang: 'python',
		status: 'completed',
		...overrides
	};
}

function confirmation(overrides?: Partial<ConfirmationItem>): ConfirmationItem {
	return {
		type: 'confirmation',
		id: uid(),
		confirmation_id: uid(),
		run_id: uid(),
		action_type: 'exec',
		description: 'Run something?',
		options: ['yes', 'no'],
		metadata: {},
		status: 'pending',
		...overrides
	};
}

function secret(overrides?: Partial<SecretInputItem>): SecretInputItem {
	return {
		type: 'secret_input',
		id: uid(),
		run_id: uid(),
		var_name: 'MY_SECRET',
		prompt: 'Enter secret',
		help: '',
		skill_name: 'test_skill',
		status: 'pending',
		...overrides
	};
}

function clarify(overrides?: Partial<ClarifyInputItem>): ClarifyInputItem {
	return {
		type: 'clarify_input',
		id: uid(),
		clarify_id: uid(),
		run_id: uid(),
		question: 'Choose an option',
		choices: ['A', 'B'],
		timeout_seconds: 300,
		status: 'pending',
		...overrides
	};
}

function todoPlan(overrides?: Partial<TodoPlanItem>): TodoPlanItem {
	return {
		type: 'todo_plan',
		id: uid(),
		call_id: uid(),
		title: 'Plan',
		todos: [{ id: '1', content: 'Build pinned strip', status: 'in_progress' }],
		status: 'in_progress',
		...overrides
	};
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('groupChronologically', () => {
	it('empty output → empty groups', () => {
		expect(groupChronologically([])).toEqual([]);
	});

	it('only messages → N message groups', () => {
		const m1 = msg();
		const m2 = msg();
		const groups = groupChronologically([m1, m2]);
		expect(groups).toHaveLength(2);
		expect(groups[0].kind).toBe('message');
		expect(groups[1].kind).toBe('message');
		if (groups[0].kind === 'message') expect(groups[0].item).toBe(m1);
		if (groups[1].kind === 'message') expect(groups[1].item).toBe(m2);
	});

	it('only reasoning → 1 chain group', () => {
		const r = reasoning();
		const groups = groupChronologically([r]);
		expect(groups).toHaveLength(1);
		expect(groups[0].kind).toBe('chain');
		if (groups[0].kind === 'chain') {
			expect(groups[0].items).toHaveLength(1);
			expect(groups[0].items[0]).toBe(r);
		}
	});

	it('reason → tool → tool → message → reason → tool → message → 4 groups in order', () => {
		const r1 = reasoning();
		const t1 = tool();
		const t2 = tool();
		const m1 = msg();
		const r2 = reasoning();
		const t3 = tool();
		const m2 = msg();

		const groups = groupChronologically([r1, t1, t2, m1, r2, t3, m2]);

		expect(groups).toHaveLength(4);
		expect(groups[0].kind).toBe('chain');
		expect(groups[1].kind).toBe('message');
		expect(groups[2].kind).toBe('chain');
		expect(groups[3].kind).toBe('message');

		if (groups[0].kind === 'chain') {
			expect(groups[0].items).toHaveLength(3);
			expect(groups[0].items[0]).toBe(r1);
			expect(groups[0].items[1]).toBe(t1);
			expect(groups[0].items[2]).toBe(t2);
			expect(groups[0].id).toBe(r1.id);
		}
		if (groups[2].kind === 'chain') {
			expect(groups[2].items).toHaveLength(2);
			expect(groups[2].items[0]).toBe(r2);
			expect(groups[2].items[1]).toBe(t3);
		}
		if (groups[1].kind === 'message') expect(groups[1].item).toBe(m1);
		if (groups[3].kind === 'message') expect(groups[3].item).toBe(m2);
	});

	it('confirmation breaks chain — verify exact group count', () => {
		const r1 = reasoning();
		const t1 = tool();
		const c1 = confirmation();
		const r2 = reasoning();
		const t2 = tool();

		const groups = groupChronologically([r1, t1, c1, r2, t2]);

		// chain(r1,t1), confirmation, chain(r2,t2) → 3 groups
		expect(groups).toHaveLength(3);
		expect(groups[0].kind).toBe('chain');
		expect(groups[1].kind).toBe('confirmation');
		expect(groups[2].kind).toBe('chain');

		if (groups[0].kind === 'chain') {
			expect(groups[0].items).toHaveLength(2);
		}
		if (groups[1].kind === 'confirmation') {
			expect(groups[1].item).toBe(c1);
		}
		if (groups[2].kind === 'chain') {
			expect(groups[2].items).toHaveLength(2);
		}
	});

	it('grouping is purely structural — in_progress status does not affect grouping', () => {
		// Even if reasoning is still in_progress, a confirmation mid-stream breaks the chain
		const r1 = reasoning({ status: 'in_progress' });
		const c1 = confirmation({ status: 'pending' });
		const r2 = reasoning({ status: 'in_progress' });

		const groups = groupChronologically([r1, c1, r2]);

		// chain(r1), confirmation, chain(r2) → 3 groups
		expect(groups).toHaveLength(3);
		expect(groups[0].kind).toBe('chain');
		expect(groups[1].kind).toBe('confirmation');
		expect(groups[2].kind).toBe('chain');
	});

	it('secret_input breaks a chain', () => {
		const r1 = reasoning();
		const s1 = secret();
		const t1 = tool();

		const groups = groupChronologically([r1, s1, t1]);

		expect(groups).toHaveLength(3);
		expect(groups[0].kind).toBe('chain');
		expect(groups[1].kind).toBe('secret');
		expect(groups[2].kind).toBe('chain');

		if (groups[1].kind === 'secret') {
			expect(groups[1].item).toBe(s1);
		}
	});

	it('clarify_input breaks a chain', () => {
		const r1 = reasoning();
		const c1 = clarify();
		const t1 = tool();

		const groups = groupChronologically([r1, c1, t1]);

		expect(groups).toHaveLength(3);
		expect(groups[0].kind).toBe('chain');
		expect(groups[1].kind).toBe('clarify');
		expect(groups[2].kind).toBe('chain');

		if (groups[1].kind === 'clarify') {
			expect(groups[1].item).toBe(c1);
		}
	});

	it('function_call_output items are filtered out', () => {
		const t1 = tool();
		const out1 = toolOutput(t1.call_id);

		const groups = groupChronologically([t1, out1]);

		// Only tool goes into a chain; output is skipped
		expect(groups).toHaveLength(1);
		expect(groups[0].kind).toBe('chain');
		if (groups[0].kind === 'chain') {
			expect(groups[0].items).toHaveLength(1);
			expect(groups[0].items[0]).toBe(t1);
		}
	});

	it('todo_plan is consumed by pinned strip and skipped from transcript groups', () => {
		const plan = todoPlan();
		const m = msg();

		const groups = groupChronologically([plan, m]);

		expect(groups).toHaveLength(1);
		expect(groups[0].kind).toBe('message');
		if (groups[0].kind === 'message') expect(groups[0].item).toBe(m);
	});

	it('generic todo tool rows are defensively hidden when a todo_plan exists', () => {
		const callId = 'call_todo_1';
		const todoCall = tool({ name: 'todo', call_id: callId });
		const todoOut = toolOutput(callId);
		const plan = todoPlan({ call_id: callId });
		const m = msg();

		const groups = groupChronologically([todoCall, todoOut, plan, m]);

		expect(groups).toHaveLength(1);
		expect(groups[0].kind).toBe('message');
		if (groups[0].kind === 'message') expect(groups[0].item).toBe(m);
	});

	it('malformed todo tool rows still render when no todo_plan exists', () => {
		const todoCall = tool({ name: 'todo', call_id: 'call_todo_bad' });

		const groups = groupChronologically([todoCall]);

		expect(groups).toHaveLength(1);
		expect(groups[0].kind).toBe('chain');
		if (groups[0].kind === 'chain') expect(groups[0].items[0]).toBe(todoCall);
	});

	it('phantom function_call with empty call_id is filtered out', () => {
		const phantom: FunctionCallItem = {
			type: 'function_call',
			id: uid(),
			call_id: '',
			name: 'ghost',
			arguments: '{}',
			status: 'in_progress'
		};
		const r1 = reasoning();

		const groups = groupChronologically([phantom, r1]);

		// Phantom is skipped; only r1 appears in a chain
		expect(groups).toHaveLength(1);
		expect(groups[0].kind).toBe('chain');
		if (groups[0].kind === 'chain') {
			expect(groups[0].items).toHaveLength(1);
			expect(groups[0].items[0]).toBe(r1);
		}
	});

	it('chain group id equals the first item id', () => {
		const r1 = reasoning();
		const t1 = tool();

		const groups = groupChronologically([r1, t1]);

		expect(groups).toHaveLength(1);
		if (groups[0].kind === 'chain') {
			expect(groups[0].id).toBe(r1.id);
		}
	});

	it('code_interpreter item goes into a chain with adjacent items', () => {
		const r1 = reasoning();
		const ci = codeInterp();
		const t1 = tool();

		const groups = groupChronologically([r1, ci, t1]);

		expect(groups).toHaveLength(1);
		if (groups[0].kind === 'chain') {
			expect(groups[0].items).toHaveLength(3);
			expect(groups[0].items[1]).toBe(ci);
		}
	});

	// ── Empty reasoning filter ──────────────────────────────────────────────
	// Backend de-dup can leave a completed reasoning item with an empty summary
	// (or none at all). Rendering such an item produces a phantom "Thought for
	// N seconds" row the user reported. The grouper filters them defensively.

	it('completed reasoning with empty summary is filtered out', () => {
		const empty = reasoning({ status: 'completed', summary: [] });
		const m = msg();

		const groups = groupChronologically([empty, m]);

		// Only the message survives — no empty chain
		expect(groups).toHaveLength(1);
		expect(groups[0].kind).toBe('message');
	});

	it('completed reasoning with whitespace-only summary is filtered out', () => {
		const whitespace = reasoning({
			status: 'completed',
			summary: [
				{ type: 'summary_text', text: '   \n\n  ' }
			]
		});
		const m = msg();

		const groups = groupChronologically([whitespace, m]);

		expect(groups).toHaveLength(1);
		expect(groups[0].kind).toBe('message');
	});

	it('in_progress reasoning with empty summary is KEPT (for shimmer)', () => {
		// While streaming, summary can briefly be empty — we still want to
		// render the "Thinking..." shimmer, so don't filter in_progress items.
		const streaming = reasoning({ status: 'in_progress', summary: [] });

		const groups = groupChronologically([streaming]);

		expect(groups).toHaveLength(1);
		expect(groups[0].kind).toBe('chain');
		if (groups[0].kind === 'chain') {
			expect(groups[0].items).toHaveLength(1);
			expect(groups[0].items[0]).toBe(streaming);
		}
	});

	it('reasoning with content is kept even if status is completed', () => {
		const withContent = reasoning({
			status: 'completed',
			summary: [{ type: 'summary_text', text: 'actual reasoning text' }]
		});

		const groups = groupChronologically([withContent]);

		expect(groups).toHaveLength(1);
		expect(groups[0].kind).toBe('chain');
	});

	it('empty reasoning between tools does NOT break the chain', () => {
		// Empty reasoning gets skipped; adjacent tool calls still form one chain.
		const t1 = tool();
		const emptyR = reasoning({ status: 'completed', summary: [] });
		const t2 = tool();

		const groups = groupChronologically([t1, emptyR, t2]);

		expect(groups).toHaveLength(1);
		expect(groups[0].kind).toBe('chain');
		if (groups[0].kind === 'chain') {
			expect(groups[0].items).toHaveLength(2); // t1, t2 — emptyR filtered
		}
	});
});
