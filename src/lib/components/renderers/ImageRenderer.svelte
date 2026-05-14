<script lang="ts">
	import { onMount, createEventDispatcher } from 'svelte';
	import panzoom, { type PanZoom } from 'panzoom';
	import { MYAH_API_BASE_URL } from '$lib/constants';
	import { artifactSelection } from '$lib/stores';
	import ArtifactFallback from './ArtifactFallback.svelte';
	import SelectionToolbar from '$lib/components/chat/Artifacts/SelectionToolbar.svelte';
	import type { ToolbarItem, SelectionPayload } from '$lib/types/artifact';

	export let content: Blob | string | undefined = undefined;
	export let filename: string;
	export let mime: string | undefined = undefined;
	export let file_id: string | undefined = undefined;
	export let path: string | undefined = undefined;
	export let editable = false;

	// Suppress unused-prop warnings for Renderer Contract props.
	$: void [mime, editable];

	const dispatch = createEventDispatcher<{
		select: SelectionPayload | null;
		toolbar: { items: ToolbarItem[] };
		error: Error;
	}>();

	// Resolution priority (mirrors the CodeRenderer fix from Phase 2A — `content: string`
	// is treated as a file_id for backwards compat; new callers pass file_id explicitly).
	$: src = file_id
		? `${MYAH_API_BASE_URL}/files/${file_id}/content`
		: path
			? `${MYAH_API_BASE_URL}/hermes/media?path=${encodeURIComponent(path)}`
			: content instanceof Blob
				? URL.createObjectURL(content)
				: typeof content === 'string'
					? `${MYAH_API_BASE_URL}/files/${content}/content`
					: '';

	let pzInstance: PanZoom | null = null;
	let errorObj: Error | null = null;
	// Bumping this re-mounts the <img>, which is how we retry a failed load.
	let reloadKey = 0;

	// Mode toggle: 'move' (panzoom owns mouse events) vs 'select' (region overlay
	// captures events). Default is 'move' so first-time users get the expected
	// pan/zoom behaviour and never see a stray pink rectangle. Switching to
	// 'select' is an explicit toolbar action.
	let mode: 'move' | 'select' = 'move';

	// Region drag state — coordinates are stored in PERCENTAGES of the image's
	// natural rendered size, so the rectangle anchors to image content and
	// transforms correctly when panzoom scales/translates the wrapper.
	let imageWrapperEl: HTMLElement;
	let isDragging = false;
	// Drag start/end as fractions of the wrapper's CURRENT rendered size — the
	// math reverses panzoom's transform so the rectangle stays glued to the
	// image content even after zoom/pan.
	let dragStartXPct = 0;
	let dragStartYPct = 0;
	let dragEndXPct = 0;
	let dragEndYPct = 0;
	let lastRegionPct: {
		left: number; // %
		top: number; // %
		width: number; // %
		height: number; // %
	} | null = null;
	// Screen-coordinate rect of the staged region — passed to SelectionToolbar
	// so it can position itself directly above the selection. The toolbar is
	// `position: fixed`, which means viewport coords (i.e. raw
	// `getBoundingClientRect()` values) are correct.
	let toolbarAnchorRect: DOMRect | null = null;

	// When the global selection store clears (e.g. SelectionToolbar dismisses
	// it after "+ Add to chat"), drop the staged rectangle so it doesn't
	// linger on the canvas next to a non-existent chip.
	$: if ($artifactSelection === null) {
		lastRegionPct = null;
		toolbarAnchorRect = null;
	}

	const initImagePanzoom = (node: HTMLElement) => {
		pzInstance = panzoom(node, {
			bounds: true,
			boundsPadding: 0.1,
			zoomSpeed: 0.065
		});
	};

	const resetImageView = () => {
		if (pzInstance) {
			pzInstance.moveTo(0, 0);
			pzInstance.zoomAbs(0, 0, 1);
		}
	};

	const zoomIn = () => {
		pzInstance?.smoothZoom(0, 0, 1.5);
	};

	const zoomOut = () => {
		pzInstance?.smoothZoom(0, 0, 1 / 1.5);
	};

	const handleError = () => {
		errorObj = new Error(`Failed to load image: ${filename}`);
		dispatch('error', errorObj);
	};

	const reload = () => {
		errorObj = null;
		reloadKey += 1;
	};

	// Convert client-space coordinates into a percentage of the image wrapper's
	// CURRENT bounding box. Because the wrapper is the panzoomed element,
	// `getBoundingClientRect()` reflects the current zoom + pan, so a fixed
	// percentage maps to a fixed point on the image regardless of transform.
	// That makes the selection rectangle anchor to the image content rather
	// than the screen.
	function clientToWrapperPct(clientX: number, clientY: number): { x: number; y: number } | null {
		if (!imageWrapperEl) return null;
		const rect = imageWrapperEl.getBoundingClientRect();
		if (rect.width === 0 || rect.height === 0) return null;
		return {
			x: ((clientX - rect.left) / rect.width) * 100,
			y: ((clientY - rect.top) / rect.height) * 100
		};
	}

	function onOverlayMouseDown(e: MouseEvent) {
		if (mode !== 'select') return;
		const pct = clientToWrapperPct(e.clientX, e.clientY);
		if (!pct) return;
		// Stop the event so panzoom (parent listener) never sees it — keeps the
		// image still while the user drags out a selection.
		e.stopPropagation();
		e.preventDefault();
		dragStartXPct = pct.x;
		dragStartYPct = pct.y;
		dragEndXPct = pct.x;
		dragEndYPct = pct.y;
		isDragging = true;
	}

	function onOverlayMouseMove(e: MouseEvent) {
		if (!isDragging) return;
		const pct = clientToWrapperPct(e.clientX, e.clientY);
		if (!pct) return;
		dragEndXPct = Math.max(0, Math.min(100, pct.x));
		dragEndYPct = Math.max(0, Math.min(100, pct.y));
	}

	function onOverlayMouseUp() {
		if (!isDragging) return;
		isDragging = false;
		const startX = Math.min(dragStartXPct, dragEndXPct);
		const endX = Math.max(dragStartXPct, dragEndXPct);
		const startY = Math.min(dragStartYPct, dragEndYPct);
		const endY = Math.max(dragStartYPct, dragEndYPct);
		const wPct = endX - startX;
		const hPct = endY - startY;
		// Sub-1% drag → treat as a click. Cancel any prior staged selection
		// instead of leaving a stale toolbar floating with no rectangle.
		// The reactive on `$artifactSelection === null` clears
		// `lastRegionPct` and `toolbarAnchorRect`, so the canvas returns to
		// a clean state.
		if (wPct < 1 || hPct < 1) {
			artifactSelection.set(null);
			return;
		}
		lastRegionPct = { left: startX, top: startY, width: wPct, height: hPct };
		const payload: SelectionPayload = {
			kind: 'image-region',
			anchor: { xPct: startX, yPct: startY, wPct, hPct },
			preview: { dataUrl: '' },
			summary: `${wPct.toFixed(0)}% × ${hPct.toFixed(0)}% region`
		};
		dispatch('select', payload);
		// 2026-05-05 dogfooding: belt-and-suspenders direct store write — see
		// CodeRenderer for rationale.
		artifactSelection.set(payload);

		// Compute the screen-coord rect of the staged region so the
		// SelectionToolbar (position: fixed) can dock directly above it.
		if (imageWrapperEl) {
			const r = imageWrapperEl.getBoundingClientRect();
			const left = r.left + (startX / 100) * r.width;
			const top = r.top + (startY / 100) * r.height;
			const right = r.left + (endX / 100) * r.width;
			const bottom = r.top + (endY / 100) * r.height;
			toolbarAnchorRect = {
				top,
				left,
				right,
				bottom,
				width: right - left,
				height: bottom - top,
				x: left,
				y: top,
				toJSON: () => ''
			} as DOMRect;
		}
	}

	function setMode(next: 'move' | 'select') {
		mode = next;
		if (next === 'move') {
			// Leaving select mode clears the staged rectangle so it doesn't
			// linger as a ghost when the user pans the image.
			lastRegionPct = null;
			isDragging = false;
		}
		emitToolbar();
	}

	function emitToolbar() {
		dispatch('toolbar', {
			items: [
				{
					placement: 'overlay-tr',
					id: 'mode-move',
					label: mode === 'move' ? 'Move (active)' : 'Move',
					onClick: () => setMode('move')
				},
				{
					placement: 'overlay-tr',
					id: 'mode-select',
					label: mode === 'select' ? 'Select (active)' : 'Select region',
					onClick: () => setMode('select')
				},
				{ placement: 'overlay-tr', id: 'reset-zoom', label: 'Reset view', onClick: resetImageView },
				{ placement: 'overlay-tr', id: 'zoom-in', label: 'Zoom in', onClick: zoomIn },
				{ placement: 'overlay-tr', id: 'zoom-out', label: 'Zoom out', onClick: zoomOut }
			]
		});
	}

	onMount(() => {
		emitToolbar();
		return () => {
			pzInstance?.dispose();
		};
	});
</script>

{#if errorObj}
	<ArtifactFallback
		error={errorObj}
		{filename}
		file_id={typeof content === 'string' ? content : file_id}
		{path}
		onRetry={reload}
	/>
{:else}
	<div
		data-testid="image-canvas"
		class="bg-gray-900 dark:bg-black h-full w-full overflow-hidden relative"
	>
		<!--
			Mode toolbar — visible always, top-right of the canvas, on a higher
			z-layer than the panzoom wrapper. Two buttons toggle move/select; the
			zoom triplet is always available.
		-->
		<div
			data-testid="image-mode-toolbar"
			class="absolute top-2 right-2 z-20 flex items-center gap-1 rounded-lg bg-black/60 backdrop-blur-sm px-1 py-1 text-white"
		>
			<button
				type="button"
				data-testid="image-mode-move"
				class="px-2 py-1 text-xs rounded {mode === 'move'
					? 'bg-white/25'
					: 'hover:bg-white/10'}"
				title="Move / pan / zoom"
				on:click={() => setMode('move')}
			>
				Move
			</button>
			<button
				type="button"
				data-testid="image-mode-select"
				class="px-2 py-1 text-xs rounded {mode === 'select'
					? 'bg-white/25'
					: 'hover:bg-white/10'}"
				title="Select region to send to chat"
				on:click={() => setMode('select')}
			>
				Select
			</button>
			<span class="mx-1 h-4 w-px bg-white/20"></span>
			<button
				type="button"
				class="px-2 py-1 text-xs rounded hover:bg-white/10"
				on:click={zoomOut}
				title="Zoom out"
			>
				−
			</button>
			<button
				type="button"
				class="px-2 py-1 text-xs rounded hover:bg-white/10"
				on:click={resetImageView}
				title="Reset view"
			>
				↺
			</button>
			<button
				type="button"
				class="px-2 py-1 text-xs rounded hover:bg-white/10"
				on:click={zoomIn}
				title="Zoom in"
			>
				+
			</button>
		</div>

		{#key reloadKey}
			<div use:initImagePanzoom class="w-full h-full flex items-center justify-center">
				<!--
					The wrapper here is the element panzoom transforms. We bind to it so
					selection rectangle math can express coords as PERCENTAGES of this
					element's current bounding box — making the rectangle "stick" to the
					image content while panzoom translates/scales the wrapper.
				-->
				<div
					bind:this={imageWrapperEl}
					data-testid="image-region-overlay"
					class="relative inline-block"
					on:mousedown={onOverlayMouseDown}
					on:mousemove={onOverlayMouseMove}
					on:mouseup={onOverlayMouseUp}
					on:mouseleave={onOverlayMouseUp}
					role="presentation"
				>
					<img
						{src}
						alt={filename}
						class="max-w-full max-h-full object-contain block"
						style={mode === 'select' ? 'cursor: crosshair;' : 'cursor: grab;'}
						loading="lazy"
						draggable="false"
						on:error={handleError}
					/>
					{#if mode === 'select' && isDragging}
						<div
							data-testid="image-region-rect"
							class="absolute border-2 border-pink-500 bg-pink-500/10 pointer-events-none"
							style="left: {Math.min(dragStartXPct, dragEndXPct)}%; top: {Math.min(
								dragStartYPct,
								dragEndYPct
							)}%; width: {Math.abs(dragEndXPct - dragStartXPct)}%; height: {Math.abs(
								dragEndYPct - dragStartYPct
							)}%;"
						></div>
					{:else if mode === 'select' && lastRegionPct}
						<div
							data-testid="image-region-rect"
							class="absolute border-2 border-pink-500 bg-pink-500/10 pointer-events-none"
							style="left: {lastRegionPct.left}%; top: {lastRegionPct.top}%; width: {lastRegionPct.width}%; height: {lastRegionPct.height}%;"
						></div>
					{/if}
				</div>
			</div>
		{/key}
		<!--
			Floating selection toolbar — only visible while $artifactSelection
			is non-null AND the user is on this renderer. Positioned with
			anchorRect (screen coords). Without this, the user's drag-to-region
			completes silently and the "+ Add to chat" affordance never appears.
		-->
		<SelectionToolbar placement="floating" anchorRect={toolbarAnchorRect} {filename} />
	</div>
{/if}
