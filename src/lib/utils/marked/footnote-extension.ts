// footnote-extension.ts
// Simple extension for marked to support footnote references like [^1], [^note]

function escapeHtml(s: string) {
	return s.replace(
		/[&<>"']/g,
		(c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!
	);
}

export function footnoteExtension() {
	return {
		name: 'footnote',
		level: 'inline' as const,
		start(src: string) {
			return src.search(/\[\^\s*[a-zA-Z0-9_-]+\s*\]/);
		},
		tokenizer(src: string) {
			const rule = /^\[\^\s*([a-zA-Z0-9_-]+)\s*\]/;
			const match = rule.exec(src);
			if (match) {
				const escapedText = escapeHtml(match[1]);
				return {
					type: 'footnote',
					raw: match[0],
					text: match[1],
					escapedText: escapedText
				};
			}
		},

		// `marked.parse(...)` call sites (RichTextInput, Banner, NotificationToast,
		// etc.) require a renderer for every custom token type. Without this,
		// the parser throws `Token with "footnote" type was not found.` whenever
		// a string contains `[^id]`. The chat message renderer
		// (`MarkdownInlineTokens.svelte`) still owns the in-chat UX via
		// `marked.lexer()`; this fallback only prevents the throw.
		renderer(token: { type: string; text?: string; escapedText?: string }) {
			const text = token.escapedText ?? escapeHtml(token.text ?? '');
			return `<sup class="footnote-ref"><a href="#fn-${text}">${text}</a></sup>`;
		}
	};
}

export default function () {
	return {
		extensions: [footnoteExtension()]
	};
}
