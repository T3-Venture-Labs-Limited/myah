<script lang="ts">
	// Where the selection is, the toolbar follows; where there is none,
	// it disappears, leaving the page as it was.
	import { onMount, onDestroy } from 'svelte';
	import { artifactSelection, composerRefs } from '$lib/stores';
	import { computeFloatingPosition } from '$lib/utils/floatingPosition';

	export let placement: 'floating' | 'bottom-strip' = 'floating';
	// The renderer passes the bounding rect of the selection so the toolbar
	// can position itself when placement === 'floating'. Ignored for 'bottom-strip'.
	export let anchorRect: DOMRect | null = null;
	// Source filename — surfaced into the composer ref chip so the user can
	// see which file each chip points back to. Defaults to '' so older
	// callers don't break, but every renderer should pass it.
	export let filename: string = '';

	let toolbarEl: HTMLElement;
	let pos: { top: number; left: number } | null = null;

	// 2026-05-05 dogfooding: dismiss the selection (and therefore the
	// toolbar) on Escape. The listener lives only as long as
	// `$artifactSelection` is truthy because this component is gated by
	// {#if $artifactSelection}, so the global keydown is bounded by the
	// selection's own lifetime.
	function onKeyDown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			artifactSelection.set(null);
		}
	}

	function cancelSelection() {
		artifactSelection.set(null);
	}

	onMount(() => {
		if (typeof window !== 'undefined') {
			window.addEventListener('keydown', onKeyDown);
		}
	});

	onDestroy(() => {
		if (typeof window !== 'undefined') {
			window.removeEventListener('keydown', onKeyDown);
		}
	});

	$: if (placement === 'floating' && anchorRect && toolbarEl && typeof window !== 'undefined') {
		pos = computeFloatingPosition({
			anchor: anchorRect,
			toolbar: { width: toolbarEl.offsetWidth || 280, height: toolbarEl.offsetHeight || 36 },
			viewport: { width: window.innerWidth, height: window.innerHeight },
			padding: 8
		});
	} else if (placement !== 'floating' || !anchorRect) {
		pos = null;
	}

	function addToChat() {
		if (!$artifactSelection) return;
		const id = `ref-${Date.now()}-${Math.random().toString(36).slice(2)}`;
		composerRefs.update((refs) => [...refs, { ...$artifactSelection!, id, filename }]);
		artifactSelection.set(null);
	}

	async function copyPreview() {
		if (!$artifactSelection || typeof navigator === 'undefined') return;
		const sel = $artifactSelection;
		let text = '';
		switch (sel.kind) {
			case 'doc-text':
			case 'code-lines':
				text = sel.preview;
				break;
			case 'sheet-cells':
				text = sel.preview.map((row) => row.join('\t')).join('\n');
				break;
			case 'image-region':
				text = sel.preview.dataUrl;
				break;
			case 'video-region':
				text = sel.summary;
				break;
		}
		try {
			await navigator.clipboard.writeText(text);
		} catch (e) {
			console.warn('Clipboard write failed:', e);
		}
	}
</script>

{#if $artifactSelection}
	<!--
		2026-05-05 dogfooding: positioned `fixed` (viewport-relative) — NOT
		`absolute`. The anchor rect comes from `getBoundingClientRect()` which
		returns viewport coordinates; combining viewport coords with
		`position: absolute` inside a `position: relative` ancestor (every
		renderer wrapper has one) produced a double-offset where the toolbar
		ended up squeezed against the right edge of the viewport — exactly
		what the user reported. `fixed` makes the coords match.
		`whitespace-nowrap` and `min-w-fit` keep the buttons on one line so
		the toolbar can't get squashed into a narrow column when its
		positioning ancestor has limited width.
	-->
	<div
		bind:this={toolbarEl}
		data-testid="selection-toolbar"
		class="bg-gray-900 dark:bg-gray-50 text-white dark:text-gray-900 rounded-xl shadow-lg px-3 py-1.5 flex items-center gap-3 text-sm whitespace-nowrap min-w-fit
			{placement === 'floating' ? 'fixed z-50' : 'w-full'}"
		style={placement === 'floating' && pos ? `top:${pos.top}px;left:${pos.left}px` : ''}
	>
		<span class="text-xs opacity-80">{$artifactSelection.summary}</span>
		<button
			type="button"
			data-testid="selection-toolbar-add"
			class="bg-pink-500 text-white px-2 py-1 rounded text-xs"
			on:click={addToChat}
		>
			+ Add to chat
		</button>
		<button
			type="button"
			data-testid="selection-toolbar-copy"
			class="bg-transparent text-white dark:text-gray-900 px-2 py-1 rounded text-xs hover:bg-white/10"
			on:click={copyPreview}
		>
			Copy
		</button>
		<button
			type="button"
			data-testid="selection-toolbar-cancel"
			title="Cancel selection (Esc)"
			aria-label="Cancel selection"
			class="bg-transparent text-white/80 dark:text-gray-700 px-1.5 py-1 rounded text-xs hover:bg-white/10 dark:hover:bg-gray-200"
			on:click={cancelSelection}
		>
			✕
		</button>
	</div>
{/if}
