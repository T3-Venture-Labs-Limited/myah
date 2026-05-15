import type { CatalogEntry, CuratedModel, ModelCapabilities } from '$lib/apis/providers'
import { normalizeCuratedModels } from '$lib/apis/providers'

// Ordered for UI display
export const AUX_TASKS = [
	'vision',
	'compression',
	'session_search',
	'skills_hub',
	'approval',
	'mcp',
	'flush_memories',
	'title_generation',
	'follow_up_generation',
] as const

export type AuxTask = (typeof AUX_TASKS)[number]

// Tasks that follow the per-provider aux_default (all except vision)
export const AUX_DEFAULT_TASKS: readonly AuxTask[] = AUX_TASKS.filter((t) => t !== 'vision')

// Tasks that need capability filtering
export const TASK_REQUIRED_CAPABILITIES: Partial<Record<AuxTask, Array<keyof ModelCapabilities>>> = {
	vision: ['supports_vision'],
	// All other tasks have no hard capability gate
}

// Human-readable labels
export const TASK_LABELS: Record<AuxTask, string> = {
	vision: 'Vision',
	compression: 'Context Compression',
	session_search: 'Session Search',
	skills_hub: 'Skills Hub',
	approval: 'Approval',
	mcp: 'MCP',
	flush_memories: 'Flush Memories',
	title_generation: 'Title Generation',
	follow_up_generation: 'Follow-up Questions',
}

export function modelsForTask(
	provider: string,
	task: AuxTask,
	catalog: CatalogEntry[]
): CuratedModel[] {
	const entry = catalog.find((c) => c.id === provider)
	if (!entry) return []
	const models = normalizeCuratedModels(entry.curated_models)
	const required = TASK_REQUIRED_CAPABILITIES[task]
	if (!required || required.length === 0) return models
	return models.filter((m) => required.every((cap) => m.capabilities?.[cap] === true))
}

export function hasVision(caps: ModelCapabilities | undefined): boolean {
	return caps?.supports_vision === true
}

export function hasLongContext(caps: ModelCapabilities | undefined, min = 32000): boolean {
	return caps?.context_window !== undefined && caps.context_window >= min
}
