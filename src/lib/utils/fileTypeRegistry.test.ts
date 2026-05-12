import { describe, it, expect } from 'vitest';
import {
	detectFileType,
	rendererKindOf,
	FILE_TYPE_REGISTRY,
	type RendererKind
} from './fileTypeRegistry';

// ── Extension coverage ────────────────────────────────────────────────────────

describe('detectFileType — extension matching', () => {
	const cases: Array<[string, RendererKind]> = [
		// PDF
		['document.pdf', 'pdf'],
		// DOCX
		['report.docx', 'docx'],
		// XLSX / XLS
		['data.xlsx', 'xlsx'],
		['data.xls', 'xlsx'],
		// PPTX
		['slides.pptx', 'pptx'],
		// Markdown
		['README.md', 'markdown'],
		['notes.markdown', 'markdown'],
		// CSV / TSV
		['export.csv', 'csv'],
		['export.tsv', 'csv'],
		// Images
		['photo.png', 'image'],
		['photo.jpg', 'image'],
		['photo.jpeg', 'image'],
		['photo.webp', 'image'],
		['photo.gif', 'image'],
		['photo.avif', 'image'],
		['icon.svg', 'image'],
		// Audio
		['song.mp3', 'audio'],
		['sound.ogg', 'audio'],
		['sound.opus', 'audio'],
		['sound.wav', 'audio'],
		['podcast.m4a', 'audio'],
		// Video
		['video.mp4', 'video'],
		['video.mov', 'video'],
		['video.webm', 'video'],
		// JSON / JSONL / IPYNB
		['config.json', 'json'],
		['stream.jsonl', 'json'],
		['notebook.ipynb', 'json'],
		// SQLite
		['database.db', 'sqlite'],
		['store.sqlite', 'sqlite'],
		['app.sqlite3', 'sqlite'],
		// HTML
		['page.html', 'html'],
		['page.htm', 'html'],
		// Code
		['script.py', 'code'],
		['module.ts', 'code'],
		['app.js', 'code'],
		['component.tsx', 'code'],
		['widget.jsx', 'code'],
		['main.go', 'code'],
		['lib.rs', 'code'],
		['Main.java', 'code'],
		['main.cpp', 'code'],
		['util.c', 'code'],
		['helpers.rb', 'code'],
		['run.sh', 'code'],
		['config.yaml', 'code'],
		['config.yml', 'code'],
		['Cargo.toml', 'code'],
		// Text
		['notes.txt', 'text']
	];

	for (const [filename, expectedKind] of cases) {
		it(`"${filename}" → ${expectedKind}`, () => {
			const entry = detectFileType(filename);
			expect(entry).not.toBeUndefined();
			expect(entry!.kind).toBe(expectedKind);
		});
	}
});

// ── Case-insensitive extension matching ───────────────────────────────────────

describe('detectFileType — case-insensitive extension', () => {
	it('FOO.PDF resolves to pdf', () => {
		expect(detectFileType('FOO.PDF')?.kind).toBe('pdf');
	});

	it('REPORT.DOCX resolves to docx', () => {
		expect(detectFileType('REPORT.DOCX')?.kind).toBe('docx');
	});

	it('Image.PNG resolves to image', () => {
		expect(detectFileType('Image.PNG')?.kind).toBe('image');
	});

	it('MixedCase.Py resolves to code', () => {
		expect(detectFileType('MixedCase.Py')?.kind).toBe('code');
	});
});

// ── Path-based inputs ─────────────────────────────────────────────────────────

describe('detectFileType — path inputs', () => {
	it('/home/user/docs/report.pdf resolves to pdf', () => {
		expect(detectFileType('/home/user/docs/report.pdf')?.kind).toBe('pdf');
	});

	it('relative/path/to/script.py resolves to code', () => {
		expect(detectFileType('relative/path/to/script.py')?.kind).toBe('code');
	});

	it('foo.tar.gz → gz (not in registry → undefined)', () => {
		// Last extension is "gz" which is not in the registry
		expect(detectFileType('foo.tar.gz')).toBeUndefined();
	});
});

// ── Unknown / no match ────────────────────────────────────────────────────────

describe('detectFileType — unknown files', () => {
	it('unknown extension returns undefined', () => {
		expect(detectFileType('archive.rar')).toBeUndefined();
	});

	it('file with no extension returns undefined', () => {
		expect(detectFileType('Makefile')).toBeUndefined();
	});

	it('trailing dot returns undefined', () => {
		expect(detectFileType('weird.')).toBeUndefined();
	});

	it('empty string returns undefined', () => {
		expect(detectFileType('')).toBeUndefined();
	});
});

// ── MIME hint priority ────────────────────────────────────────────────────────

describe('detectFileType — MIME hint priority', () => {
	it('application/pdf MIME wins over any extension', () => {
		// Even if the filename says .docx, MIME should win
		expect(detectFileType('wrong.docx', 'application/pdf')?.kind).toBe('pdf');
	});

	it('MIME hint takes priority over extension for docx', () => {
		const entry = detectFileType(
			'file.txt',
			'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
		);
		expect(entry?.kind).toBe('docx');
	});

	it('MIME hint is case-insensitive', () => {
		expect(detectFileType('file.xyz', 'Application/PDF')?.kind).toBe('pdf');
	});

	it('unknown MIME falls back to extension', () => {
		expect(detectFileType('document.pdf', 'application/octet-stream')?.kind).toBe('pdf');
	});

	it('unknown MIME with unknown extension returns undefined', () => {
		expect(detectFileType('archive.rar', 'application/x-rar-compressed')).toBeUndefined();
	});
});

// ── rendererKindOf ────────────────────────────────────────────────────────────

describe('rendererKindOf', () => {
	it('returns the kind for a known file', () => {
		expect(rendererKindOf('report.pdf')).toBe('pdf');
	});

	it('returns "unknown" for an unrecognized file', () => {
		expect(rendererKindOf('archive.rar')).toBe('unknown');
	});

	it('returns "unknown" for empty string', () => {
		expect(rendererKindOf('')).toBe('unknown');
	});

	it('respects MIME hint', () => {
		expect(rendererKindOf('file.bin', 'application/pdf')).toBe('pdf');
	});
});

// ── Registry completeness ─────────────────────────────────────────────────────

describe('FILE_TYPE_REGISTRY completeness', () => {
	it('every entry has at least one extension', () => {
		for (const entry of FILE_TYPE_REGISTRY) {
			expect(entry.extensions.length).toBeGreaterThan(0);
		}
	});

	it('all extensions are lowercase and have no leading dot', () => {
		for (const entry of FILE_TYPE_REGISTRY) {
			for (const ext of entry.extensions) {
				expect(ext).toBe(ext.toLowerCase());
				expect(ext.startsWith('.')).toBe(false);
			}
		}
	});

	it('all capability values are valid', () => {
		const valid = new Set(['inline', 'panel', 'both']);
		for (const entry of FILE_TYPE_REGISTRY) {
			expect(valid.has(entry.capability)).toBe(true);
		}
	});

	it('MEDIA_EXTS — all inline/both entries can be discovered from registry', () => {
		// Tasks 4 and 5 (bare-path tokenizers) need to know which extensions
		// represent media files (images, audio, video). They can derive this
		// set from FILE_TYPE_REGISTRY by filtering on capability.
		const mediaKinds: RendererKind[] = ['image', 'audio', 'video'];
		const mediaExts = FILE_TYPE_REGISTRY.filter((e) => mediaKinds.includes(e.kind)).flatMap(
			(e) => e.extensions
		);

		// Spot-check a few known media extensions
		expect(mediaExts).toContain('png');
		expect(mediaExts).toContain('jpg');
		expect(mediaExts).toContain('mp3');
		expect(mediaExts).toContain('mp4');
		expect(mediaExts).toContain('wav');
		expect(mediaExts).toContain('gif');
	});
});
