import { describe, it, expect } from 'vitest';
import {
	ARTIFACT_TOOL_NAMES,
	isArtifactTriggerTool,
	isArtifactExtension,
	isKnownFileExtension,
	extractPathFromToolResult
} from './artifact-triggers';
import fixture from './artifact-triggers.fixture.json';

// ── ARTIFACT_TOOL_NAMES ───────────────────────────────────────────────────────

describe('ARTIFACT_TOOL_NAMES', () => {
	it('matches fixture tool_names exactly', () => {
		expect([...ARTIFACT_TOOL_NAMES]).toEqual(fixture.tool_names);
	});
});

// ── isArtifactTriggerTool ─────────────────────────────────────────────────────

describe('isArtifactTriggerTool', () => {
	it('"write_file" → true', () => {
		expect(isArtifactTriggerTool('write_file')).toBe(true);
	});

	it('"patch" → true', () => {
		expect(isArtifactTriggerTool('patch')).toBe(true);
	});

	it('"image_generate" → true', () => {
		expect(isArtifactTriggerTool('image_generate')).toBe(true);
	});

	it('"text_to_speech" → true', () => {
		expect(isArtifactTriggerTool('text_to_speech')).toBe(true);
	});

	it('"browser_get_images" → true', () => {
		expect(isArtifactTriggerTool('browser_get_images')).toBe(true);
	});

	it('"display_file" → false (not a registered Hermes tool)', () => {
		expect(isArtifactTriggerTool('display_file')).toBe(false);
	});

	it('"create_document" → false (not a registered Hermes tool)', () => {
		expect(isArtifactTriggerTool('create_document')).toBe(false);
	});

	it('"edit_file" → false (not a registered Hermes tool)', () => {
		expect(isArtifactTriggerTool('edit_file')).toBe(false);
	});

	it('"browser_vision" → false', () => {
		expect(isArtifactTriggerTool('browser_vision')).toBe(false);
	});

	it('"search_web" → false', () => {
		expect(isArtifactTriggerTool('search_web')).toBe(false);
	});

	it('empty string → false', () => {
		expect(isArtifactTriggerTool('')).toBe(false);
	});
});

// ── isArtifactExtension ───────────────────────────────────────────────────────

describe('isArtifactExtension', () => {
	it('"report.pdf" → true (panel)', () => {
		expect(isArtifactExtension('report.pdf')).toBe(true);
	});

	it('"notes.md" → true (both)', () => {
		expect(isArtifactExtension('notes.md')).toBe(true);
	});

	it('"notes.markdown" → true (both)', () => {
		expect(isArtifactExtension('notes.markdown')).toBe(true);
	});

	it('"data.csv" → true (panel)', () => {
		expect(isArtifactExtension('data.csv')).toBe(true);
	});

	it('"script.py" → true (panel)', () => {
		expect(isArtifactExtension('script.py')).toBe(true);
	});

	it('"config.json" → true (panel)', () => {
		expect(isArtifactExtension('config.json')).toBe(true);
	});

	// Note: TS-side isArtifactExtension uses fileTypeRegistry which marks media
	// (image/audio/video) as capability:'inline'. The Python side's
	// _ARTIFACT_EXTENSIONS is the more permissive list and includes these
	// extensions. Phase 2B (media renderer redesign) will reconcile.
	it('"photo.png" → false (inline; TS side intentionally diverges from Python)', () => {
		expect(isArtifactExtension('photo.png')).toBe(false);
	});

	it('"song.mp3" → false (inline; TS side intentionally diverges from Python)', () => {
		expect(isArtifactExtension('song.mp3')).toBe(false);
	});

	it('"video.mp4" → false (inline; TS side intentionally diverges from Python)', () => {
		expect(isArtifactExtension('video.mp4')).toBe(false);
	});

	it('"archive.rar" → false (unknown)', () => {
		expect(isArtifactExtension('archive.rar')).toBe(false);
	});

	it('path-based: "/data/.hermes/cache/report.pdf" → true', () => {
		expect(isArtifactExtension('/data/.hermes/cache/report.pdf')).toBe(true);
	});
});

// ── extractPathFromToolResult ─────────────────────────────────────────────────

describe('extractPathFromToolResult', () => {
	it('null → null', () => {
		expect(extractPathFromToolResult(null)).toBeNull();
	});

	it('undefined → null', () => {
		expect(extractPathFromToolResult(undefined)).toBeNull();
	});

	it('absolute path string → the path', () => {
		expect(extractPathFromToolResult('/data/.hermes/cache/docs/report.md')).toBe(
			'/data/.hermes/cache/docs/report.md'
		);
	});

	it('relative string (no leading slash) → null', () => {
		expect(extractPathFromToolResult('relative/path.txt')).toBeNull();
	});

	it('{path: "/data/.hermes/cache/docs/report.md"} → the path', () => {
		expect(
			extractPathFromToolResult({ path: '/data/.hermes/cache/docs/report.md' })
		).toBe('/data/.hermes/cache/docs/report.md');
	});

	it('{filename: "out.pdf"} → "out.pdf"', () => {
		expect(extractPathFromToolResult({ filename: 'out.pdf' })).toBe('out.pdf');
	});

	it('{file_path: "/tmp/result.xlsx"} → the path', () => {
		expect(extractPathFromToolResult({ file_path: '/tmp/result.xlsx' })).toBe('/tmp/result.xlsx');
	});

	it('{filepath: "/tmp/result.db"} → the path', () => {
		expect(extractPathFromToolResult({ filepath: '/tmp/result.db' })).toBe('/tmp/result.db');
	});

	it('double-stringified JSON string → the path', () => {
		const doubleStringified = '{"path": "/data/file.txt"}';
		expect(extractPathFromToolResult(doubleStringified)).toBe('/data/file.txt');
	});

	it('object with double-stringified value → the path', () => {
		const obj = { result: '{"path": "/data/output.csv"}' };
		expect(extractPathFromToolResult(obj)).toBe('/data/output.csv');
	});

	it('number → null', () => {
		expect(extractPathFromToolResult(42)).toBeNull();
	});

	it('empty object → null', () => {
		expect(extractPathFromToolResult({})).toBeNull();
	});

	it('object with empty path string → checks next key', () => {
		expect(extractPathFromToolResult({ path: '', filename: 'out.txt' })).toBe('out.txt');
	});
});

// ── extractPathFromToolResult — stdout/output scan ───────────────────────────

describe('extractPathFromToolResult — stdout/output scan', () => {
	it('scans output for an embedded path', () => {
		expect(extractPathFromToolResult({ output: 'Wrote /tmp/forecast.xlsx' })).toBe(
			'/tmp/forecast.xlsx'
		);
	});

	it('scans stdout for an embedded path', () => {
		expect(extractPathFromToolResult({ stdout: 'Saved to /tmp/report.pdf' })).toBe(
			'/tmp/report.pdf'
		);
	});

	it('scans result string for an embedded path', () => {
		expect(extractPathFromToolResult({ result: 'Generated /tmp/chart.png in 0.5s' })).toBe(
			'/tmp/chart.png'
		);
	});

	it('returns null when neither a known key nor an embedded path exists', () => {
		expect(extractPathFromToolResult({ output: 'no path here' })).toBeNull();
	});

	it('scans bare strings without a leading slash', () => {
		expect(extractPathFromToolResult('Saved /workspace/out.csv to disk')).toBe(
			'/workspace/out.csv'
		);
	});
});

// ── isKnownFileExtension ─────────────────────────────────────────────────────

describe('isKnownFileExtension', () => {
	it('returns true for media (png/jpg/mp3/mp4)', () => {
		expect(isKnownFileExtension('chart.png')).toBe(true);
		expect(isKnownFileExtension('photo.jpg')).toBe(true);
		expect(isKnownFileExtension('clip.mp3')).toBe(true);
		expect(isKnownFileExtension('demo.mp4')).toBe(true);
	});

	it('returns true for documents (pdf/docx/xlsx)', () => {
		expect(isKnownFileExtension('doc.pdf')).toBe(true);
		expect(isKnownFileExtension('letter.docx')).toBe(true);
	});

	it('returns false for unknown extensions', () => {
		expect(isKnownFileExtension('mystery.xyz')).toBe(false);
		expect(isKnownFileExtension('Makefile')).toBe(false);
	});
});
