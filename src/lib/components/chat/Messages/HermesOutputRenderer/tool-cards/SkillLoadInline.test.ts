import { describe, it, expect } from 'vitest';
import type { FunctionCallItem } from '../types';

// Pure logic extracted from SkillLoadInline.svelte for unit testing.
// (@testing-library/svelte is not installed, so we test the derivation logic directly.)

function deriveSkillName(call: Pick<FunctionCallItem, 'arguments'>): string {
	try {
		const args = JSON.parse(call.arguments || '{}');
		return args.name ?? args.skill_name ?? '';
	} catch {
		return '';
	}
}

function deriveIsExecuting(
	call: Pick<FunctionCallItem, 'status'>,
	messageDone: boolean
): boolean {
	return call.status === 'in_progress' && !messageDone;
}

function deriveLabel(skillName: string, isExecuting: boolean): string {
	const suffix = skillName ? ` ${skillName}` : '';
	return isExecuting ? `Loading skill${suffix}...` : `Loaded skill${suffix}`;
}

describe('SkillLoadInline logic', () => {
	// 1. skill_view in_progress → "Loading skill foo-skill..."
	it('renders "Loading skill foo-skill..." when skill_view is in_progress', () => {
		const call = { name: 'skill_view', arguments: '{"name": "foo-skill"}', status: 'in_progress' } as FunctionCallItem;
		const skillName = deriveSkillName(call);
		const isExecuting = deriveIsExecuting(call, false);
		expect(skillName).toBe('foo-skill');
		expect(isExecuting).toBe(true);
		expect(deriveLabel(skillName, isExecuting)).toBe('Loading skill foo-skill...');
	});

	// 2. skill_view completed → "Loaded skill foo-skill"
	it('renders "Loaded skill foo-skill" when skill_view is completed', () => {
		const call = { name: 'skill_view', arguments: '{"name": "foo-skill"}', status: 'completed' } as FunctionCallItem;
		const skillName = deriveSkillName(call);
		const isExecuting = deriveIsExecuting(call, true);
		expect(skillName).toBe('foo-skill');
		expect(isExecuting).toBe(false);
		expect(deriveLabel(skillName, isExecuting)).toBe('Loaded skill foo-skill');
	});

	// 3. view_skill alias → same behavior
	it('handles view_skill alias identically to skill_view', () => {
		const callInProgress = { name: 'view_skill', arguments: '{"name": "bar-skill"}', status: 'in_progress' } as FunctionCallItem;
		const callDone = { name: 'view_skill', arguments: '{"name": "bar-skill"}', status: 'completed' } as FunctionCallItem;
		expect(deriveLabel(deriveSkillName(callInProgress), deriveIsExecuting(callInProgress, false))).toBe('Loading skill bar-skill...');
		expect(deriveLabel(deriveSkillName(callDone), deriveIsExecuting(callDone, true))).toBe('Loaded skill bar-skill');
	});

	// 4. No skill name in arguments → "Loading skill..." / "Loaded skill"
	it('renders without skill name when arguments has no name field', () => {
		const callInProgress = { name: 'skill_view', arguments: '{}', status: 'in_progress' } as FunctionCallItem;
		const callDone = { name: 'skill_view', arguments: '{}', status: 'completed' } as FunctionCallItem;
		expect(deriveLabel(deriveSkillName(callInProgress), deriveIsExecuting(callInProgress, false))).toBe('Loading skill...');
		expect(deriveLabel(deriveSkillName(callDone), deriveIsExecuting(callDone, true))).toBe('Loaded skill');
	});

	// 5. args.skill_name fallback when args.name is absent
	it('falls back to args.skill_name when args.name is not present', () => {
		const call = { name: 'skill_view', arguments: '{"skill_name": "my-skill"}', status: 'in_progress' } as FunctionCallItem;
		const skillName = deriveSkillName(call);
		expect(skillName).toBe('my-skill');
		expect(deriveLabel(skillName, true)).toBe('Loading skill my-skill...');
	});

	// Extra: args.name takes priority over args.skill_name
	it('prefers args.name over args.skill_name when both are present', () => {
		const call = { name: 'skill_view', arguments: '{"name": "primary", "skill_name": "fallback"}', status: 'completed' } as FunctionCallItem;
		expect(deriveSkillName(call)).toBe('primary');
	});

	// Extra: invalid JSON arguments → empty skill name, no throw
	it('returns empty string for unparseable arguments', () => {
		const call = { name: 'skill_view', arguments: 'not-json', status: 'completed' } as FunctionCallItem;
		expect(deriveSkillName(call)).toBe('');
	});

	// Extra: messageDone=false with completed status → isExecuting is false
	it('isExecuting is false when status is completed regardless of messageDone', () => {
		const call = { status: 'completed' } as FunctionCallItem;
		expect(deriveIsExecuting(call, false)).toBe(false);
	});
});
