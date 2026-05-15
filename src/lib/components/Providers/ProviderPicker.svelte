<script lang="ts">
	import { getContext } from 'svelte';
	import { browser } from '$app/environment';
	import { createFocusTrap } from 'focus-trap';
	import { toast } from 'svelte-sonner';
	import type { CatalogEntry } from '$lib/apis/providers';
	import { disconnectProvider } from '$lib/apis/providers';
	import {
		catalog,
		providerStatusV2,
		refreshCatalog,
		refreshProviderStatus
	} from '$lib/stores/providers';
	import ApiKey from './AuthFlow/ApiKey.svelte';
	import DeviceCode from './AuthFlow/DeviceCode.svelte';

	let {
		mode = 'onboarding',
		onComplete
	}: {
		mode?: 'onboarding' | 'settings';
		onComplete?: () => void;
	} = $props();

	const i18n = getContext('i18n');

	let activeProvider = $state<CatalogEntry | null>(null);
	let searchQuery = $state('');

	let statusMap = $derived(
		Object.fromEntries(
			($providerStatusV2 ?? []).map((s) => [s.providerId, s])
		)
	);

	$effect(() => {
		const token = localStorage.token;
		refreshCatalog(token);
		refreshProviderStatus(token);
	});

	function openProvider(entry: CatalogEntry) {
		const status = statusMap[entry.id];
		// Already connected — don't re-prompt for credentials. In onboarding,
		// just complete the flow; in settings, open the disconnect/manage UI.
		if (status?.isValid) {
			if (mode === 'onboarding') {
				onComplete?.();
				return;
			}
			// Settings mode: scroll the manage options into view by opening
			// the modal (which shows the Connected state / Disconnect option).
		}
		activeProvider = entry;
	}

	function closeSubModal() {
		activeProvider = null;
	}

	async function handleComplete() {
		closeSubModal();
		await refreshProviderStatus(localStorage.token);
		if (mode === 'onboarding') {
			onComplete?.();
		}
	}

	async function disconnect(providerId: string) {
		if (
			!confirm(
				$i18n.t('Disconnect {{provider}}? Your credential will be removed.', {
					provider: providerId
				})
			)
		)
			return;
		try {
			await disconnectProvider(localStorage.token, providerId);
			await refreshProviderStatus(localStorage.token);
			toast.success($i18n.t('Provider disconnected'));
		} catch (err: unknown) {
			const e = err as Record<string, unknown>;
			toast.error(
				typeof err === 'string'
					? err
					: typeof e?.detail === 'string'
						? e.detail
						: $i18n.t('Failed to disconnect')
			);
		}
	}

	let v1Providers = $derived(Object.values($catalog ?? {}).filter((e) => e.v1_visible));
	let filteredProviders = $derived(
		searchQuery.trim()
			? v1Providers.filter(
					(e) =>
						e.display_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
						e.description.toLowerCase().includes(searchQuery.toLowerCase())
				)
			: v1Providers
	);

	function portal(node: HTMLElement) {
		if (!browser) return;
		document.body.appendChild(node);
		return {
			destroy() {
				node.remove();
			}
		};
	}

	// The parent settings modal (Modal.svelte) activates a focus-trap on its own
	// container. Because our sub-modal is portaled to document.body, it lives
	// OUTSIDE that container — focus-trap's checkFocusIn then yanks focus back
	// whenever the user tries to focus the API-key input or any other control
	// inside the sub-modal. Activating our own trap on the portaled node pushes
	// onto focus-trap's global stack and auto-pauses the parent, letting the
	// sub-modal's inputs receive focus normally.
	function trapFocus(node: HTMLElement) {
		if (!browser) return;
		const trap = createFocusTrap(node, {
			escapeDeactivates: false,
			clickOutsideDeactivates: false,
			allowOutsideClick: true,
			fallbackFocus: node
		});
		trap.activate();
		return {
			destroy() {
				trap.deactivate();
			}
		};
	}
</script>

{#if mode === 'onboarding'}
	<div class="flex-1 min-h-0 w-full overflow-hidden flex flex-col items-center py-8 px-4">
		<div class="w-full max-w-3xl shrink-0 mb-5">
			<div class="text-center mb-6">
				<p class="text-[11px] font-semibold uppercase tracking-widest text-gray-400 dark:text-neutral-500 mb-3">
					Get started
				</p>
				<h1 class="text-2xl font-semibold text-gray-900 dark:text-gray-50 mb-2">
					Connect a provider
				</h1>
				<p class="text-sm text-gray-500 dark:text-gray-400 max-w-sm mx-auto leading-relaxed">
					Choose an AI provider to power your agent. You can add more later in settings.
				</p>
			</div>
			<div class="relative">
				<svg
					class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none"
					xmlns="http://www.w3.org/2000/svg"
					fill="none"
					viewBox="0 0 24 24"
					stroke="currentColor"
					stroke-width="2"
				>
					<path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
				</svg>
				<input
					bind:value={searchQuery}
					type="search"
					placeholder={$i18n.t('Search providers...')}
					aria-label={$i18n.t('Search providers')}
					class="w-full pl-9 pr-4 py-2.5 text-sm bg-gray-100 dark:bg-neutral-800 border border-transparent focus:border-gray-300 dark:focus:border-neutral-600 rounded-xl outline-none text-gray-900 dark:text-gray-100 placeholder:text-gray-400 transition-colors"
				/>
			</div>
		</div>

		<div class="w-full max-w-3xl flex-1 min-h-0 overflow-y-auto">
			{#if $catalog === null}
				<div class="flex justify-center py-12">
					<div class="h-7 w-7 border-2 border-neutral-700 border-t-neutral-400 rounded-full animate-spin"></div>
				</div>
			{:else if filteredProviders.length === 0}
				<p class="text-center py-12 text-sm text-gray-400 dark:text-neutral-500">
					{$i18n.t('No providers match your search')}
				</p>
			{:else}
				<div class="grid grid-cols-1 sm:grid-cols-2 gap-3 pb-6">
					{#each filteredProviders as entry (entry.id)}
						{@const status = statusMap[entry.id]}
						<div
							class="relative border rounded-xl p-4 cursor-pointer transition-all duration-200 {status?.isValid
								? 'border-green-500/30 bg-green-500/5 hover:border-green-500/50'
								: status?.reconnectNeeded
									? 'border-amber-500/30 bg-amber-500/5 hover:border-amber-500/50'
									: 'border-gray-100 dark:border-neutral-800 bg-white dark:bg-neutral-900/60 hover:border-gray-300 dark:hover:border-neutral-600 hover:shadow-sm'}"
							role="button"
							tabindex="0"
					onclick={() => openProvider(entry)}
					onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && openProvider(entry)}
				>
						<div class="flex items-start justify-between gap-2 mb-2.5">
							<p class="font-medium text-sm text-gray-900 dark:text-gray-100">
								{entry.display_name}
							</p>
							{#if status?.isValid}
								<span class="shrink-0 text-xs font-medium text-green-700 dark:text-green-400 bg-green-100 dark:bg-green-500/20 rounded-full px-2 py-0.5">
									{$i18n.t('Connected')}
								</span>
							{:else if status?.reconnectNeeded}
								<span class="shrink-0 text-xs font-medium text-amber-700 dark:text-amber-400 bg-amber-100 dark:bg-amber-500/20 rounded-full px-2 py-0.5">
									{$i18n.t('Reconnect')}
								</span>
							{/if}
						</div>
						<p class="text-xs text-gray-500 dark:text-gray-400 line-clamp-2 leading-relaxed">
							{entry.description}
						</p>
						<div class="flex items-center mt-3">
								<span class="text-[10px] font-medium text-gray-400 dark:text-neutral-600 uppercase tracking-wide">
									{entry.auth_type === 'api_key' ? 'API Key' : entry.auth_type === 'oauth_device_code' ? 'OAuth' : ''}
								</span>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>
	</div>
{:else}
	<div class="flex flex-col gap-3">
		<div class="relative">
			<svg
				class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400 pointer-events-none"
				xmlns="http://www.w3.org/2000/svg"
				fill="none"
				viewBox="0 0 24 24"
				stroke="currentColor"
				stroke-width="2"
			>
				<path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
			</svg>
			<input
				bind:value={searchQuery}
				type="search"
				placeholder={$i18n.t('Search providers...')}
				aria-label={$i18n.t('Search providers')}
				class="w-full pl-9 pr-4 py-2.5 text-sm bg-gray-100 dark:bg-neutral-800 border border-transparent focus:border-gray-300 dark:focus:border-neutral-600 rounded-xl outline-none text-gray-900 dark:text-gray-100 placeholder:text-gray-400 transition-colors"
			/>
		</div>
		{#if $catalog === null}
			<div class="flex justify-center py-8">
				<div class="h-7 w-7 border-2 border-neutral-700 border-t-neutral-400 rounded-full animate-spin"></div>
			</div>
		{:else if filteredProviders.length === 0}
			<p class="text-center py-8 text-sm text-gray-400 dark:text-neutral-500">
				{$i18n.t('No providers match your search')}
			</p>
		{:else}
			<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
				{#each filteredProviders as entry (entry.id)}
					{@const status = statusMap[entry.id]}
					<div
						class="relative border rounded-xl p-4 cursor-pointer transition-all duration-200 {status?.isValid
							? 'border-green-500/30 bg-green-500/5 hover:border-green-500/50'
							: status?.reconnectNeeded
								? 'border-amber-500/30 bg-amber-500/5 hover:border-amber-500/50'
								: 'border-gray-100 dark:border-neutral-800 bg-white dark:bg-neutral-900/60 hover:border-gray-300 dark:hover:border-neutral-600 hover:shadow-sm'}"
						role="button"
						tabindex="0"
					onclick={() => openProvider(entry)}
					onkeydown={(e) => (e.key === 'Enter' || e.key === ' ') && openProvider(entry)}
					>
						<div class="flex items-start justify-between gap-2 mb-2.5">
							<p class="font-medium text-sm text-gray-900 dark:text-gray-100">
								{entry.display_name}
							</p>
							{#if status?.isValid}
								<span class="shrink-0 text-xs font-medium text-green-700 dark:text-green-400 bg-green-100 dark:bg-green-500/20 rounded-full px-2 py-0.5">
									{$i18n.t('Connected')}
								</span>
							{:else if status?.reconnectNeeded}
								<span class="shrink-0 text-xs font-medium text-amber-700 dark:text-amber-400 bg-amber-100 dark:bg-amber-500/20 rounded-full px-2 py-0.5">
									{$i18n.t('Reconnect')}
								</span>
							{/if}
						</div>
						<p class="text-xs text-gray-500 dark:text-gray-400 line-clamp-2 leading-relaxed">
							{entry.description}
						</p>
						<div class="flex items-center justify-between mt-3">
							<span class="text-[10px] font-medium text-gray-400 dark:text-neutral-600 uppercase tracking-wide">
								{entry.auth_type === 'api_key' ? 'API Key' : entry.auth_type === 'oauth_device_code' ? 'OAuth' : ''}
							</span>
							{#if status?.isValid}
								<button
									class="text-xs text-red-500/60 hover:text-red-500 transition-colors"
									onclick={(e) => { e.stopPropagation(); disconnect(entry.id); }}
								>
									{$i18n.t('Disconnect')}
								</button>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>
{/if}

<!-- Sub-modal for active provider auth flow -->
{#if activeProvider}
	<div
		use:portal
		use:trapFocus
		tabindex="-1"
		class="fixed inset-0 z-[10000] flex items-center justify-center bg-black/60 backdrop-blur-md"
		role="dialog"
		aria-modal="true"
	>
		<div
			class="bg-white dark:bg-neutral-900 rounded-2xl shadow-2xl border border-gray-100 dark:border-neutral-800 w-full max-w-md mx-4"
		>
			<div
				class="flex items-center justify-between px-5 pt-5 pb-4 border-b border-gray-100 dark:border-neutral-800"
			>
				<h3 class="font-semibold text-base text-gray-900 dark:text-gray-100">
					{activeProvider.display_name}
				</h3>
				<button
					class="w-7 h-7 rounded-lg flex items-center justify-center text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-neutral-800 transition-colors"
				onclick={closeSubModal}
				aria-label={$i18n.t('Close')}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						class="h-4 w-4"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
						stroke-width="2"
					>
						<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
					</svg>
				</button>
			</div>

			{#if statusMap[activeProvider.id]?.isValid}
				<!-- Already connected — show manage state instead of re-prompting -->
				<div class="flex flex-col gap-4 p-5">
					<div class="flex items-center gap-2">
						<span class="inline-flex h-2 w-2 rounded-full bg-green-500" aria-hidden="true"></span>
						<p class="text-sm font-medium text-green-700 dark:text-green-400">
							{$i18n.t('Connected')}
						</p>
					</div>
					{#if statusMap[activeProvider.id]?.keyLastFour}
						<p class="text-xs text-gray-500 dark:text-gray-400">
							{$i18n.t('Key ending in')} ••••{statusMap[activeProvider.id].keyLastFour}
						</p>
					{/if}
					<p class="text-sm text-gray-600 dark:text-gray-400 leading-relaxed">
						{activeProvider.description}
					</p>
					<div
						class="flex items-center justify-end gap-2 pt-4 border-t border-gray-100 dark:border-neutral-800"
					>
						<button
							class="text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 px-3 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-neutral-800 transition-colors"
						onclick={closeSubModal}
					>
						{$i18n.t('Close')}
						</button>
						<button
							class="text-sm text-red-600 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300 font-medium px-3 py-1.5 rounded-lg hover:bg-red-50 dark:hover:bg-red-500/10 transition-colors"
						onclick={async () => {
							if (activeProvider) {
								await disconnect(activeProvider.id);
								closeSubModal();
							}
						}}
						>
							{$i18n.t('Disconnect')}
						</button>
					</div>
				</div>
			{:else if activeProvider.auth_type === 'api_key'}
			<ApiKey
				provider={activeProvider}
				onComplete={handleComplete}
				onCancel={closeSubModal}
			/>
			{:else if activeProvider.auth_type === 'oauth_device_code'}
			<DeviceCode
				provider={activeProvider}
				onComplete={handleComplete}
				onCancel={closeSubModal}
			/>
			{:else}
				<div class="p-6 text-center text-gray-500 text-sm">
					{$i18n.t('This provider requires a flow not yet supported in the UI. Coming soon.')}
				</div>
			{/if}
		</div>
	</div>
{/if}
