// A name alone is not enough. Every tool deserves a face —
// a small icon and a plain word to say what it is doing.

export interface ToolLabel {
	icon: string; // emoji icon
	label: string; // short human-readable label
}

export const TOOL_LABELS: Record<string, ToolLabel> = {
	// File operations
	read_file: { icon: '📄', label: 'Reading file' },
	write_file: { icon: '✏️', label: 'Writing file' },
	patch: { icon: '🔧', label: 'Patching' },
	list_directory: { icon: '📁', label: 'Listing directory' },
	search_files: { icon: '🔍', label: 'Searching files' },
	delete_file: { icon: '🗑️', label: 'Deleting file' },
	move_file: { icon: '📦', label: 'Moving file' },

	// Web
	web_search: { icon: '🌐', label: 'Searching web' },
	web_extract: { icon: '🌐', label: 'Extracting page' },
	browser_navigate: { icon: '🖥️', label: 'Navigating browser' },
	browser_vision: { icon: '📸', label: 'Taking screenshot' },

	// Terminal / code
	terminal: { icon: '💻', label: 'Running command' },
	execute_code: { icon: '⚡', label: 'Executing code' },
	background: { icon: '⚙️', label: 'Background process' },

	// AI / analysis
	vision_analyze: { icon: '👁️', label: 'Analyzing image' },
	text_to_speech: { icon: '🔊', label: 'Generating speech' },
	image_generate: { icon: '🎨', label: 'Generating image' },
	transcribe_audio: { icon: '🎤', label: 'Transcribing audio' },

	// Memory / skills
	memorize: { icon: '🧠', label: 'Memorizing' },
	recall: { icon: '🧠', label: 'Recalling' },
	skill_manage: { icon: '🛠️', label: 'Managing skill' },
	delegate_task: { icon: '🤝', label: 'Delegating task' }
};

/**
 * Get the label config for a tool, falling back to a default.
 */
export function getToolLabel(toolName: string): ToolLabel {
	return TOOL_LABELS[toolName] ?? { icon: '🔧', label: toolName };
}
