<script lang="ts">
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import { WEBUI_API_BASE_URL } from '$lib/constants';

	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	const i18n: Writable<any> = getContext('i18n');

	type Props = {
		error: string | Error;
		filename: string;
		/** file_id OR path — exactly one should be set, mirrors ArtifactViewer */
		file_id?: string;
		path?: string;
		/** Optional retry callback. When omitted, retry button is hidden. */
		onRetry?: () => void | Promise<void>;
	};

	const {
		error,
		filename,
		file_id = undefined,
		path = undefined,
		onRetry = undefined
	}: Props = $props();

	const errorMessage = $derived(error instanceof Error ? error.message : String(error));

	// Build the download URL — works for both file_id and path
	const downloadUrl = $derived(
		file_id
			? `${WEBUI_API_BASE_URL}/files/${file_id}/content`
			: path
				? `${WEBUI_API_BASE_URL}/hermes/media?path=${encodeURIComponent(path)}`
				: null
	);

	let copying = $state(false);
	const copyUrl = async () => {
		if (!downloadUrl) return;
		copying = true;
		try {
			// Build absolute URL for clipboard
			const absUrl = new URL(downloadUrl, window.location.origin).toString();
			await navigator.clipboard.writeText(absUrl);
		} catch (e) {
			console.error('Failed to copy URL:', e);
		} finally {
			setTimeout(() => (copying = false), 1500);
		}
	};
</script>

<div class="flex flex-col items-center justify-center py-12 px-4 gap-4 text-center">
	<!-- Warning icon -->
	<div
		class="size-12 rounded-full bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center text-amber-600 dark:text-amber-400"
	>
		<svg
			xmlns="http://www.w3.org/2000/svg"
			viewBox="0 0 24 24"
			fill="currentColor"
			class="size-6"
		>
			<path
				fill-rule="evenodd"
				d="M9.401 3.003c1.155-2 4.043-2 5.197 0l7.355 12.748c1.154 2-.29 4.5-2.599 4.5H4.645c-2.309 0-3.752-2.5-2.598-4.5L9.4 3.003ZM12 8.25a.75.75 0 0 1 .75.75v3.75a.75.75 0 0 1-1.5 0V9a.75.75 0 0 1 .75-.75Zm0 8.25a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Z"
				clip-rule="evenodd"
			/>
		</svg>
	</div>

	<div class="flex flex-col gap-1">
		<div class="text-sm font-medium text-gray-900 dark:text-gray-100">
			{$i18n?.t('Preview unavailable') ?? 'Preview unavailable'}
		</div>
		<div class="text-xs text-gray-500 dark:text-gray-400 max-w-sm break-words">
			{errorMessage}
		</div>
	</div>

	<div class="flex flex-wrap items-center justify-center gap-2 mt-2">
		{#if onRetry}
			<button
				type="button"
				class="px-3 py-1.5 text-xs rounded-lg bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 transition flex items-center gap-1.5"
				onclick={() => onRetry?.()}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
					class="size-3.5"
				>
					<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
					<path d="M21 3v5h-5" />
					<path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
					<path d="M3 21v-5h5" />
				</svg>
				{$i18n?.t('Retry') ?? 'Retry'}
			</button>
		{/if}

		{#if downloadUrl}
			<a
				href={downloadUrl}
				download={filename}
				class="px-3 py-1.5 text-xs rounded-lg bg-blue-600 hover:bg-blue-700 text-white transition flex items-center gap-1.5"
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
					class="size-3.5"
				>
					<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
					<polyline points="7 10 12 15 17 10" />
					<line x1="12" y1="15" x2="12" y2="3" />
				</svg>
				{$i18n?.t('Download') ?? 'Download'}
			</a>

			<button
				type="button"
				class="px-3 py-1.5 text-xs rounded-lg bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-700 dark:text-gray-300 transition flex items-center gap-1.5"
				onclick={copyUrl}
			>
				{#if copying}
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
						class="size-3.5 text-green-500"
					>
						<polyline points="20 6 9 17 4 12" />
					</svg>
					{$i18n?.t('Copied') ?? 'Copied'}
				{:else}
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
						class="size-3.5"
					>
						<rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
						<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
					</svg>
					{$i18n?.t('Copy URL') ?? 'Copy URL'}
				{/if}
			</button>
		{/if}
	</div>
</div>
