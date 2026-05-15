/**
 * Single source of truth for file-type detection across the application.
 *
 * Every renderer, tokenizer, and file tab resolves file kind through
 * detectFileType — never through ad-hoc extension checks scattered
 * across individual components.
 */

export type RendererKind =
	| 'image'
	| 'pdf'
	| 'docx'
	| 'xlsx'
	| 'pptx'
	| 'csv'
	| 'markdown'
	| 'code'
	| 'json'
	| 'sqlite'
	| 'html'
	| 'text'
	| 'video'
	| 'audio'
	| 'unknown';

export interface FileTypeEntry {
	extensions: string[]; // lowercase, no leading dot
	mimes?: string[];
	kind: RendererKind;
	capability: 'inline' | 'panel' | 'both';
}

// The order here matters: first match wins for MIME-less lookups.
export const FILE_TYPE_REGISTRY: FileTypeEntry[] = [
	{
		extensions: ['pdf'],
		mimes: ['application/pdf'],
		kind: 'pdf',
		capability: 'panel'
	},
	{
		extensions: ['docx'],
		mimes: ['application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
		kind: 'docx',
		capability: 'panel'
	},
	{ extensions: ['xlsx', 'xls'], kind: 'xlsx', capability: 'panel' },
	{ extensions: ['pptx'], kind: 'pptx', capability: 'panel' },
	{ extensions: ['md', 'markdown'], kind: 'markdown', capability: 'both' },
	{ extensions: ['csv', 'tsv'], kind: 'csv', capability: 'panel' },
	{
		extensions: ['png', 'jpg', 'jpeg', 'webp', 'gif', 'avif', 'svg'],
		kind: 'image',
		capability: 'inline'
	},
	{ extensions: ['mp3', 'ogg', 'opus', 'wav', 'm4a'], kind: 'audio', capability: 'inline' },
	{ extensions: ['mp4', 'mov', 'webm', 'mkv', 'm4v', 'avi'], kind: 'video', capability: 'inline' },
	{ extensions: ['json', 'jsonl', 'ipynb'], kind: 'json', capability: 'panel' },
	{ extensions: ['db', 'sqlite', 'sqlite3'], kind: 'sqlite', capability: 'panel' },
	{ extensions: ['html', 'htm'], kind: 'html', capability: 'panel' },
	{
		extensions: [
			'py',
			'ts',
			'js',
			'tsx',
			'jsx',
			'go',
			'rs',
			'java',
			'cpp',
			'c',
			'rb',
			'sh',
			'yaml',
			'yml',
			'toml'
		],
		kind: 'code',
		capability: 'panel'
	},
	{ extensions: ['txt'], kind: 'text', capability: 'panel' }
];

/**
 * Detect the file type entry for a given filename/path and optional MIME hint.
 *
 * Strategy:
 * 1. If mimeHint is provided, search registry for an entry whose mimes array
 *    contains the hint (case-insensitive). Return on first match.
 * 2. Extract the extension from the last '.' in filenameOrPath (lowercase).
 * 3. Return the first registry entry whose extensions array includes the ext.
 * 4. Return undefined if no match.
 */
export function detectFileType(
	filenameOrPath: string,
	mimeHint?: string
): FileTypeEntry | undefined {
	// 1. MIME hint — most specific signal, check first
	if (mimeHint) {
		const normalizedMime = mimeHint.toLowerCase().trim();
		for (const entry of FILE_TYPE_REGISTRY) {
			if (entry.mimes?.some((m) => m.toLowerCase() === normalizedMime)) {
				return entry;
			}
		}
	}

	// 2. Extension fallback
	const lastDot = filenameOrPath.lastIndexOf('.');
	if (lastDot === -1 || lastDot === filenameOrPath.length - 1) {
		return undefined;
	}
	const ext = filenameOrPath.slice(lastDot + 1).toLowerCase();

	for (const entry of FILE_TYPE_REGISTRY) {
		if (entry.extensions.includes(ext)) {
			return entry;
		}
	}

	return undefined;
}

/**
 * Convenience wrapper that returns the RendererKind string,
 * falling back to 'unknown' when no entry matches.
 */
export function rendererKindOf(filenameOrPath: string, mimeHint?: string): RendererKind {
	return detectFileType(filenameOrPath, mimeHint)?.kind ?? 'unknown';
}
