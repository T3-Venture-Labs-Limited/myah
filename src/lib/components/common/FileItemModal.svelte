<script lang="ts">
	import { getContext, onMount, tick } from 'svelte';

	import { formatFileSize, getLineCount } from '$lib/utils';
	import { MYAH_API_BASE_URL } from '$lib/constants';
	import { settings } from '$lib/stores';
	import { getFileById } from '$lib/apis/files';
	import { detectFileType, type RendererKind } from '$lib/utils/fileTypeRegistry';

	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';

	// Renderer components — one per RendererKind
	import PdfRenderer from '$lib/components/renderers/PdfRenderer.svelte';
	import DocxRenderer from '$lib/components/renderers/DocxRenderer.svelte';
	import PptxRenderer from '$lib/components/renderers/PptxRenderer.svelte';
	import CsvRenderer from '$lib/components/renderers/CsvRenderer.svelte';
	import MarkdownRenderer from '$lib/components/renderers/MarkdownRenderer.svelte';
	import CodeRenderer from '$lib/components/renderers/CodeRenderer.svelte';
	import JsonRenderer from '$lib/components/renderers/JsonRenderer.svelte';
	import SqliteRenderer from '$lib/components/renderers/SqliteRenderer.svelte';
	import HtmlRenderer from '$lib/components/renderers/HtmlRenderer.svelte';
	import TextRenderer from '$lib/components/renderers/TextRenderer.svelte';
	import AudioRenderer from '$lib/components/renderers/AudioRenderer.svelte';
	import ImageRenderer from '$lib/components/renderers/ImageRenderer.svelte';
	import VideoRenderer from '$lib/components/renderers/VideoRenderer.svelte';

	const i18n = getContext('i18n');

	const CONTENT_PREVIEW_LIMIT = 10000;
	let expandedContent = false;

	import Modal from './Modal.svelte';
	import XMark from '../icons/XMark.svelte';
	import Switch from './Switch.svelte';
	import Tooltip from './Tooltip.svelte';
	import dayjs from 'dayjs';
	import Spinner from './Spinner.svelte';

	export let item;
	export let show = false;
	export let edit = false;

	let enableFullContent = false;
	let loading = false;
	let selectedTab = '';

	// ── File-type detection via registry ─────────────────────────────────────
	$: fileTypeEntry = detectFileType(item?.name ?? '', item?.meta?.content_type);
	$: kind = fileTypeEntry?.kind ?? 'unknown';

	// Shorthands used by the tab bar / legacy UI paths
	$: isPDF = kind === 'pdf';
	$: isAudio = kind === 'audio';
	$: isImage = kind === 'image';
	$: isVideo = kind === 'video';
	$: isExcel = kind === 'xlsx';
	$: isCsv = kind === 'csv';
	$: isDocx = kind === 'docx';
	$: isPptx = kind === 'pptx';
	$: isMarkdown = kind === 'markdown';
	$: isCode = kind === 'code';

	// Whether this kind has a richer Preview tab beyond the plain-text Content tab
	$: hasPreviewTab = isAudio || isPDF || isExcel || isCsv || isCode || isMarkdown || isDocx || isPptx || isVideo;

	// Map kind → renderer component (excluding xlsx which is deferred to Task 13)
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	const RENDERER_MAP: Partial<Record<RendererKind, any>> = {
		pdf: PdfRenderer,
		docx: DocxRenderer,
		pptx: PptxRenderer,
		csv: CsvRenderer,
		markdown: MarkdownRenderer,
		code: CodeRenderer,
		json: JsonRenderer,
		sqlite: SqliteRenderer,
		html: HtmlRenderer,
		text: TextRenderer,
		audio: AudioRenderer,
		image: ImageRenderer,
		video: VideoRenderer
	};

	// File ID used when passing content as a string to renderers
	$: fileId = item?.id as string;

	const loadContent = async () => {
		selectedTab = '';
		expandedContent = false;
		if (item?.type === 'file') {
			loading = true;

			const file = await getFileById(localStorage.token, item.id).catch((e) => {
				console.error('Error fetching file:', e);
				return null;
			});

			if (file) {
				item.file = file || {};
			}

			loading = false;
		}

		await tick();
	};

	$: if (show) {
		loadContent();
	}

	onMount(() => {
		console.log(item);
		if (item?.context === 'full') {
			enableFullContent = true;
		}
	});
</script>

<Modal bind:show size="lg">
	<div class="font-primary px-4.5 py-3.5 w-full flex flex-col justify-center dark:text-gray-400">
		<div class=" pb-2">
			<div class="flex items-start justify-between">
				<div>
					<div class=" font-medium text-lg dark:text-gray-100">
						<a
							href="#"
							class="hover:underline line-clamp-1"
							on:click|preventDefault={() => {
								if (!isPDF && item.url) {
									window.open(
										item.type === 'file'
											? item?.url?.startsWith('http')
												? item.url
												: `${MYAH_API_BASE_URL}/files/${item.url}/content`
											: item.url,
										'_blank'
									);
								}
							}}
						>
							{item?.name ?? 'File'}
						</a>
					</div>
				</div>

				<div>
					<button
						on:click={() => {
							show = false;
						}}
					>
						<XMark />
					</button>
				</div>
			</div>

			<div>
				<div class="flex flex-col items-center md:flex-row gap-1 justify-between w-full">
					<div class=" flex flex-wrap text-xs gap-1 text-gray-500">
						{#if item?.type === 'collection'}
							{#if item?.type}
								<div class="capitalize shrink-0">{item.type}</div>
								•
							{/if}

							{#if item?.description}
								<div class="line-clamp-1">{item.description}</div>
								•
							{/if}

							{#if item?.created_at}
								<div class="capitalize shrink-0">
									{dayjs(item.created_at * 1000).format('LL')}
								</div>
							{/if}
						{/if}

						{#if item.size}
							<div class="capitalize shrink-0">{formatFileSize(item.size)}</div>
							•
						{/if}

						{#if item?.file?.data?.content}
							<div class="capitalize shrink-0">
								{$i18n.t('{{COUNT}} extracted lines', {
									COUNT: getLineCount(item?.file?.data?.content ?? '')
								})}
							</div>

							<div class="flex items-center gap-1 shrink-0">
								• {$i18n.t('Formatting may be inconsistent from source.')}
							</div>
						{/if}
					</div>

					{#if edit}
						<div class=" self-end">
							<Tooltip
								content={enableFullContent
									? $i18n.t(
											'Inject the entire content as context for comprehensive processing, this is recommended for complex queries.'
										)
									: $i18n.t(
											'Default to segmented retrieval for focused and relevant content extraction, this is recommended for most cases.'
										)}
							>
								<div class="flex items-center gap-1.5 text-xs">
									{#if enableFullContent}
										{$i18n.t('Using Entire Document')}
									{:else}
										{$i18n.t('Using Focused Retrieval')}
									{/if}
									<Switch
										bind:state={enableFullContent}
										on:change={(e) => {
											item.context = e.detail ? 'full' : undefined;
										}}
									/>
								</div>
							</Tooltip>
						</div>
					{/if}
				</div>
			</div>
		</div>

		<div class="max-h-[75vh] overflow-auto">
			{#if !loading}
				{#if item?.type === 'collection'}
					<div>
						{#each item?.files as file}
							<div class="flex items-center gap-2 mb-2">
								<div class="flex-shrink-0 text-xs">
									{file?.meta?.name}
								</div>
							</div>
						{/each}
					</div>
				{/if}

				{#if hasPreviewTab}
					<div
						class="flex mb-2.5 scrollbar-none overflow-x-auto w-full border-b border-gray-50 dark:border-gray-850/30 text-center text-sm font-medium bg-transparent dark:text-gray-200"
					>
						<button
							class="min-w-fit py-1.5 px-4 border-b {selectedTab === ''
								? ' '
								: ' border-transparent text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition"
							type="button"
							on:click={() => {
								selectedTab = '';
							}}>{$i18n.t('Content')}</button
						>

						<button
							class="min-w-fit py-1.5 px-4 border-b {selectedTab === 'preview'
								? ' '
								: ' border-transparent text-gray-300 dark:text-gray-600 hover:text-gray-700 dark:hover:text-white'} transition"
							type="button"
							on:click={() => {
								selectedTab = 'preview';
							}}>{$i18n.t('Preview')}</button
						>
					</div>
				{/if}

				{#if isImage}
					<!-- Images render inline — no tab switching needed -->
					<ImageRenderer content={fileId} filename={item?.name ?? 'image'} mime={item?.meta?.content_type} />
				{:else if isVideo}
					<!-- Videos render inline -->
					<VideoRenderer content={fileId} filename={item?.name ?? 'video'} mime={item?.meta?.content_type} />
				{:else if selectedTab === ''}
					<!-- Content tab: extracted text preview -->
					{#if item?.file?.data}
						{@const rawContent = (item?.file?.data?.content ?? '').trim() || 'No content'}
						{@const isTruncated =
							($settings?.renderMarkdownInPreviews ?? true) &&
							rawContent.length > CONTENT_PREVIEW_LIMIT &&
							!expandedContent}
						{#if $settings?.renderMarkdownInPreviews ?? true}
							<div
								class="max-h-96 overflow-scroll scrollbar-hidden text-sm prose dark:prose-invert max-w-full"
							>
								<Markdown
									content={isTruncated ? rawContent.slice(0, CONTENT_PREVIEW_LIMIT) : rawContent}
									id="file-preview"
								/>
							</div>
							{#if isTruncated}
								<button
									class="mt-1 text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition"
									on:click={() => {
										expandedContent = true;
									}}
								>
									{$i18n.t('Show all ({{COUNT}} characters)', {
										COUNT: rawContent.length.toLocaleString()
									})}
								</button>
							{/if}
						{:else}
							<div class="max-h-96 overflow-scroll scrollbar-hidden text-xs whitespace-pre-wrap">
								{rawContent}
							</div>
						{/if}
					{:else if item?.content}
						{@const rawContent = (item?.content ?? '').trim() || 'No content'}
						{@const isTruncated =
							($settings?.renderMarkdownInPreviews ?? true) &&
							rawContent.length > CONTENT_PREVIEW_LIMIT &&
							!expandedContent}
						{#if $settings?.renderMarkdownInPreviews ?? true}
							<div
								class="max-h-96 overflow-scroll scrollbar-hidden text-sm prose dark:prose-invert max-w-full"
							>
								<Markdown
									content={isTruncated ? rawContent.slice(0, CONTENT_PREVIEW_LIMIT) : rawContent}
									id="file-preview-content"
								/>
							</div>
							{#if isTruncated}
								<button
									class="mt-1 text-xs text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 transition"
									on:click={() => {
										expandedContent = true;
									}}
								>
									{$i18n.t('Show all ({{COUNT}} characters)', {
										COUNT: rawContent.length.toLocaleString()
									})}
								</button>
							{/if}
						{:else}
							<div class="max-h-96 overflow-scroll scrollbar-hidden text-xs whitespace-pre-wrap">
								{rawContent}
							</div>
						{/if}
					{/if}
				{:else if selectedTab === 'preview'}
					<!-- Preview tab: rich renderer via registry -->
					{#if RENDERER_MAP[kind]}
						<svelte:component
							this={RENDERER_MAP[kind]}
							content={fileId}
							filename={item?.name ?? ''}
							mime={item?.meta?.content_type}
						/>
					{:else}
						<div class="max-h-96 overflow-scroll scrollbar-hidden text-xs whitespace-pre-wrap">
							{(item?.file?.data?.content ?? '').trim() || 'No content'}
						</div>
					{/if}
				{/if}
			{:else}
				<div class="flex items-center justify-center py-6">
					<Spinner className="size-5" />
				</div>
			{/if}
		</div>
	</div>
</Modal>

<style>
	:global(.excel-table-container table) {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.875rem;
		line-height: 1.25rem;
	}

	:global(.excel-table-container table td),
	:global(.excel-table-container table th) {
		border-width: 1px;
		border-style: solid;
		border-color: var(--color-gray-300, #cdcdcd);
		padding: 0.5rem 0.75rem;
		text-align: left;
	}

	:global(.dark .excel-table-container table td),
	:global(.dark .excel-table-container table th) {
		border-color: var(--color-gray-600, #676767);
	}

	:global(.excel-table-container table th) {
		background-color: var(--color-gray-100, #ececec);
		font-weight: 600;
	}

	:global(.dark .excel-table-container table th) {
		background-color: var(--color-gray-800, #333);
		color: var(--color-gray-100, #ececec);
	}

	:global(.excel-table-container table tr:nth-child(even)) {
		background-color: var(--color-gray-50, #f9f9f9);
	}

	:global(.dark .excel-table-container table tr:nth-child(even)) {
		background-color: rgba(38, 38, 38, 0.5);
	}

	:global(.excel-table-container table tr:hover) {
		background-color: var(--color-gray-100, #ececec);
	}

	:global(.dark .excel-table-container table tr:hover) {
		background-color: rgba(51, 51, 51, 0.5);
	}
</style>
