<script lang="ts">
	import { onMount, createEventDispatcher } from 'svelte';
	import DOMPurify from 'dompurify';
	import { MYAH_API_BASE_URL } from '$lib/constants';
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

	// Surface props the host doesn't read; declared so Svelte doesn't warn.
	$$restProps;
	void mime;
	void editable;

	const dispatch = createEventDispatcher<{
		select: SelectionPayload | null;
		toolbar: { items: ToolbarItem[] };
		error: Error;
	}>();

	let html = '';
	let errorObj: Error | null = null;
	let loading = true;
	let useDocxPreview = false;
	let card: HTMLElement;
	let toolbarAnchorRect: DOMRect | null = null;

	// Clear the local anchor rect when the global selection store is reset.
	$: if ($artifactSelection === null) toolbarAnchorRect = null;

	const load = async () => {
		loading = true;
		errorObj = null;
		try {
			let arrayBuffer: ArrayBuffer;
			if (content instanceof Blob) {
				arrayBuffer = await content.arrayBuffer();
			} else {
				const fileId = typeof content === 'string' ? content : file_id;
				if (!fileId) throw new Error('No file_id, path, or Blob content');
				const res = await fetch(`${MYAH_API_BASE_URL}/files/${fileId}/content`, {
					credentials: 'include'
				});
				if (!res.ok) throw new Error(`HTTP ${res.status}`);
				arrayBuffer = await res.arrayBuffer();
			}

			if (useDocxPreview) {
				// High-fidelity render via docx-preview. Lazy-imported (~600KB) so
				// users who never toggle never pay for it. We need the paper card
				// element to exist before docx-preview can write into it; setting
				// `html` non-empty lets the {#if html} block render the card on
				// the next tick, then we wait one frame and inject.
				html = '__docx_preview__';
				loading = false;
				await new Promise((r) => requestAnimationFrame(r));
				if (card) {
					card.innerHTML = '';
					const blob = content instanceof Blob ? content : new Blob([arrayBuffer]);
					const { renderAsync } = await import('docx-preview');
					await renderAsync(blob, card, undefined, {
						inWrapper: false,
						ignoreWidth: false,
						ignoreHeight: false
					});
				}
				return;
			}

			const mammoth = await import('mammoth');
			const result = await mammoth.convertToHtml({ arrayBuffer });
			html = DOMPurify.sanitize(result.value);
		} catch (e) {
			console.error('Error loading DOCX file:', e);
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
					id: 'docx-fidelity',
					label: useDocxPreview ? 'Standard view' : 'High fidelity',
					onClick: () => {
						useDocxPreview = !useDocxPreview;
						dispatchToolbar();
						load();
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
		const text = range.toString();
		if (!text.trim()) {
			dispatch('select', null);
			artifactSelection.set(null);
			toolbarAnchorRect = null;
			return;
		}
		const cardText = card?.innerText ?? '';
		const startOffset = cardText.indexOf(text);
		const endOffset = startOffset + text.length;
		const fp =
			cardText.slice(Math.max(0, startOffset - 50), startOffset) +
			'|' +
			cardText.slice(endOffset, endOffset + 50);
		const wordCount = text.trim().split(/\s+/).length;
		const paraCount = text.split(/\n+/).filter((p) => p.trim()).length;
		const payload: SelectionPayload = {
			kind: 'doc-text',
			anchor: { startOffset, endOffset, contextFingerprint: fp },
			preview: text.slice(0, 200),
			summary: `${paraCount} paragraph${paraCount === 1 ? '' : 's'} · ${wordCount} word${wordCount === 1 ? '' : 's'}`
		};
		dispatch('select', payload);
		// 2026-05-05 dogfooding: write the store directly — see CodeRenderer
		// for the rationale (Svelte 5 <svelte:component> event forwarding is
		// fragile, so the host doesn't always receive the dispatch).
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
{:else if html}
	<div class="bg-gray-50 dark:bg-gray-900 h-full overflow-auto py-8 relative">
		<!-- svelte-ignore a11y-no-static-element-interactions -->
		<div
			data-testid="docx-paper-card"
			data-listens-for-selection="true"
			bind:this={card}
			on:mouseup={handleTextSelection}
			role="document"
			class="mx-auto max-w-[640px] bg-white dark:bg-gray-850 shadow-md p-14 prose dark:prose-invert font-serif"
		>
			{#if !useDocxPreview}
				{@html html}
			{/if}
			<!-- when useDocxPreview is true, load() injects via card.innerHTML -->
		</div>
		<SelectionToolbar placement="floating" anchorRect={toolbarAnchorRect} {filename} />
	</div>
{:else}
	<div class="text-gray-500 text-sm p-4">No content available</div>
{/if}
