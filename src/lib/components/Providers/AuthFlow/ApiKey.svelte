<script lang="ts">
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import type { CatalogEntry, ConnectResult } from '$lib/apis/providers';
	import { connectCredential } from '$lib/apis/providers';
	import { refreshProviderStatus } from '$lib/stores/providers';

	let {
		provider,
		onComplete,
		onCancel
	}: {
		provider: CatalogEntry;
		onComplete?: (result: ConnectResult) => void;
		onCancel?: () => void;
	} = $props();

	const i18n = getContext('i18n');

	let apiKey = $state('');
	let loading = $state(false);

	async function save() {
		if (!apiKey.trim()) {
			toast.error($i18n.t('Please enter an API key'));
			return;
		}
		loading = true;
		try {
			const token = localStorage.token;
			const result = await connectCredential(token, provider.id, apiKey.trim());
			await refreshProviderStatus(token);
			onComplete?.(result);
		} catch (err: unknown) {
			const e = err as Record<string, unknown>;
			const msg =
				typeof err === 'string'
					? err
					: typeof e?.detail === 'string'
						? e.detail
						: $i18n.t('Failed to connect provider');
			toast.error(msg);
		} finally {
			loading = false;
		}
	}
</script>

<div class="flex flex-col gap-4 p-4">
	<p class="text-sm text-gray-600 dark:text-gray-400">{provider.description}</p>

	<input
		type="password"
		bind:value={apiKey}
		placeholder={$i18n.t('Paste your API key here')}
		class="w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
		onkeydown={(e) => e.key === 'Enter' && save()}
	/>

	<div class="flex gap-2 justify-end">
		<button
			class="text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 px-3 py-1.5"
			onclick={() => onCancel?.()}
			disabled={loading}
		>
			{$i18n.t('Cancel')}
		</button>
		<button
			class="bg-gray-900 hover:bg-gray-700 dark:bg-white dark:hover:bg-gray-100 text-white dark:text-gray-900 text-sm font-medium px-4 py-1.5 rounded-lg disabled:opacity-50 transition-colors"
			onclick={save}
			disabled={loading}
		>
			{loading ? $i18n.t('Connecting…') : $i18n.t('Save & Connect')}
		</button>
	</div>
</div>
