<script lang="ts">
	import { getContext } from 'svelte';
	import { goto } from '$app/navigation';

	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Pin from '$lib/components/icons/Pin.svelte';
	import PinSlash from '$lib/components/icons/PinSlash.svelte';
	import Link from '$lib/components/icons/Link.svelte';
	import Pencil from '$lib/components/icons/Pencil.svelte';
	import Star from '$lib/components/icons/Star.svelte';
	import { config, settings, user, defaultModel } from '$lib/stores';
	import GlobeAlt from '$lib/components/icons/GlobeAlt.svelte';

	const i18n = getContext('i18n');

	export let show = false;
	export let model;

	export let pinModelHandler: (modelId: string) => void = () => {};
	export let copyLinkHandler: Function = () => {};
	// Myah T3-932: promotes `model` to the user's global default for new chats.
	export let setDefaultHandler: (modelId: string) => void = () => {};

	export let onClose: Function = () => {};

	// Compare the structured pair (post 2026-05-24) against this model's
	// (provider, id) — bare id alone is not unique when multiple providers
	// expose the same model id (the original T3-1031 disambiguation case).
	$: isDefault =
		$defaultModel?.model === model?.id &&
		$defaultModel?.provider === model?.tags?.[0]?.name;
</script>

<Dropdown
	bind:show
	align="end"
	sideOffset={-2}
	onOpenChange={(state) => {
		if (state === false) {
			onClose();
		}
	}}
>
	<Tooltip
		content={$i18n.t('More')}
		className={($settings?.highContrastMode ?? false)
			? ''
			: 'group-hover/item:opacity-100 opacity-0'}
	>
		<slot />
	</Tooltip>

	<div slot="content">
		<div
			class="min-w-[210px] text-sm rounded-2xl p-1 z-[9999999] bg-white dark:bg-gray-850 dark:text-white shadow-lg border border-gray-100 dark:border-gray-800"
		>
			<button
				type="button"
				aria-pressed={($settings?.pinnedModels ?? []).includes(model?.id)}
				class="select-none flex rounded-xl py-1.5 px-3 w-full hover:bg-gray-50 dark:hover:bg-gray-800 transition items-center gap-2"
				on:click={(e) => {
					e.stopPropagation();
					e.preventDefault();

					pinModelHandler(model?.id);
					show = false;
				}}
			>
				{#if ($settings?.pinnedModels ?? []).includes(model?.id)}
					<PinSlash />
				{:else}
					<Pin />
				{/if}

				<div class="flex items-center">
					{#if ($settings?.pinnedModels ?? []).includes(model?.id)}
						{$i18n.t('Hide from Sidebar')}
					{:else}
						{$i18n.t('Keep in Sidebar')}
					{/if}
				</div>
			</button>

			<button
				type="button"
				class="select-none flex rounded-xl py-1.5 px-3 w-full hover:bg-gray-50 dark:hover:bg-gray-800 transition items-center gap-2"
				on:click={(e) => {
					e.stopPropagation();
					e.preventDefault();

					copyLinkHandler();
					show = false;
				}}
			>
				<Link />

				<div class="flex items-center">{$i18n.t('Copy Link')}</div>
			</button>

			<!-- Myah T3-932: promote this model to the user's global default -->
			{#if !isDefault}
				<button
					type="button"
					class="select-none flex rounded-xl py-1.5 px-3 w-full hover:bg-gray-50 dark:hover:bg-gray-800 transition items-center gap-2"
					on:click={(e) => {
						e.stopPropagation();
						e.preventDefault();

						setDefaultHandler(model?.id);
						show = false;
					}}
				>
					<Star />
					<div class="flex items-center">{$i18n.t('Set as default')}</div>
				</button>
			{/if}
		</div>
	</div>
</Dropdown>
