<script lang="ts">
	// /diagnostics — detailed system-check page for OSS deployments.
	//
	// Linked from:
	//   * blocking-error screens (HermesDownError, PluginMissingError)
	//   * Help menu (when wired by Workstream C.7 / future docs work)
	//
	// Renders the response of GET /api/v1/oss/diagnostics with one row
	// per system check + collapsible details + remediation hints.
	//
	// Spec ref: §8 '/diagnostics page'
	import { getContext, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { getOssDiagnostics, type OssDiagnostics } from '$lib/apis/oss';

	const i18n = getContext('i18n');

	let loading = true;
	let error: string | null = null;
	let data: OssDiagnostics | null = null;

	async function load() {
		loading = true;
		error = null;
		try {
			data = await getOssDiagnostics();
		} catch (err) {
			error = typeof err === 'string' ? err : 'Diagnostics request failed.';
		} finally {
			loading = false;
		}
	}

	onMount(load);
</script>

<svelte:head>
	<title>{$i18n.t('Diagnostics')} • Myah</title>
</svelte:head>

<div class="diagnostics-page max-w-2xl mx-auto px-6 py-12">
	<div class="flex items-center justify-between mb-6">
		<h1 class="text-2xl font-semibold">{$i18n.t('Myah Diagnostics')}</h1>
		<button
			type="button"
			class="text-sm border border-gray-200 dark:border-gray-800 rounded-xl py-2 px-4 hover:bg-gray-50 dark:hover:bg-gray-800 transition"
			on:click={load}
		>
			{$i18n.t('Re-run all checks')}
		</button>
	</div>

	{#if loading}
		<div class="text-center text-sm text-gray-500 py-12">
			{$i18n.t('Running checks…')}
		</div>
	{:else if error}
		<div class="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-900 rounded-xl p-4 text-sm text-red-900 dark:text-red-200">
			<div class="font-medium mb-1">{$i18n.t('Could not fetch diagnostics')}</div>
			<div class="opacity-80">{error}</div>
		</div>
	{:else if data}
		<div class="space-y-3">
			<!-- Hermes gateway reachable -->
			<div class="rounded-xl border border-gray-200 dark:border-gray-800 p-4">
				<div class="flex items-start gap-3">
					<span
						class={data.hermes_reachable
							? 'text-emerald-500 text-lg leading-none mt-0.5'
							: 'text-red-500 text-lg leading-none mt-0.5'}
						aria-hidden="true"
					>
						{data.hermes_reachable ? '✓' : '✗'}
					</span>
					<div class="flex-1">
						<div class="font-medium">{$i18n.t('Hermes gateway reachable')}</div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mt-1 break-all">
							{data.hermes_url}
						</div>
						{#if !data.hermes_reachable}
							<div class="text-xs mt-2">
								{$i18n.t('Start Hermes on your host:')}
								<code class="bg-gray-100 dark:bg-gray-800 px-1 py-0.5 rounded">hermes gateway start</code>
							</div>
						{/if}
					</div>
				</div>
			</div>

			<!-- Myah plugin installed -->
			<div class="rounded-xl border border-gray-200 dark:border-gray-800 p-4">
				<div class="flex items-start gap-3">
					<span
						class={data.plugin_installed
							? 'text-emerald-500 text-lg leading-none mt-0.5'
							: 'text-red-500 text-lg leading-none mt-0.5'}
						aria-hidden="true"
					>
						{data.plugin_installed ? '✓' : '✗'}
					</span>
					<div class="flex-1">
						<div class="font-medium">{$i18n.t('Myah plugin installed')}</div>
						{#if data.plugin_version}
							<div class="text-xs text-gray-500 dark:text-gray-400 mt-1">
								{$i18n.t('version {{v}}', { v: data.plugin_version })}
							</div>
						{:else if data.hermes_reachable}
							<div class="text-xs mt-2">
								<code class="bg-gray-100 dark:bg-gray-800 px-1 py-0.5 rounded"
									>hermes plugins install T3-Venture-Labs-Limited/myah-hermes-plugin</code
								>
							</div>
						{/if}
					</div>
				</div>
			</div>

			<!-- Providers configured -->
			<div class="rounded-xl border border-gray-200 dark:border-gray-800 p-4">
				<div class="flex items-start gap-3">
					<span
						class={data.providers_configured.length > 0
							? 'text-emerald-500 text-lg leading-none mt-0.5'
							: 'text-yellow-500 text-lg leading-none mt-0.5'}
						aria-hidden="true"
					>
						{data.providers_configured.length > 0 ? '✓' : '!'}
					</span>
					<div class="flex-1">
						<div class="font-medium">{$i18n.t('Provider key detected in Hermes')}</div>
						{#if data.providers_configured.length > 0}
							<div class="text-xs text-gray-500 dark:text-gray-400 mt-1">
								{data.providers_configured.join(', ')}
							</div>
						{:else}
							<div class="text-xs mt-2 text-gray-500 dark:text-gray-400">
								{$i18n.t(
									'Add an API key (e.g. OPENROUTER_API_KEY) to ~/.hermes/.env and restart Hermes.'
								)}
							</div>
						{/if}
					</div>
				</div>
			</div>

			<!-- Platform port binding -->
			<div class="rounded-xl border border-gray-200 dark:border-gray-800 p-4">
				<div class="flex items-start gap-3">
					<span class="text-emerald-500 text-lg leading-none mt-0.5" aria-hidden="true">✓</span>
					<div class="flex-1">
						<div class="font-medium">{$i18n.t('Platform port binding')}</div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mt-1">
							{data.platform_port_binding}
							{$i18n.t('(localhost-only, secure default)')}
						</div>
					</div>
				</div>
			</div>

			<!-- Agent ports -->
			<div class="rounded-xl border border-gray-200 dark:border-gray-800 p-4">
				<div class="flex items-start gap-3">
					<span class="text-emerald-500 text-lg leading-none mt-0.5" aria-hidden="true">✓</span>
					<div class="flex-1">
						<div class="font-medium">{$i18n.t('Hermes agent ports')}</div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mt-1 space-y-0.5">
							<div>
								{$i18n.t('Gateway')}:
								<code class="bg-gray-100 dark:bg-gray-800 px-1 rounded"
									>{data.agent_ports.gateway}</code
								>
							</div>
							<div>
								{$i18n.t('Standalone')}:
								<code class="bg-gray-100 dark:bg-gray-800 px-1 rounded"
									>{data.agent_ports.standalone}</code
								>
							</div>
							<div>
								{$i18n.t('Web')}:
								<code class="bg-gray-100 dark:bg-gray-800 px-1 rounded">{data.agent_ports.web}</code>
							</div>
						</div>
					</div>
				</div>
			</div>

			<!-- OSS version -->
			<div class="rounded-xl border border-gray-200 dark:border-gray-800 p-4">
				<div class="flex items-start gap-3">
					<span class="text-gray-400 text-lg leading-none mt-0.5" aria-hidden="true">·</span>
					<div class="flex-1">
						<div class="font-medium">{$i18n.t('Myah OSS version')}</div>
						<div class="text-xs text-gray-500 dark:text-gray-400 mt-1">{data.oss_version}</div>
					</div>
				</div>
			</div>
		</div>

		<div class="mt-8">
			<button
				type="button"
				class="text-sm text-gray-500 hover:text-gray-700 dark:hover:text-gray-300"
				on:click={() => goto('/')}
			>
				← {$i18n.t('Back to chat')}
			</button>
		</div>
	{/if}
</div>
