<script lang="ts">
	import { onMount, createEventDispatcher } from 'svelte';
	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';
	import { WEBUI_API_BASE_URL } from '$lib/constants';
	import ArtifactFallback from './ArtifactFallback.svelte';
	import SelectionToolbar from '$lib/components/chat/Artifacts/SelectionToolbar.svelte';
	import { artifactSelection } from '$lib/stores';
	import type { ToolbarItem, SelectionPayload } from '$lib/types/artifact';

	export let content: Blob | string;
	export let filename: string;
	export let mime: string | undefined = undefined;
	export let file_id: string | undefined = undefined;
	export let path: string | undefined = undefined;
	export let editable = false;

	void mime;
	void editable;

	const dispatch = createEventDispatcher<{
		select: SelectionPayload | null;
		toolbar: { items: ToolbarItem[] };
		error: Error;
	}>();

	let text = '';
	let errorObj: Error | null = null;
	let loading = true;
	let card: HTMLElement;
	let toolbarAnchorRect: DOMRect | null = null;

	$: if ($artifactSelection === null) toolbarAnchorRect = null;

	const load = async () => {
		loading = true;
		errorObj = null;
		try {
			if (content instanceof Blob) {
				text = await content.text();
			} else if (typeof content === 'string') {
				const res = await fetch(`${WEBUI_API_BASE_URL}/files/${content}/content`, {
					credentials: 'include'
				});
				if (!res.ok) throw new Error(`HTTP ${res.status}`);
				text = await res.text();
			}
		} catch (e) {
			console.error('Error loading Markdown file:', e);
			errorObj = e instanceof Error ? e : new Error(String(e));
			dispatch('error', errorObj);
		} finally {
			loading = false;
		}
	};

	function dispatchToolbar() {
		dispatch('toolbar', {
			items: [
				{
					placement: 'top',
					id: 'md-show-source',
					label: 'Show source',
					onClick: () => {
						// Source-toggle implementation lands in Phase 2C.
						console.log('[MarkdownRenderer] show-source toggle (impl pending)');
					}
				}
			]
		});
	}

	function handleTextSelection() {
		if (typeof window === 'undefined') return;
		const sel = window.getSelection();
		if (!sel || sel.rangeCount === 0 || sel.isCollapsed) {
			dispatch('select', null);
			artifactSelection.set(null);
			toolbarAnchorRect = null;
			return;
		}
		const range = sel.getRangeAt(0);
		const selText = range.toString();
		if (!selText.trim()) {
			dispatch('select', null);
			artifactSelection.set(null);
			toolbarAnchorRect = null;
			return;
		}
		const cardText = card?.innerText ?? '';
		const startOffset = cardText.indexOf(selText);
		const endOffset = startOffset + selText.length;
		const fp =
			cardText.slice(Math.max(0, startOffset - 50), startOffset) +
			'|' +
			cardText.slice(endOffset, endOffset + 50);
		const wordCount = selText.trim().split(/\s+/).length;
		const paraCount = selText.split(/\n+/).filter((p) => p.trim()).length;
		const payload: SelectionPayload = {
			kind: 'doc-text',
			anchor: { startOffset, endOffset, contextFingerprint: fp },
			preview: selText.slice(0, 200),
			summary: `${paraCount} paragraph${paraCount === 1 ? '' : 's'} · ${wordCount} word${wordCount === 1 ? '' : 's'}`
		};
		dispatch('select', payload);
		// 2026-05-05 dogfooding: write the store directly — see CodeRenderer
		// for the full rationale (Svelte 5 <svelte:component on:event>
		// forwarding is fragile, so we don't rely on it).
		artifactSelection.set(payload);
		toolbarAnchorRect = range.getBoundingClientRect();
	}

	onMount(() => {
		load();
		dispatchToolbar();
	});
</script>

{#if loading}
	<div class="flex items-center justify-center py-8 text-sm text-gray-500">Loading…</div>
{:else if errorObj}
	<ArtifactFallback
		error={errorObj}
		{filename}
		file_id={typeof content === 'string' ? content : file_id}
		{path}
		onRetry={load}
	/>
{:else}
	<div class="bg-gray-50 dark:bg-gray-900 h-full overflow-auto py-8 relative">
		<!-- svelte-ignore a11y-no-static-element-interactions -->
		<div
			data-testid="md-paper-card"
			data-listens-for-selection="true"
			bind:this={card}
			on:mouseup={handleTextSelection}
			role="document"
			class="mx-auto max-w-[640px] bg-white dark:bg-gray-850 shadow-md p-14 prose dark:prose-invert"
		>
			<Markdown content={text} id="markdown-renderer-{filename}" />
		</div>
		<SelectionToolbar placement="floating" anchorRect={toolbarAnchorRect} {filename} />
	</div>
{/if}
