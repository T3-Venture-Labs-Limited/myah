<script lang="ts">
	// Time becomes a place: a strip the user can scrub, drag, and pin context to.
	// A second handle on the video frame itself captures spatial regions —
	// which actor, which corner of the shot — so an anchor can carry both
	// "when" and "where" back to the agent.
	import { onMount, createEventDispatcher } from 'svelte';
	import { WEBUI_API_BASE_URL } from '$lib/constants';
	import { artifactSelection } from '$lib/stores';
	import ArtifactFallback from './ArtifactFallback.svelte';
	import SelectionToolbar from '$lib/components/chat/Artifacts/SelectionToolbar.svelte';
	import type { ToolbarItem, SelectionPayload, VideoRegionAnchor } from '$lib/types/artifact';

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

	$: src = file_id
		? `${WEBUI_API_BASE_URL}/files/${file_id}/content`
		: path
			? `${WEBUI_API_BASE_URL}/hermes/media?path=${encodeURIComponent(path)}`
			: content instanceof Blob
				? URL.createObjectURL(content)
				: typeof content === 'string'
					? `${WEBUI_API_BASE_URL}/files/${content}/content`
					: '';

	let videoEl: HTMLVideoElement;
	let videoFrameEl: HTMLElement;
	let timelineEl: HTMLElement;
	let isPlaying = false;
	let currentTime = 0;
	let duration = 0;
	let errorObj: Error | null = null;
	let reloadKey = 0;

	// Mode toggle for the video frame — Move (default; click anywhere to
	// play/pause, no spatial selection) vs Select (drag on frame to capture
	// a spatial region at the current playhead). The timeline is always
	// drag-to-range regardless of mode, mirroring how every video editor
	// treats the timeline as a separate input surface.
	let mode: 'move' | 'select' = 'move';

	// ── Timeline drag state (time-range selection) ──────────────────────
	let isTimelineDragging = false;
	let timelineDragStartPx = 0;
	let timelineDragEndPx = 0;
	let regionStartSec: number | null = null;
	let regionEndSec: number | null = null;

	// ── Frame drag state (spatial-region selection) ─────────────────────
	let isFrameDragging = false;
	let frameDragStartXPct = 0;
	let frameDragStartYPct = 0;
	let frameDragEndXPct = 0;
	let frameDragEndYPct = 0;
	let lastFrameRegionPct: {
		left: number;
		top: number;
		width: number;
		height: number;
	} | null = null;
	// The timestamp the spatial region was captured at — anchors the bbox
	// to a moment in the video so the agent gets both "where" and "when".
	let frameRegionAtSec: number | null = null;

	// Floating SelectionToolbar's screen-coord anchor.
	let toolbarAnchorRect: DOMRect | null = null;

	// Clear stale visuals when the global selection store resets.
	$: if ($artifactSelection === null) {
		regionStartSec = null;
		regionEndSec = null;
		lastFrameRegionPct = null;
		frameRegionAtSec = null;
		toolbarAnchorRect = null;
	}

	function fmtTime(sec: number): string {
		if (!Number.isFinite(sec) || sec < 0) return '0:00';
		const m = Math.floor(sec / 60);
		const s = Math.floor(sec % 60);
		return `${m}:${s.toString().padStart(2, '0')}`;
	}

	function togglePlay() {
		if (!videoEl) return;
		if (videoEl.paused) videoEl.play();
		else videoEl.pause();
	}

	function onLoadedMetadata() {
		duration = videoEl?.duration ?? 0;
	}

	function onTimeUpdate() {
		currentTime = videoEl?.currentTime ?? 0;
	}

	// ── Timeline (always active; works in both modes) ───────────────────

	function onTimelineDown(e: MouseEvent) {
		if (!timelineEl) return;
		const rect = timelineEl.getBoundingClientRect();
		timelineDragStartPx = e.clientX - rect.left;
		timelineDragEndPx = timelineDragStartPx;
		isTimelineDragging = true;
	}

	function onTimelineMove(e: MouseEvent) {
		if (!isTimelineDragging || !timelineEl) return;
		const rect = timelineEl.getBoundingClientRect();
		timelineDragEndPx = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
	}

	function onTimelineUp() {
		if (!isTimelineDragging || !timelineEl) {
			isTimelineDragging = false;
			return;
		}
		const rect = timelineEl.getBoundingClientRect();
		isTimelineDragging = false;
		const startPx = Math.min(timelineDragStartPx, timelineDragEndPx);
		const endPx = Math.max(timelineDragStartPx, timelineDragEndPx);
		// Sub-4px drag → treat as a click → seek instead of select.
		// Also clear any prior staged selection so the toolbar doesn't
		// linger after a navigation gesture.
		if (Math.abs(endPx - startPx) < 4) {
			const sec = (startPx / rect.width) * duration;
			if (videoEl) videoEl.currentTime = sec;
			artifactSelection.set(null);
			return;
		}
		const startSec = (startPx / rect.width) * duration;
		const endSec = (endPx / rect.width) * duration;
		regionStartSec = startSec;
		regionEndSec = endSec;
		// A new timeline-range selection supersedes any prior frame-region
		// selection so the chip the user adds to chat reflects only what
		// they last drew.
		lastFrameRegionPct = null;
		frameRegionAtSec = null;
		emitVideoSelect();
		// Anchor the floating toolbar above the selected timeline range.
		toolbarAnchorRect = {
			top: rect.top,
			bottom: rect.bottom,
			left: rect.left + startPx,
			right: rect.left + endPx,
			width: endPx - startPx,
			height: rect.height,
			x: rect.left + startPx,
			y: rect.top,
			toJSON: () => ''
		} as DOMRect;
	}

	// ── Video-frame drag (only active when mode === 'select') ───────────

	function frameClientToPct(clientX: number, clientY: number): { x: number; y: number } | null {
		if (!videoFrameEl) return null;
		const rect = videoFrameEl.getBoundingClientRect();
		if (rect.width === 0 || rect.height === 0) return null;
		return {
			x: ((clientX - rect.left) / rect.width) * 100,
			y: ((clientY - rect.top) / rect.height) * 100
		};
	}

	function onFrameMouseDown(e: MouseEvent) {
		if (mode !== 'select') return;
		// If the click landed on the <video> element, we still want to capture
		// the drag — but we have to stop the default click-to-play behaviour.
		e.preventDefault();
		e.stopPropagation();
		const pct = frameClientToPct(e.clientX, e.clientY);
		if (!pct) return;
		frameDragStartXPct = pct.x;
		frameDragStartYPct = pct.y;
		frameDragEndXPct = pct.x;
		frameDragEndYPct = pct.y;
		isFrameDragging = true;
	}

	function onFrameMouseMove(e: MouseEvent) {
		if (!isFrameDragging) return;
		const pct = frameClientToPct(e.clientX, e.clientY);
		if (!pct) return;
		frameDragEndXPct = Math.max(0, Math.min(100, pct.x));
		frameDragEndYPct = Math.max(0, Math.min(100, pct.y));
	}

	function onFrameMouseUp() {
		if (!isFrameDragging) return;
		isFrameDragging = false;
		const startX = Math.min(frameDragStartXPct, frameDragEndXPct);
		const endX = Math.max(frameDragStartXPct, frameDragEndXPct);
		const startY = Math.min(frameDragStartYPct, frameDragEndYPct);
		const endY = Math.max(frameDragStartYPct, frameDragEndYPct);
		const wPct = endX - startX;
		const hPct = endY - startY;
		// Sub-1% drag → treat as a click. Cancel any prior staged selection
		// so the toolbar disappears alongside the rectangle. The reactive on
		// `$artifactSelection === null` clears all renderer-local visual
		// state.
		if (wPct < 1 || hPct < 1) {
			artifactSelection.set(null);
			return;
		}
		lastFrameRegionPct = { left: startX, top: startY, width: wPct, height: hPct };
		frameRegionAtSec = currentTime;
		// Frame-region selection supersedes any prior timeline-range pick —
		// only the most recent intent goes into the chip.
		regionStartSec = currentTime;
		regionEndSec = currentTime;
		emitVideoSelect();
		// Anchor the toolbar to the staged rect (in screen coords).
		if (videoFrameEl) {
			const r = videoFrameEl.getBoundingClientRect();
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

	// ── SelectionPayload assembly + dispatch ────────────────────────────

	function emitVideoSelect() {
		if (regionStartSec === null || regionEndSec === null) return;
		const anchor: VideoRegionAnchor = {
			startSeconds: regionStartSec,
			endSeconds: regionEndSec
		};
		const summaryParts: string[] = [];
		if (regionStartSec === regionEndSec) {
			// Pure spatial selection at a single moment.
			summaryParts.push(`@ ${fmtTime(regionStartSec)}`);
		} else {
			summaryParts.push(
				`${fmtTime(regionStartSec)} → ${fmtTime(regionEndSec)} · ${(regionEndSec - regionStartSec).toFixed(1)}s`
			);
		}
		if (lastFrameRegionPct) {
			anchor.xPct = lastFrameRegionPct.left;
			anchor.yPct = lastFrameRegionPct.top;
			anchor.wPct = lastFrameRegionPct.width;
			anchor.hPct = lastFrameRegionPct.height;
			summaryParts.push(
				`region ${lastFrameRegionPct.width.toFixed(0)}% × ${lastFrameRegionPct.height.toFixed(0)}%`
			);
		}
		const payload: SelectionPayload = {
			kind: 'video-region',
			anchor,
			preview: { thumbnailDataUrl: '' },
			summary: summaryParts.join(' · ')
		};
		dispatch('select', payload);
		// Belt-and-suspenders direct write — see CodeRenderer for rationale.
		artifactSelection.set(payload);
	}

	function setMode(next: 'move' | 'select') {
		mode = next;
		if (next === 'move') {
			// Leaving select mode clears any staged frame rectangle so it
			// doesn't ghost over the canvas.
			lastFrameRegionPct = null;
			frameRegionAtSec = null;
			isFrameDragging = false;
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
				{ placement: 'overlay-tr', id: 'video-pip', label: 'Picture in picture' },
				{ placement: 'overlay-tr', id: 'video-fullscreen', label: 'Fullscreen' }
			]
		});
	}

	function handleError() {
		errorObj = new Error(`Failed to load video: ${filename}`);
		dispatch('error', errorObj);
	}

	function reload() {
		errorObj = null;
		reloadKey += 1;
	}

	onMount(emitToolbar);
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
	<div data-testid="video-canvas" class="bg-gray-900 dark:bg-black h-full w-full flex flex-col relative">
		<!--
			Mode toolbar — absolute, top-right. Mirrors ImageRenderer so users
			don't have to learn two UIs. "Select" enables drag-to-region on the
			video frame; the timeline range-drag works in either mode.
		-->
		<div
			data-testid="video-mode-toolbar"
			class="absolute top-2 right-2 z-20 flex items-center gap-1 rounded-lg bg-black/60 backdrop-blur-sm px-1 py-1 text-white"
		>
			<button
				type="button"
				data-testid="video-mode-move"
				class="px-2 py-1 text-xs rounded {mode === 'move' ? 'bg-white/25' : 'hover:bg-white/10'}"
				title="Move / play / pause"
				on:click={() => setMode('move')}
			>
				Move
			</button>
			<button
				type="button"
				data-testid="video-mode-select"
				class="px-2 py-1 text-xs rounded {mode === 'select' ? 'bg-white/25' : 'hover:bg-white/10'}"
				title="Drag a region on the frame to attach it to chat"
				on:click={() => setMode('select')}
			>
				Select
			</button>
		</div>

		<div class="flex-1 flex items-center justify-center overflow-hidden">
			{#key reloadKey}
				<!--
					The frame wrapper bounds the video element so spatial drags
					can be expressed as % of the rendered frame, surviving any
					CSS resize. In Select mode it captures pointer events
					BEFORE the video, so click-to-play doesn't fire mid-drag.
				-->
				<div
					bind:this={videoFrameEl}
					data-testid="video-frame"
					class="relative inline-block"
					style={mode === 'select' ? 'cursor: crosshair;' : ''}
					on:mousedown={onFrameMouseDown}
					on:mousemove={onFrameMouseMove}
					on:mouseup={onFrameMouseUp}
					on:mouseleave={onFrameMouseUp}
					role="presentation"
				>
					<!-- svelte-ignore a11y-media-has-caption -->
					<video
						bind:this={videoEl}
						{src}
						class="max-w-full max-h-full block"
						style={mode === 'select' ? 'pointer-events: none;' : ''}
						on:play={() => (isPlaying = true)}
						on:pause={() => (isPlaying = false)}
						on:loadedmetadata={onLoadedMetadata}
						on:timeupdate={onTimeUpdate}
						on:error={handleError}
						playsinline
					></video>

					{#if mode === 'select' && isFrameDragging}
						<div
							data-testid="video-region-rect"
							class="absolute border-2 border-pink-500 bg-pink-500/10 pointer-events-none"
							style="left: {Math.min(frameDragStartXPct, frameDragEndXPct)}%; top: {Math.min(
								frameDragStartYPct,
								frameDragEndYPct
							)}%; width: {Math.abs(frameDragEndXPct - frameDragStartXPct)}%; height: {Math.abs(
								frameDragEndYPct - frameDragStartYPct
							)}%;"
						></div>
					{:else if mode === 'select' && lastFrameRegionPct}
						<div
							data-testid="video-region-rect"
							class="absolute border-2 border-pink-500 bg-pink-500/10 pointer-events-none"
							style="left: {lastFrameRegionPct.left}%; top: {lastFrameRegionPct.top}%; width: {lastFrameRegionPct.width}%; height: {lastFrameRegionPct.height}%;"
						></div>
					{/if}
				</div>
			{/key}
		</div>

		<!--
			Player controls + timeline. Timeline drag = time-range selection,
			click = seek. Drag fills the rail with a pink overlay; on mouseup
			the SelectionToolbar appears anchored to the selected segment.
		-->
		<div class="bg-black/80 text-white px-4 py-2 flex items-center gap-3 text-sm">
			<button
				type="button"
				data-testid="video-playpause"
				class="px-2 py-1 rounded hover:bg-white/10"
				on:click={togglePlay}
			>
				{isPlaying ? '⏸' : '▶'}
			</button>
			<span class="font-mono text-xs">{fmtTime(currentTime)} / {fmtTime(duration)}</span>
			<div
				bind:this={timelineEl}
				data-testid="video-timeline"
				class="relative flex-1 h-3 rounded bg-white/20 cursor-pointer"
				on:mousedown={onTimelineDown}
				on:mousemove={onTimelineMove}
				on:mouseup={onTimelineUp}
				on:mouseleave={onTimelineUp}
				role="slider"
				tabindex="0"
				aria-valuemin="0"
				aria-valuemax={duration}
				aria-valuenow={currentTime}
			>
				<!-- Played-portion overlay -->
				<div
					class="absolute inset-y-0 left-0 bg-white/60 rounded"
					style="width: {duration ? (currentTime / duration) * 100 : 0}%;"
				></div>
				<!-- Selected-region overlay (during drag, then persisted post-drag) -->
				{#if isTimelineDragging}
					<div
						class="absolute inset-y-0 bg-pink-500/40 border border-pink-500 rounded pointer-events-none"
						style="left: {Math.min(timelineDragStartPx, timelineDragEndPx)}px; width: {Math.abs(
							timelineDragEndPx - timelineDragStartPx
						)}px;"
					></div>
				{:else if regionStartSec !== null && regionEndSec !== null && regionStartSec !== regionEndSec && duration}
					<div
						class="absolute inset-y-0 bg-pink-500/40 border border-pink-500 rounded pointer-events-none"
						style="left: {(regionStartSec / duration) * 100}%; width: {((regionEndSec -
							regionStartSec) /
							duration) *
							100}%;"
					></div>
				{/if}
				<!-- Single-moment indicator (when a frame-region is anchored to one timestamp) -->
				{#if frameRegionAtSec !== null && duration}
					<div
						class="absolute top-0 bottom-0 w-0.5 bg-pink-500 pointer-events-none"
						style="left: {(frameRegionAtSec / duration) * 100}%;"
					></div>
				{/if}
			</div>
		</div>

		<SelectionToolbar placement="floating" anchorRect={toolbarAnchorRect} {filename} />
	</div>
{/if}
