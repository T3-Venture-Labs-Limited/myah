/**
 * Marked extension that tokenizes Hermes MEDIA:<path> tags and bare
 * /data/.hermes/cache/... paths written verbatim in agent prose.
 *
 * Two tokenizers are registered:
 *  1. MEDIA:<path>  — original convention for agent-surfaced artifacts.
 *  2. bare_path     — verbatim cache paths the agent sometimes writes without
 *                     a MEDIA: prefix. Routes through the same media proxy.
 *
 * Security: Both token srcs are always passed through /api/v1/hermes/media
 * which re-authenticates with the user session and validates the path against
 * the container's whitelist. No direct container path exposure.
 *
 * Sync invariant: MEDIA_EXTS must match _BARE_PATH_EXTS in hermes_media_persist.py.
 * Any drift means Python persists URLs the TS tokenizer cannot resolve.
 */
import type { MarkedExtension, Tokens } from 'marked';
import { detectFileType } from '$lib/utils/fileTypeRegistry';

// The path part after MEDIA: contains only ASCII printable characters (0x21–0x7E).
// This stops cleanly at emoji, multi-byte Unicode, whitespace, and punctuation
// that would never appear inside a URL or filesystem path.
const MEDIA_RE = /^MEDIA:([\x21-\x7E]+?)(?=[^\x21-\x7E]|$)/;
const PRECEDING_BOUNDARY = /[\s\n\r\t([{>]$/;

// 2026-05-05 dogfooding (Bug 1a): strip trailing sentence-end punctuation that
// the agent's prose appends after a path/URL. Without this, "Saved to
// `MEDIA:/api/v1/files/abc/content?name=fib.py`." captures the trailing `.`
// because every char up to the newline is printable. The chip then renders
// "fib.py." with a dangling period and the URL is wrong by one byte.
//
// We only strip punctuation that NEVER appears as a meaningful trailing
// character in URLs or filesystem paths. `/` is intentionally NOT in the set
// — directories may end in `/`. `_` and `-` are also kept because filenames
// frequently end in them.
const TRAILING_TERMINAL_PUNCT_RE = /[.,;:!?)\]}>'"`]+$/;
function trimTrailingPunctuation(captured: string): string {
	return captured.replace(TRAILING_TERMINAL_PUNCT_RE, '');
}

// ── Bare cache-path tokenizer constants ───────────────────────────────────
// Extension list is the single source of truth — must match _BARE_PATH_EXTS
// in platform/backend/myah/utils/hermes_media_persist.py.
// T3-1001 dogfooding 2026-04-24: expanded with code/config/db extensions to
// match _ARTIFACT_EXTENSIONS in artifact_triggers.py.
const MEDIA_EXTS =
	// images
	'png|jpg|jpeg|webp|gif|avif|svg' +
	// audio / video
	'|mp3|ogg|opus|wav|m4a' +
	'|mp4|mov|webm|mkv|m4v|avi' +
	// docs
	'|pdf|docx|xlsx|xls|pptx|ipynb' +
	// text / markup
	'|md|markdown|csv|tsv' +
	'|json|jsonl' +
	'|html|htm' +
	'|txt|log' +
	// databases
	'|db|sqlite|sqlite3' +
	// code
	'|py|ts|js|tsx|jsx' +
	'|go|rs|java|cpp|c|rb|sh' +
	'|yaml|yml|toml';

// T3-1001 dogfooding 2026-04-24: extended prefix list to match the broader
// backend regex. Agents routinely write to /tmp, /workspace, /data, and
// /home/<user> in addition to /data/.hermes/cache/.
// Also /root/ (Hermes' default terminal.cwd inside the Myah Docker container)
// and /Users/<name>/ (macOS OSS Hermes deployments).
//
// Tilde paths (`~/foo.docx`) are added because the agent's shell context resolves
// `~` to its home directory (`/root` inside our container, sometimes `/data` or
// `/home/<user>` in OSS deployments). Without this match, the agent saying
// "saved to ~/file.docx" produces no artifact link in chat — it just renders
// as plain text. We rewrite `~/...` to `/root/...` at resolveSrc-time so the
// Hermes media proxy can serve it (the agent container's HOME is /root by
// default; if that ever changes, the proxy's allowlist must be updated to
// match).
const PATH_PREFIXES = [
	'/data/.hermes/cache/',
	'/tmp/',
	'/workspace/',
	'/data/',
	'/root/', // Hermes default terminal.cwd inside Myah Docker container
	'/Users/', // macOS OSS Hermes deployments
	'/home/', // Linux OSS Hermes deployments
	'~/' // agent shell shortcut — rewritten to /root/ at resolve time
];

// RegExp built from string concatenation to avoid backtick escaping issues
// inside a template literal character class.
const CACHE_PATH_RE = new RegExp(
	'^((?:/data/\\.hermes/cache|/tmp|/workspace|/data|/root|/Users/[^/\\s]+|/home/[^/\\s]+|~)/' +
		"[^\\s<>'\"`,]+?\\.(?:" +
		MEDIA_EXTS +
		'))(?=[\\s<>\'"\\)\\]}`]|$)',
	'i'
);
// ─────────────────────────────────────────────────────────────────────────

type MediaKind = 'image' | 'audio' | 'video' | 'file';

export interface MediaToken extends Tokens.Generic {
	type: 'media';
	raw: string;
	src: string;
	kind: MediaKind;
	filename: string;
}

// Extract filename from a `name=...` query param if present.
// T3-1001 dogfooding 2026-04-24: persist_and_rewrite appends ?name=<orig> to
// rewritten platform file URLs so we can classify by extension instead of
// always falling back to 'image' for /api/v1/files/{id}/content.
function nameHintFromUrl(url: string): string | undefined {
	const qsIdx = url.indexOf('?');
	if (qsIdx === -1) return undefined;
	const params = new URLSearchParams(url.slice(qsIdx + 1));
	const name = params.get('name');
	return name ? name.toLowerCase() : undefined;
}

function kindOf(pathOrUrl: string): MediaKind {
	// 1. Filename hint from ?name=<orig> query param — most authoritative
	const hint = nameHintFromUrl(pathOrUrl);
	if (hint) {
		if (/\.(png|jpe?g|webp|gif|avif|svg)$/.test(hint)) return 'image';
		if (/\.(ogg|opus|mp3|wav|m4a|aac)$/.test(hint)) return 'audio';
		if (/\.(mp4|mov|webm|mkv|m4v|avi)$/.test(hint)) return 'video';
		return 'file';
	}

	// 2. Direct extension on the path itself
	const lower = pathOrUrl.split('?')[0].toLowerCase();
	if (/\.(png|jpe?g|webp|gif|avif|svg)$/.test(lower)) return 'image';
	if (/\.(ogg|opus|mp3|wav|m4a|aac)$/.test(lower)) return 'audio';
	if (/\.(mp4|mov|webm|mkv|m4v|avi)$/.test(lower)) return 'video';

	// 3. Hermes media proxy: infer from original path in `path=` query
	if (/\/api\/v1\/hermes\/media/.test(lower)) {
		const qs = pathOrUrl.split('?')[1] || '';
		const p = decodeURIComponent(qs.replace('path=', '')).toLowerCase();
		if (/\.(png|jpe?g|webp|gif|avif|svg)$/.test(p)) return 'image';
		if (/\.(ogg|opus|mp3|wav|m4a|aac)$/.test(p)) return 'audio';
		if (/\.(mp4|mov|webm|mkv|m4v|avi)$/.test(p)) return 'video';
	}

	// Default: treat as a generic file (rendered as a clickable pill, not <img>).
	// Platform file content URLs (/api/v1/files/{id}/content) without a name hint
	// land here — safer than misclassifying CSVs and Markdown as images.
	return 'file';
}

function resolveSrc(raw: string): string {
	// Already a platform file URL — pass through
	if (/^(https?:|data:|blob:|\/api\/v1\/files\/)/.test(raw)) return raw;
	// Container path or relative — route through the media proxy
	return `/api/v1/hermes/media?path=${encodeURIComponent(raw)}`;
}

// Minimal HTML escape for renderer fallback. Marked's html_safe path needs a
// renderer to exist for every custom token type — without it, `marked.parse(...)`
// throws `Token with "media" type was not found.` at any call site that doesn't
// go through the Svelte token switch (RichTextInput, Placeholder, Banner,
// NotificationToast, etc). The chat message renderer (`MarkdownInlineTokens.svelte`)
// still owns the rich UX; this fallback only prevents the throw on the simpler
// `marked.parse()` call sites.
function escapeHtml(s: string): string {
	return String(s)
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;')
		.replace(/'/g, '&#39;');
}

function renderMediaToken(token: MediaToken): string {
	const src = escapeHtml(token.src);
	const filename = escapeHtml(token.filename);
	if (token.kind === 'image') {
		return `<img src="${src}" alt="${filename}">`;
	}
	if (token.kind === 'audio') {
		return `<audio controls src="${src}"></audio>`;
	}
	if (token.kind === 'video') {
		return `<video controls src="${src}"></video>`;
	}
	return `<a href="${src}" download="${filename}">${filename}</a>`;
}

export const mediaExtension: MarkedExtension = {
	extensions: [
		{
			name: 'media',
			level: 'inline' as const,

			start(src: string): number | undefined {
				// Walk all occurrences of MEDIA: and return the index of the first one
				// that has a valid preceding character (boundary or start of string).
				let i = 0;
				while (true) {
					const idx = src.indexOf('MEDIA:', i);
					if (idx < 0) return undefined;
					if (idx === 0) return 0;
					const prev = src[idx - 1];
					if (PRECEDING_BOUNDARY.test(prev) || prev === '') return idx;
					i = idx + 1;
				}
			},

			tokenizer(src: string): MediaToken | undefined {
				const m = MEDIA_RE.exec(src);
				if (!m) return undefined;
				// Strip leading wrap quotes AND trailing sentence-end punctuation
				// (`.`, `,`, `;`, `:`, `!`, `?`, `)`, `]`, `}`, `>`, `"`, `'`).
				// The MEDIA: regex is greedy across all printable ASCII because
				// it has to handle URLs that legitimately contain unusual chars,
				// but it cannot tell when a `.` belongs to the URL vs. the prose
				// that follows. Post-processing handles that ambiguity.
				const raw_capture = m[1].replace(/^['"`]|['"`]$/g, '');
				const raw_path = trimTrailingPunctuation(raw_capture);
				if (!raw_path) return undefined;
				// Recompute `raw` (the whole match including MEDIA: prefix) so the
				// trailing punctuation we trimmed is left in the source for marked
				// to tokenize as plain text. Without this, "MEDIA:/foo.png." would
				// still consume the trailing period and render as a hidden char.
				const trimmedDelta = raw_capture.length - raw_path.length;
				const raw = trimmedDelta > 0 ? m[0].slice(0, m[0].length - trimmedDelta) : m[0];
				const src_url = resolveSrc(raw_path);
				// Prefer ?name=<orig> hint from the URL when available
				// (set by persist_and_rewrite for rewritten bare paths).
				// Otherwise fall back to the last path segment, which for
				// /api/v1/files/{id}/content would be "content" — useless.
				const hint = nameHintFromUrl(raw_path);
				const filename =
					hint || raw_path.split('?')[0].split('/').pop() || raw_path;
				return {
					type: 'media',
					raw,
					src: src_url,
					kind: kindOf(raw_path),
					filename
				};
			},

			renderer(token: Tokens.Generic): string {
				return renderMediaToken(token as MediaToken);
			}
		},

		// ── Myah: bare cache-path tokenizer ──────────────────────────────────
		// Matches verbatim agent-written paths under /data/.hermes/cache, /tmp,
		// /workspace, /data, /home/<user>. Reuses the 'media' token type so the
		// existing HermesOutputRenderer handles both paths identically.
		{
			name: 'bare_path',
			level: 'inline' as const,

			start(src: string): number | undefined {
				let earliest = -1;
				for (const prefix of PATH_PREFIXES) {
					const idx = src.indexOf(prefix);
					if (idx >= 0 && (earliest === -1 || idx < earliest)) {
						earliest = idx;
					}
				}
				return earliest >= 0 ? earliest : undefined;
			},

			tokenizer(src: string, _tokens: any[]): MediaToken | undefined {
				// CACHE_PATH_RE is anchored at start — only fires when marked
				// calls us at the right offset.
				const m = CACHE_PATH_RE.exec(src);
				if (!m) return undefined;

				// 2026-05-05 dogfooding (Bug 1a): strip sentence-end punctuation
				// that the agent's prose appends after a bare path. The CACHE_PATH_RE
				// lookahead already stops at `,` and `)` etc., but `.` followed by
				// EOL slips through because the path itself contains `.`. Clean up
				// any residual `.,;:!?` here.
				const rawCaptureBare = m[1];
				const rawPath = trimTrailingPunctuation(rawCaptureBare);
				if (!rawPath) return undefined;
				const entry = detectFileType(rawPath);
				// Reject if registry doesn't recognise the extension
				if (!entry) return undefined;

				const trimmedDeltaBare = rawCaptureBare.length - rawPath.length;
				const raw = trimmedDeltaBare > 0 ? m[0].slice(0, m[0].length - trimmedDeltaBare) : m[0];

				// Map RendererKind → MediaKind (image/audio/video pass through; rest are 'file')
				const kind: MediaKind =
					entry.kind === 'image' || entry.kind === 'audio' || entry.kind === 'video'
						? entry.kind
						: 'file';

				// Rewrite tilde to the agent container's HOME (/root) so the
				// Hermes media proxy's allowlist accepts the path. The display
				// path stays as-is (rawPath) so the rendered filename matches
				// what the agent wrote; only the fetch URL is rewritten.
				const fetchPath = rawPath.startsWith('~/') ? `/root/${rawPath.slice(2)}` : rawPath;

				return {
					type: 'media',
					raw,
					src: `/api/v1/hermes/media?path=${encodeURIComponent(fetchPath)}`,
					kind,
					filename: rawPath.split('/').pop() ?? rawPath
				};
			},

			renderer(token: Tokens.Generic): string {
				return renderMediaToken(token as MediaToken);
			}
		}
		// ─────────────────────────────────────────────────────────────────────
	]
};
