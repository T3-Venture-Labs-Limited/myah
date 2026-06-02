<script lang="ts">
	import { getContext } from 'svelte';

	import { MYAH_API_BASE_URL } from '$lib/constants';
	import { artifactSelection } from '$lib/stores';
	import type { ArtifactFile, SelectionPayload, ToolbarItem } from '$lib/types/artifact';
	import { detectFileType, type RendererKind } from '$lib/utils/fileTypeRegistry';

	import PdfRenderer from '$lib/components/renderers/PdfRenderer.svelte';
	import DocxRenderer from '$lib/components/renderers/DocxRenderer.svelte';
	import PptxRenderer from '$lib/components/renderers/PptxRenderer.svelte';
	import MarkdownRenderer from '$lib/components/renderers/MarkdownRenderer.svelte';
	import CsvRenderer from '$lib/components/renderers/CsvRenderer.svelte';
	import XlsxRenderer from '$lib/components/renderers/XlsxRenderer.svelte';
	import JsonRenderer from '$lib/components/renderers/JsonRenderer.svelte';
	import SqliteRenderer from '$lib/components/renderers/SqliteRenderer.svelte';
	import HtmlRenderer from '$lib/components/renderers/HtmlRenderer.svelte';
	import CodeRenderer from '$lib/components/renderers/CodeRenderer.svelte';
	import TextRenderer from '$lib/components/renderers/TextRenderer.svelte';
	import ImageRenderer from '$lib/components/renderers/ImageRenderer.svelte';
	import AudioRenderer from '$lib/components/renderers/AudioRenderer.svelte';
	import VideoRenderer from '$lib/components/renderers/VideoRenderer.svelte';
	import DiffBanner from './DiffBanner.svelte';

	// Mounted by ArtifactPane.svelte with the active tab's file. Header chrome
	// (Download / Open / Copy URL / Close) lives in ArtifactTabs.svelte; this
	// component now only renders the artifact content.
	export let file: ArtifactFile;
	export let token = '';
	// Spec §8.4. Phase 4B ships the components but does NOT yet wire the
	// agent-modified-while-dirty detection logic (a follow-up).  Hosts can
	// inject a pending diff via this prop for testing / future integration.
	export let pendingDiff: { from: string; to: string } | undefined = undefined;

	$: void token; // reserved for future renderers that need explicit auth headers

	// Resolve the display filename from the file prop
	$: resolvedFilename = file?.filename ?? (file?.path ? (file.path.split('/').pop() ?? file.path) : (file?.file_id ?? ''));

	// Detect the file type from the resolved name and optional MIME hint
	$: fileTypeEntry = detectFileType(resolvedFilename, file?.mime);
	$: kind = fileTypeEntry?.kind ?? 'unknown';

	// Map RendererKind to the renderer component.
	// xlsx uses XlsxRenderer (formula visibility); csv uses CsvRenderer.
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	const RENDERER_MAP: Record<RendererKind, any> = {
		pdf: PdfRenderer,
		docx: DocxRenderer,
		xlsx: XlsxRenderer,
		pptx: PptxRenderer,
		markdown: MarkdownRenderer,
		csv: CsvRenderer,
		json: JsonRenderer,
		sqlite: SqliteRenderer,
		html: HtmlRenderer,
		code: CodeRenderer,
		text: TextRenderer,
		image: ImageRenderer,
		audio: AudioRenderer,
		video: VideoRenderer,
		unknown: TextRenderer
	};

	$: rendererComponent = RENDERER_MAP[kind] ?? TextRenderer;

	// The renderer dispatches `select` events with a SelectionPayload (or null
	// to clear). We mirror that into the global `artifactSelection` store so
	// the SelectionToolbar embedded inside each renderer — and the upstream
	// composer ref-chip bar — can react. Without this, every renderer's
	// dispatch falls on the floor and the floating "+ Add to chat" toolbar
	// never appears. See Bugs 5+7 of the 2026-05-05 dogfooding pass.
	function onRendererSelect(e: CustomEvent<SelectionPayload | null>) {
		artifactSelection.set(e.detail ?? null);
	}

	// Toolbar items requested by the renderer (Format / Discard / Show source /
	// etc.) — currently surfaced only through the SelectionToolbar's own
	// internal slot. Captured here so a future tab-strip overlay action can
	// pick them up.
	// eslint-disable-next-line @typescript-eslint/no-unused-vars
	let _rendererToolbarItems: ToolbarItem[] = [];
	function onRendererToolbar(e: CustomEvent<{ items: ToolbarItem[] }>) {
		_rendererToolbarItems = e.detail.items;
	}

	// Content to pass to the renderer: file_id string (renderer fetches internally)
	// or a Blob fetched from the hermes media endpoint for path-based files.
	let content: string | Blob | null = null;
	let loading = false;
	let fetchError = '';

	const load = async () => {
		// Validate: exactly one of file_id or path
		if (!file?.file_id && !file?.path) {
			fetchError = 'ArtifactViewer: file has neither file_id nor path.';
			console.warn(fetchError);
			return;
		}

		fetchError = '';
		loading = true;
		content = null;

		try {
			if (file.file_id) {
				// Pass the file_id as a string — individual renderers know how to
				// fetch from /api/v1/files/{id}/content using MYAH_API_BASE_URL.
				content = file.file_id;
			} else if (file.path) {
				// Fetch blob from the hermes media proxy endpoint
				const url = `${MYAH_API_BASE_URL}/hermes/media?path=${encodeURIComponent(file.path)}`;
				const res = await fetch(url, { credentials: 'include' });
				if (!res.ok) throw new Error(`HTTP ${res.status}`);
				content = await res.blob();
			}
		} catch (e) {
			console.error('ArtifactViewer: failed to load file', e);
			fetchError = 'Failed to load file.';
		} finally {
			loading = false;
		}
	};

	// Reload whenever the key source identifiers change (covers initial mount
	// too). Track the composite key explicitly so the reactive block has a
	// proper if-statement body rather than a dangling comma expression.
	let lastFileKey: string | undefined = undefined;
	$: {
		const currentFileKey = `${file?.file_id ?? ''}|${file?.path ?? ''}`;
		if (currentFileKey !== lastFileKey) {
			lastFileKey = currentFileKey;
			load();
		}
	}

	// Auto-refresh: when the same artifact is re-emitted with a new mtime, debounce
	// 500ms then reload — handles agent tools that write files iteratively.
	let lastLoadedMtime: number | undefined = undefined;
	let debounceTimer: ReturnType<typeof setTimeout> | undefined;

	$: if (file) {
		const currentMtime = file.mtime;
		if (currentMtime !== undefined && currentMtime !== lastLoadedMtime) {
			clearTimeout(debounceTimer);
			debounceTimer = setTimeout(() => {
				lastLoadedMtime = currentMtime;
				load();
			}, 500);
		}
	}
</script>

<!-- Content area. Header chrome (filename / download / copy url / close)
     lives in ArtifactTabs.svelte's right-side action strip.
     No padding here — renderers paint their own backdrop edge-to-edge so the
     grey "page on background" surface from MarkdownRenderer/DocxRenderer
     reaches the pane's edges (no white frame around the grey wash). -->
<div class="flex-1 overflow-auto h-full">
	{#if loading}
		<div class="flex items-center justify-center py-12 text-sm text-gray-500 dark:text-gray-400">
			Loading…
		</div>
	{:else if fetchError}
		<div class="flex flex-col items-center justify-center py-12 gap-3">
			<span class="text-sm text-red-500">{fetchError}</span>
			<button
				class="px-3 py-1.5 text-xs rounded-lg bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 transition"
				on:click={load}
			>
				Retry
			</button>
		</div>
	{:else if !file?.file_id && !file?.path}
		<div class="text-sm text-gray-400 dark:text-gray-500 p-4">No file selected.</div>
	{:else if content !== null}
		{#if pendingDiff && kind !== 'code'}
			<DiffBanner
				filename={resolvedFilename}
				on:reload={() => (pendingDiff = undefined)}
				on:dismiss={() => (pendingDiff = undefined)}
			/>
		{/if}
		{#key file?.file_key}
			<svelte:component
				this={rendererComponent}
				{content}
				filename={resolvedFilename}
				mime={file?.mime}
				file_id={typeof content === 'string' ? content : file?.file_id}
				path={file?.path}
				{pendingDiff}
				on:select={onRendererSelect}
				on:toolbar={onRendererToolbar}
			/>
		{/key}
	{/if}
</div>
