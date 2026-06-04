<script lang="ts">
	import { getContext } from 'svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Image from '$lib/components/common/Image.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';
	import EditPencil from '$lib/components/icons/EditPencil.svelte';
	import ArrowForward from '$lib/components/icons/ArrowForward.svelte';
	import { MYAH_API_BASE_URL } from '$lib/constants';

	const i18n: any = getContext('i18n');

	export let id: string;
	export let content: string;
	export let files: any[] = [];
	export let onSteer: (id: string) => void;
	export let onInterrupt: (id: string) => void;
	export let onEdit: (id: string) => void;
	export let onDelete: (id: string) => void;
	export let steerDisabled = false;
</script>

<div class="flex items-center gap-2 px-2 py-1.5">
	<!-- Arrow forward icon -->
	<div class="shrink-0 text-gray-500">
		<ArrowForward className="size-3.5" />
	</div>

	<!-- Message content -->
	<div class="flex-1 min-w-0 flex items-center gap-2">
		{#if files.length > 0}
			<div class="flex items-center gap-1 shrink-0">
				{#each files as file}
					{#if file.type === 'image' || (file?.content_type ?? '').startsWith('image/')}
						{@const fileUrl =
							file.url?.startsWith('data') || file.url?.startsWith('http')
								? file.url
								: `${MYAH_API_BASE_URL}/files/${file.url}${file?.content_type ? '/content' : ''}`}
						<Image src={fileUrl} alt="" imageClassName="size-6 rounded-md object-cover" />
					{:else}
						<div
							class="flex items-center px-1.5 py-0.5 rounded-md bg-gray-100 dark:bg-gray-800 text-xs text-gray-500 dark:text-gray-400"
						>
							<span class="max-w-[80px] truncate">{file.name ?? 'file'}</span>
						</div>
					{/if}
				{/each}
			</div>
		{/if}

		{#if content}
			<p class="text-sm text-gray-600 dark:text-gray-300 truncate">{content}</p>
		{:else if files.length === 0}
			<p class="text-sm text-gray-400 dark:text-gray-500 truncate italic">
				{$i18n.t('Empty message')}
			</p>
		{/if}
	</div>

	<!-- Actions -->
	<div class="flex items-center gap-1 shrink-0">
		<!-- Steer current run -->
		<Tooltip
			content={steerDisabled
				? $i18n.t('Steer supports text-only queued messages for now')
				: $i18n.t('Steer current run')}
		>
			<button
				type="button"
				class="p-1 text-gray-400 hover:text-gray-700 disabled:hover:text-gray-400 disabled:opacity-40 dark:text-gray-500 dark:hover:text-gray-300 dark:disabled:hover:text-gray-500 transition-colors"
				on:click={() => {
					if (!steerDisabled) onSteer(id);
				}}
				disabled={steerDisabled}
				aria-label={$i18n.t('Steer current run')}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					stroke-width="1.5"
					stroke="currentColor"
					class="size-3.5"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						d="M7.5 8.25h9m-9 3.75h6m-8.25 8.25 3-3H18a2.25 2.25 0 0 0 2.25-2.25V6A2.25 2.25 0 0 0 18 3.75H6A2.25 2.25 0 0 0 3.75 6v9A2.25 2.25 0 0 0 6 17.25h.75v3Z"
					/>
				</svg>
			</button>
		</Tooltip>

		<!-- Interrupt and send -->
		<Tooltip content={$i18n.t('Interrupt and send')}>
			<button
				type="button"
				class="p-1 text-gray-400 hover:text-gray-700 dark:text-gray-500 dark:hover:text-gray-300 transition-colors"
				on:click={() => onInterrupt(id)}
				aria-label={$i18n.t('Interrupt and send')}
			>
				<svg
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					stroke-width="1.5"
					stroke="currentColor"
					class="size-3.5"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						d="m4.5 12.75 6 6 9-13.5"
					/>
				</svg>
			</button>
		</Tooltip>

		<!-- Edit -->
		<Tooltip content={$i18n.t('Edit')}>
			<button
				type="button"
				class="p-1 text-gray-400 hover:text-gray-700 dark:text-gray-500 dark:hover:text-gray-300 transition-colors"
				on:click={() => onEdit(id)}
				aria-label={$i18n.t('Edit')}
			>
				<EditPencil className="size-3.5" />
			</button>
		</Tooltip>

		<!-- Delete -->
		<Tooltip content={$i18n.t('Delete')}>
			<button
				type="button"
				class="p-1 text-gray-400 hover:text-gray-700 dark:text-gray-500 dark:hover:text-gray-300 transition-colors"
				on:click={() => onDelete(id)}
				aria-label={$i18n.t('Delete')}
			>
				<GarbageBin className="size-3.5" />
			</button>
		</Tooltip>
	</div>
</div>
