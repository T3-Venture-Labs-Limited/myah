import type { OutputItem } from '$lib/components/chat/Messages/HermesOutputRenderer/types';

export interface InflightSnapshot {
	run_id: string;
	chat_id: string;
	message_id: string;
	started_at: number;
	updated_at: number;
	message_content: string;
	reasoning_content: string;
	// Flat OutputItem[] matching message.output shape from the stream handler.
	// Named 'output' (not 'tool_calls') to match the backend field and avoid
	// confusion with PR 6's {call, result} paired shape.
	output: OutputItem[];
	status: 'streaming' | 'settled';
}

export type Banner = {
	id: string;
	type: string;
	title?: string;
	content: string;
	url?: string;
	dismissible?: boolean;
	timestamp: number;
};

export type AgentCommand = {
	name: string;
	category: 'session' | 'config' | 'tools' | 'info' | 'skill' | 'plugin' | 'misc';
	description: string;
	aliases: string[];
	args: string;
	bypass: boolean;
	source: 'builtin' | 'skill' | 'plugin';
	skill_path?: string;
};

export enum TTS_RESPONSE_SPLIT {
	PUNCTUATION = 'punctuation',
	PARAGRAPHS = 'paragraphs',
	NONE = 'none'
}
