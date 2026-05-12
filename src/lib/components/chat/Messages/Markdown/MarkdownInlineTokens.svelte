<script lang="ts">
	import DOMPurify from 'dompurify';
	import { toast } from 'svelte-sonner';

	import type { Token } from 'marked';
	import { getContext } from 'svelte';
	import { goto } from '$app/navigation';

	const i18n = getContext('i18n');

	import { WEBUI_BASE_URL } from '$lib/constants';
	import { copyToClipboard, unescapeHtml } from '$lib/utils';
	import { openArtifactInPane } from '$lib/stores';
	import { detectFileType } from '$lib/utils/fileTypeRegistry';

	import Image from '$lib/components/common/Image.svelte';
	import KatexRenderer from './KatexRenderer.svelte';
	import Source from './Source.svelte';
	import HtmlToken from './HTMLToken.svelte';
	import TextToken from './MarkdownInlineTokens/TextToken.svelte';
	import CodespanToken from './MarkdownInlineTokens/CodespanToken.svelte';
	import MentionToken from './MarkdownInlineTokens/MentionToken.svelte';
	import NoteLinkToken from './MarkdownInlineTokens/NoteLinkToken.svelte';
	import SourceToken from './SourceToken.svelte';

	// T3-1001 dogfooding 2026-04-24: open the right-side artifact panel for
	// non-inline file types (CSV, MD, code, JSON, etc.) when the user clicks
	// the inline file pill, instead of opening the raw bytes in a new tab.
	// Image/audio/video have capability='inline' and continue to open in a
	// new tab via the default <a> behaviour.
	const openInArtifactPanel = (event: MouseEvent, src: string, filename: string): void => {
		const entry = detectFileType(filename);
		const cap = entry?.capability ?? 'panel';
		if (cap === 'inline') return; // let the default new-tab behaviour run

		event.preventDefault();

		// Try to extract a platform file_id from /api/v1/files/{id}/content
		const fileMatch = src.match(/\/api\/v1\/files\/([^/]+)\/content/);
		if (fileMatch) {
			const fileId = fileMatch[1];
			openArtifactInPane({
				file_key: `file_id:${fileId}`,
				file_id: fileId,
				filename,
				source: 'user-click',
				mtime: Date.now()
			});
			return;
		}

		// Otherwise, treat as a hermes media path (?path=<encoded>)
		const pathMatch = src.match(/[?&]path=([^&]+)/);
		if (pathMatch) {
			const decoded = decodeURIComponent(pathMatch[1]);
			openArtifactInPane({
				file_key: `path:${decoded}`,
				path: decoded,
				filename,
				source: 'user-click',
				mtime: Date.now()
			});
			return;
		}

		// Unknown URL shape — fall back to opening in a new tab
		window.open(src, '_blank', 'noopener');
	};

	export let id: string;
	export let done = true;
	export let tokens: Token[];
	export let sourceIds = [];
	export let onSourceClick: Function = () => {};

	/**
	 * Check if a URL is a same-origin note link and return the note ID if so.
	 */
	const getNoteIdFromHref = (href: string): string | null => {
		try {
			const url = new URL(href, window.location.origin);
			if (url.origin === window.location.origin) {
				const match = url.pathname.match(/^\/notes\/([^/]+)$/);
				if (match) {
					return match[1];
				}
			}
		} catch {
			// Invalid URL
		}
		return null;
	};

	/**
	 * Handle link clicks - intercept same-origin app URLs for in-app navigation
	 */
	const handleLinkClick = (e: MouseEvent, href: string) => {
		try {
			const url = new URL(href, window.location.origin);
			// Check if same origin and an in-app route
			if (
				url.origin === window.location.origin &&
				(url.pathname.startsWith('/notes/') || url.pathname.startsWith('/c/'))
			) {
				e.preventDefault();
				goto(url.pathname + url.search + url.hash);
			}
		} catch {
			// Invalid URL, let browser handle it
		}
	};
</script>

{#each tokens as token, tokenIdx (tokenIdx)}
	{#if token.type === 'escape'}
		{unescapeHtml(token.text)}
	{:else if token.type === 'html'}
		<HtmlToken {id} {token} {onSourceClick} />
	{:else if token.type === 'link'}
		{@const noteId = getNoteIdFromHref(token.href)}
		{#if noteId}
			<NoteLinkToken {noteId} href={token.href} />
		{:else if token.tokens}
			<a
				href={token.href}
				target="_blank"
				rel="nofollow"
				title={token.title}
				on:click={(e) => handleLinkClick(e, token.href)}
			>
				<svelte:self id={`${id}-a`} tokens={token.tokens} {onSourceClick} {done} />
			</a>
		{:else}
			<a
				href={token.href}
				target="_blank"
				rel="nofollow"
				title={token.title}
				on:click={(e) => handleLinkClick(e, token.href)}>{token.text}</a
			>
		{/if}
	{:else if token.type === 'image'}
		<Image src={token.href} alt={token.text} />
	{:else if token.type === 'strong'}
		<strong><svelte:self id={`${id}-strong`} tokens={token.tokens} {onSourceClick} /></strong>
	{:else if token.type === 'em'}
		<em><svelte:self id={`${id}-em`} tokens={token.tokens} {onSourceClick} /></em>
	{:else if token.type === 'codespan'}
		<CodespanToken {token} {done} />
	{:else if token.type === 'br'}
		<br />
	{:else if token.type === 'del'}
		<del><svelte:self id={`${id}-del`} tokens={token.tokens} {onSourceClick} /></del>
	{:else if token.type === 'inlineKatex'}
		{#if token.text}
			<KatexRenderer content={token.text} displayMode={false} />
		{/if}
	{:else if token.type === 'iframe'}
		<iframe
			src="{WEBUI_BASE_URL}/api/v1/files/{token.fileId}/content"
			title={token.fileId}
			width="100%"
			frameborder="0"
			on:load={(e) => {
				try {
					e.currentTarget.style.height =
						e.currentTarget.contentWindow.document.body.scrollHeight + 20 + 'px';
				} catch {}
			}}
		></iframe>
	{:else if token.type === 'mention'}
		<MentionToken {token} />
	{:else if token.type === 'footnote'}
		{@html DOMPurify.sanitize(
			`<sup class="footnote-ref footnote-ref-text">${token.escapedText}</sup>`
		) || ''}
	{:else if token.type === 'citation'}
		{#if (sourceIds ?? []).length > 0}
			<SourceToken {id} {token} {sourceIds} onClick={onSourceClick} />
		{:else}
			<TextToken {token} {done} />
		{/if}
	{:else if token.type === 'media'}
		{@const mediaToken = token as any}
		{#if mediaToken.kind === 'image'}
			<div class="relative group inline-block">
				<Image src={mediaToken.src} alt={mediaToken.filename} />
				<a
					class="absolute top-1 right-1 opacity-0 group-hover:opacity-100 transition-opacity bg-black/50 rounded p-1 hidden sm:block"
					href={mediaToken.src}
					download={mediaToken.filename}
					title="Download"
					on:click|stopPropagation
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						class="w-4 h-4 text-white"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
					>
						<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
						<polyline points="7 10 12 15 17 10" />
						<line x1="12" y1="15" x2="12" y2="3" />
					</svg>
				</a>
			</div>
		{:else if mediaToken.kind === 'audio'}
			<audio controls preload="metadata" src={mediaToken.src} class="my-2 w-full max-w-md rounded"
			></audio>
		{:else if mediaToken.kind === 'video'}
			<video
				controls
				preload="metadata"
				src={mediaToken.src}
				class="my-2 w-full max-w-md rounded-lg"
			></video>
		{:else}
			<button
				type="button"
				class="inline-flex items-center gap-2 my-1 px-3 py-2 rounded-xl text-sm font-medium
					bg-gray-50 dark:bg-gray-800/60 border border-gray-200/70 dark:border-gray-700/60
					text-gray-800 dark:text-gray-100
					hover:bg-gray-100 dark:hover:bg-gray-750 hover:border-gray-300 dark:hover:border-gray-600
					transition shadow-sm"
				on:click={(e) => openInArtifactPanel(e, mediaToken.src, mediaToken.filename)}
				title={`Open ${mediaToken.filename} in artifact panel`}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 24 24"
					fill="currentColor"
					class="size-4 shrink-0 text-gray-500 dark:text-gray-400"
					aria-hidden="true"
				>
					<path
						fill-rule="evenodd"
						d="M5.625 1.5c-1.036 0-1.875.84-1.875 1.875v17.25c0 1.035.84 1.875 1.875 1.875h12.75c1.035 0 1.875-.84 1.875-1.875V12.75A3.75 3.75 0 0 0 16.5 9h-1.875a1.875 1.875 0 0 1-1.875-1.875V5.25A3.75 3.75 0 0 0 9 1.5H5.625Z"
						clip-rule="evenodd"
					/>
					<path
						d="M12.971 1.816A5.23 5.23 0 0 1 14.25 5.25v1.875c0 .207.168.375.375.375H16.5a5.23 5.23 0 0 1 3.434 1.279 9.768 9.768 0 0 0-6.963-6.963Z"
					/>
				</svg>
				<span class="truncate max-w-[28ch]">{mediaToken.filename}</span>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 20 20"
					fill="currentColor"
					class="size-3.5 shrink-0 text-gray-400 dark:text-gray-500"
					aria-hidden="true"
				>
					<path
						fill-rule="evenodd"
						d="M5 10a.75.75 0 0 1 .75-.75h6.638L10.23 7.29a.75.75 0 1 1 1.04-1.08l3.5 3.25a.75.75 0 0 1 0 1.08l-3.5 3.25a.75.75 0 1 1-1.04-1.08l2.158-1.96H5.75A.75.75 0 0 1 5 10Z"
						clip-rule="evenodd"
					/>
				</svg>
			</button>
		{/if}
	{:else if token.type === 'text'}
		<TextToken {token} {done} />
	{/if}
{/each}
