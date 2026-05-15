<script lang="ts">
	// A printed page glimpsed through cracked-open doors:
	// the first paragraph of a markdown or docx document.
	import { onMount } from 'svelte';
	import { marked } from 'marked';
	import DOMPurify from 'dompurify';
	import { MYAH_API_BASE_URL } from '$lib/constants';
	import type { ArtifactCardItem } from '$lib/types/contract';

	export let item: ArtifactCardItem;

	const MAX_CHARS = 400;

	let snippetHtml = '';
	let loading =
		!!(item.preview && typeof item.preview === 'string') ||
		!!item.file_id ||
		!!item.path;
	let errored = false;

	async function loadMarkdown() {
		if (!(item.preview && typeof item.preview === 'string') && !item.file_id && !item.path) {
			loading = false;
			return;
		}
		try {
			let text = '';
			if (item.preview && typeof item.preview === 'string') {
				text = item.preview;
			} else if (item.file_id) {
				const res = await fetch(`${MYAH_API_BASE_URL}/files/${item.file_id}/content`, {
					credentials: 'include'
				});
				if (!res.ok) throw new Error(`HTTP ${res.status}`);
				text = await res.text();
			} else if (item.path) {
				const res = await fetch(
					`${MYAH_API_BASE_URL}/hermes/media?path=${encodeURIComponent(item.path)}`,
					{ credentials: 'include' }
				);
				if (!res.ok) throw new Error(`HTTP ${res.status}`);
				text = await res.text();
			}

			// Strip front-matter so the preview shows real prose, not YAML.
			const trimmed = text.replace(/^---\n[\s\S]*?\n---\n?/, '');
			// First few non-blank paragraphs, capped to MAX_CHARS.
			const paragraphs = trimmed.split(/\n{2,}/).filter((p) => p.trim().length > 0);
			let preview = paragraphs.slice(0, 3).join('\n\n');
			if (preview.length > MAX_CHARS) preview = preview.slice(0, MAX_CHARS) + '…';
			const rendered = await marked.parse(preview);
			snippetHtml = DOMPurify.sanitize(rendered);
		} catch {
			errored = true;
		} finally {
			loading = false;
		}
	}

	async function loadDocx() {
		// Lazy import — docx-preview is only loaded when a docx mini preview
		// is actually rendered, keeping the main bundle thin.
		try {
			let blob: Blob;
			if (item.file_id) {
				const res = await fetch(`${MYAH_API_BASE_URL}/files/${item.file_id}/content`, {
					credentials: 'include'
				});
				if (!res.ok) throw new Error(`HTTP ${res.status}`);
				blob = await res.blob();
			} else if (item.path) {
				const res = await fetch(
					`${MYAH_API_BASE_URL}/hermes/media?path=${encodeURIComponent(item.path)}`,
					{ credentials: 'include' }
				);
				if (!res.ok) throw new Error(`HTTP ${res.status}`);
				blob = await res.blob();
			} else {
				errored = true;
				return;
			}
			const buf = await blob.arrayBuffer();
			const docx = await import('docx-preview');
			const host = document.createElement('div');
			await docx.renderAsync(buf, host, undefined, {
				inWrapper: false,
				ignoreFonts: true,
				breakPages: false
			});
			// First chunk of plain text from the rendered doc, capped.
			const text = host.innerText.replace(/\s+/g, ' ').trim();
			let preview = text.slice(0, MAX_CHARS);
			if (text.length > MAX_CHARS) preview += '…';
			snippetHtml = DOMPurify.sanitize(preview);
		} catch {
			errored = true;
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		if (item.kind === 'docx') {
			loadDocx();
		} else {
			loadMarkdown();
		}
	});
</script>

<div data-testid="mini-doc" class="text-xs leading-snug text-gray-700 dark:text-gray-300">
	{#if loading}
		<div class="text-gray-400 dark:text-gray-500 animate-pulse">Loading preview…</div>
	{:else if errored || !snippetHtml}
		<div class="text-gray-500 italic">Document · {item.filename}</div>
	{:else}
		<div class="prose prose-xs dark:prose-invert max-w-none mini-doc-snippet">
			{@html snippetHtml}
		</div>
	{/if}
</div>

<style>
	.mini-doc-snippet :global(h1),
	.mini-doc-snippet :global(h2),
	.mini-doc-snippet :global(h3) {
		font-size: 0.85em;
		font-weight: 600;
		margin: 0.25em 0;
	}
	.mini-doc-snippet :global(p) {
		margin: 0.25em 0;
	}
	.mini-doc-snippet :global(ul),
	.mini-doc-snippet :global(ol) {
		margin: 0.25em 0;
		padding-left: 1.25em;
	}
</style>
