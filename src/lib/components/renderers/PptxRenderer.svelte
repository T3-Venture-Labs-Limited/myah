<script lang="ts">
	import { onMount, createEventDispatcher } from 'svelte';
	import { MYAH_API_BASE_URL } from '$lib/constants';
	import type { ToolbarItem } from '$lib/types/artifact';
	import ArtifactFallback from './ArtifactFallback.svelte';

	export let content: Blob | string;
	export let filename: string;
	export let mime: string | undefined = undefined;
	export let file_id: string | undefined = undefined;
	export let path: string | undefined = undefined;
	export let editable = false;

	$: void editable;

	const dispatch = createEventDispatcher<{
		toolbar: { items: ToolbarItem[] };
		error: Error;
	}>();

	let slides: string[] = [];
	let currentSlide = 0;
	let errorObj: Error | null = null;
	let loading = true;

	function prev() {
		currentSlide = Math.max(0, currentSlide - 1);
		emitToolbar();
	}

	function next() {
		currentSlide = Math.min(slides.length - 1, currentSlide + 1);
		emitToolbar();
	}

	function emitToolbar() {
		dispatch('toolbar', {
			items: [
				{ placement: 'bottom', id: 'slide-prev', label: 'Previous slide', onClick: prev },
				{ placement: 'bottom', id: 'slide-next', label: 'Next slide', onClick: next }
			]
		});
	}

	const load = async () => {
		loading = true;
		errorObj = null;
		try {
			let arrayBuffer: ArrayBuffer;
			if (content instanceof Blob) {
				arrayBuffer = await content.arrayBuffer();
			} else {
				const res = await fetch(`${MYAH_API_BASE_URL}/files/${content}/content`, {
					credentials: 'include'
				});
				if (!res.ok) throw new Error(`HTTP ${res.status}`);
				arrayBuffer = await res.arrayBuffer();
			}

			const { pptxToImages } = await import('$lib/utils/pptxToHtml');
			const result = await pptxToImages(arrayBuffer);
			slides = result.images;
			currentSlide = 0;
			emitToolbar();
		} catch (e) {
			console.error('Error loading PPTX file:', e);
			errorObj = e instanceof Error ? e : new Error(String(e));
			dispatch('error', errorObj);
		} finally {
			loading = false;
		}
	};

	onMount(() => {
		emitToolbar();
		load();
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
{:else if slides.length > 0}
	<div class="max-h-[60vh] overflow-auto">
		<div class="flex justify-center p-4">
			<img
				src={slides[currentSlide]}
				alt="Slide {currentSlide + 1}"
				class="max-w-full max-h-[50vh] object-contain rounded-md shadow-lg"
				draggable="false"
			/>
		</div>
		{#if slides.length > 1}
			<div class="flex items-center justify-center gap-3 pb-3 text-sm text-gray-500">
				<button
					class="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-30"
					disabled={currentSlide === 0}
					aria-label="Previous slide"
					on:click={prev}
				>
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-5">
						<path
							fill-rule="evenodd"
							d="M11.78 5.22a.75.75 0 0 1 0 1.06L8.06 10l3.72 3.72a.75.75 0 1 1-1.06 1.06l-4.25-4.25a.75.75 0 0 1 0-1.06l4.25-4.25a.75.75 0 0 1 1.06 0Z"
							clip-rule="evenodd"
						/>
					</svg>
				</button>
				<span>{currentSlide + 1} / {slides.length}</span>
				<button
					class="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 disabled:opacity-30"
					disabled={currentSlide === slides.length - 1}
					aria-label="Next slide"
					on:click={next}
				>
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-5">
						<path
							fill-rule="evenodd"
							d="M8.22 5.22a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 0 1 0 1.06l-4.25 4.25a.75.75 0 0 1-1.06-1.06L11.94 10 8.22 6.28a.75.75 0 0 1 0-1.06Z"
							clip-rule="evenodd"
						/>
					</svg>
				</button>
			</div>
		{/if}
	</div>
{:else}
	<div class="text-gray-500 text-sm p-4">No content available</div>
{/if}
