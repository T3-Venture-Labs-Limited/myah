import { describe, it, expect, beforeAll } from 'vitest';
import { marked } from 'marked';
import { mediaExtension } from './media-extension';

beforeAll(() => {
	marked.use(mediaExtension);
});

function findMediaTokens(text: string) {
	// Inline tokens are nested inside paragraph → tokens
	const blockTokens = marked.lexer(text);
	const inlineTokens: any[] = [];
	for (const block of blockTokens) {
		if (block.tokens) {
			for (const t of block.tokens) {
				if (t.type === 'media') inlineTokens.push(t);
			}
		}
	}
	return inlineTokens;
}

describe('mediaExtension', () => {
	it('tokenizes a PNG path as image', () => {
		const tokens = findMediaTokens('Look: MEDIA:/cache/images/shot.png');
		expect(tokens).toHaveLength(1);
		expect(tokens[0].kind).toBe('image');
		expect(tokens[0].src).toContain('/api/v1/hermes/media?path=');
	});

	it('tokenizes an MP3 path as audio', () => {
		const tokens = findMediaTokens('Audio: MEDIA:/cache/audio/speech.mp3');
		expect(tokens).toHaveLength(1);
		expect(tokens[0].kind).toBe('audio');
	});

	it('tokenizes an MP4 path as video', () => {
		const tokens = findMediaTokens('Video: MEDIA:/cache/video/clip.mp4');
		expect(tokens).toHaveLength(1);
		expect(tokens[0].kind).toBe('video');
	});

	it('tokenizes unknown extension as file', () => {
		const tokens = findMediaTokens('Document: MEDIA:/cache/documents/report.pdf');
		expect(tokens).toHaveLength(1);
		expect(tokens[0].kind).toBe('file');
	});

	it('does NOT tokenize MEDIA: inside a URL', () => {
		// The MEDIA: is preceded by '/' which is not a boundary
		const tokens = findMediaTokens('See http://example.com/path/MEDIA:foo for details');
		// Should find zero media tokens (it's inside a URL)
		expect(tokens).toHaveLength(0);
	});

	it('does NOT tokenize MEDIA: inside inline code', () => {
		// Marked handles code spans before our extension runs
		const tokens = findMediaTokens('Use `MEDIA:/path/to/file.png` in your prompt');
		expect(tokens).toHaveLength(0);
	});

	it('routes https URLs directly (no proxy)', () => {
		const tokens = findMediaTokens('Image: MEDIA:https://cdn.example.com/image.jpg');
		expect(tokens).toHaveLength(1);
		expect(tokens[0].src).toBe('https://cdn.example.com/image.jpg');
	});

	it('extracts filename from path', () => {
		const tokens = findMediaTokens('MEDIA:/long/path/to/screenshot.png');
		expect(tokens[0].filename).toBe('screenshot.png');
	});

	// ── Bare cache-path tokenizer ────────────────────────────────────────────

	it('bare image path matches and returns image kind', () => {
		const tokens = findMediaTokens('Here is /data/.hermes/cache/images/foo.png done');
		expect(tokens).toHaveLength(1);
		expect(tokens[0].kind).toBe('image');
		expect(tokens[0].src).toContain('/api/v1/hermes/media?path=');
		expect(tokens[0].src).toContain('foo.png');
		expect(tokens[0].filename).toBe('foo.png');
	});

	it('bare audio path matches and returns audio kind', () => {
		const tokens = findMediaTokens('Output: /data/.hermes/cache/audio/speech.mp3');
		expect(tokens).toHaveLength(1);
		expect(tokens[0].kind).toBe('audio');
	});

	it('bare pdf path matches and returns file kind', () => {
		const tokens = findMediaTokens('Report: /data/.hermes/cache/docs/report.pdf done');
		expect(tokens).toHaveLength(1);
		expect(tokens[0].kind).toBe('file');
	});

	it('bare path in code fence does not match', () => {
		// marked processes code spans before our extension
		const tokens = findMediaTokens('`/data/.hermes/cache/images/foo.png`');
		expect(tokens).toHaveLength(0);
	});

	it('/etc/passwd.png does not match — no cache prefix', () => {
		const tokens = findMediaTokens('See /etc/passwd.png here');
		expect(tokens).toHaveLength(0);
	});

	it('.txt is a valid extension and DOES match', () => {
		// .txt was added to MEDIA_EXTS and is in fileTypeRegistry as 'text' kind.
		// The old test assumed it would not match — that test was wrong after the extension was added.
		const tokensTxt = findMediaTokens('See /data/.hermes/cache/log.txt here');
		expect(tokensTxt).toHaveLength(1);
		expect(tokensTxt[0].kind).toBe('file');
	});

	it('matches /root/<file>.xlsx as a bare media path', () => {
		const tokens = findMediaTokens('Saved to /root/financials.xlsx now.');
		expect(tokens).toHaveLength(1);
		expect(tokens[0].src).toContain('/api/v1/hermes/media?path=');
		expect(tokens[0].filename).toBe('financials.xlsx');
		expect(tokens[0].kind).toBe('file');
	});

	it('matches /root/<file>.png as bare image path', () => {
		const tokens = findMediaTokens('Generated /root/chart.png');
		expect(tokens).toHaveLength(1);
		expect(tokens[0].kind).toBe('image');
	});

	it('matches /Users/<name>/<file>.csv as bare path (macOS OSS)', () => {
		const tokens = findMediaTokens('See /Users/jane/workspace/data.csv done');
		expect(tokens).toHaveLength(1);
		expect(tokens[0].filename).toBe('data.csv');
		expect(tokens[0].kind).toBe('file');
	});

	it('matches ~/<file>.docx (agent shell shortcut) and rewrites to /root/', () => {
		// The agent often saves to its home directory and writes the path with
		// a tilde. Without this match, "saved to ~/Foo.docx" renders as plain
		// text — no artifact link, no preview pane entry. The fetch URL must
		// rewrite ~ to /root (the agent container's HOME) so the Hermes media
		// proxy can serve it; the displayed filename keeps ~/ as the agent
		// wrote it.
		const tokens = findMediaTokens('Word document created at ~/Adventures.docx now.');
		expect(tokens).toHaveLength(1);
		expect(tokens[0].filename).toBe('Adventures.docx');
		expect(tokens[0].kind).toBe('file');
		// URL-encoded /root/Adventures.docx
		expect(tokens[0].src).toContain('path=%2Froot%2FAdventures.docx');
	});

	it('matches ~/<file>.png as image with tilde rewrite', () => {
		const tokens = findMediaTokens('Saved chart to ~/output/chart.png');
		expect(tokens).toHaveLength(1);
		expect(tokens[0].filename).toBe('chart.png');
		expect(tokens[0].kind).toBe('image');
		expect(tokens[0].src).toContain('path=%2Froot%2Foutput%2Fchart.png');
	});

	it('does NOT match /etc/passwd.png even with extension allowlist', () => {
		const tokens = findMediaTokens('See /etc/passwd.png here');
		expect(tokens).toHaveLength(0);
	});

	// ── Image format coverage ──────────────────────────────────────────────
	// Lock in support for every image extension agents commonly produce —
	// breaking any one of these in MEDIA_EXTS or kindOf() should fail tests.

	it.each(['png', 'jpg', 'jpeg', 'webp', 'gif', 'avif', 'svg'])(
		'tokenizes .%s as image (bare path)',
		(ext) => {
			const tokens = findMediaTokens(`Generated /data/chart.${ext}`);
			expect(tokens).toHaveLength(1);
			expect(tokens[0].kind).toBe('image');
			expect(tokens[0].filename).toBe(`chart.${ext}`);
		}
	);

	// ── Video format coverage ──────────────────────────────────────────────
	// Without mkv/m4v/avi, agents using yt-dlp (defaults to .mkv), ffmpeg
	// captures, or screen recordings would have files silently dropped.

	it.each(['mp4', 'mov', 'webm', 'mkv', 'm4v', 'avi'])(
		'tokenizes .%s as video (bare path)',
		(ext) => {
			const tokens = findMediaTokens(`Recorded /data/clip.${ext} successfully`);
			expect(tokens).toHaveLength(1);
			expect(tokens[0].kind).toBe('video');
			expect(tokens[0].filename).toBe(`clip.${ext}`);
		}
	);

	it.each(['mp4', 'mov', 'webm', 'mkv', 'm4v', 'avi'])(
		'tokenizes .%s as video (MEDIA: tag)',
		(ext) => {
			const tokens = findMediaTokens(`Output: MEDIA:/data/clip.${ext}`);
			expect(tokens).toHaveLength(1);
			expect(tokens[0].kind).toBe('video');
		}
	);
});
