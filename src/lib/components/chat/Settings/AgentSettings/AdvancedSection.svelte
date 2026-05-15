<script lang="ts">
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { restartAgent } from '$lib/apis/agent-config';

	export let config: Record<string, any> = {};
	export let schema: Record<string, any> = {};
	export let onPatch: (body: Record<string, unknown>) => Promise<void>;

	const i18n = getContext<any>('i18n');
	let pendingRestart = false;

	async function setAndWarn(key: string, value: string) {
		pendingRestart = true;
		await onPatch({ [key]: value });
		toast.warning($i18n.t('Changing this requires restarting the agent. Click Restart when ready.'));
	}

	async function doRestart() {
		try {
			const res = await restartAgent(localStorage.token);
			if ('busy' in res && res.busy) {
				toast.warning($i18n.t('A turn is currently running. Wait for it to finish and retry.'));
			} else {
				toast.success($i18n.t('Agent restarting…'));
				pendingRestart = false;
			}
		} catch (err) {
			// The restart endpoint kills the gateway process mid-response, so
			// httpx raises a TimeoutException and the platform proxy returns
			// 504. The restart itself succeeded — health-check confirms it.
			// Treat 504 / "timed out" as success and surface a softer toast.
			// See e2e-output/report.md ISSUE-006.
			const message = `${err}`;
			if (message.includes('timed out') || message.includes('504')) {
				toast.success($i18n.t('Agent restarting…'));
				pendingRestart = false;
				return;
			}
			toast.error(message);
		}
	}
</script>

<section
	class="py-2 bg-amber-50/30 dark:bg-amber-950/10 rounded-3xl border border-amber-200/60 dark:border-amber-800/40"
>
	<div class="flex items-center justify-between px-4 mb-1">
		<div class="text-sm font-medium">{$i18n.t('Advanced (requires agent restart)')}</div>
	</div>
	<p class="px-4 mb-3 text-xs text-gray-600 dark:text-gray-400">
		{$i18n.t(
			'Changing these restarts your agent (~3 seconds). Active conversations are preserved via session DB.'
		)}
	</p>

	<div class="px-3.5 flex flex-col gap-3">
		<div>
			<label for="agent-terminal-backend" class="mb-1 block text-xs text-gray-500">
				{$i18n.t('Terminal backend')}
			</label>
			<select
				id="agent-terminal-backend"
				class="text-sm rounded-xl py-1.5 px-3 bg-transparent border border-gray-100 dark:border-gray-850 outline-none"
				value={config.terminal?.backend ?? 'local'}
				on:change={(e) =>
					setAndWarn('terminal.backend', (e.target as HTMLSelectElement).value)}
			>
				<option value="local">local</option>
				<option value="docker">docker</option>
				<option value="ssh">ssh</option>
			</select>
		</div>

		<div>
			<label for="agent-timezone" class="mb-1 block text-xs text-gray-500">
				{$i18n.t('Timezone')}
			</label>
			<input
				id="agent-timezone"
				type="text"
				class="text-sm rounded-xl py-1.5 px-3 bg-transparent border border-gray-100 dark:border-gray-850 outline-none"
				value={config.timezone ?? ''}
				on:blur={(e) => setAndWarn('timezone', (e.target as HTMLInputElement).value)}
				placeholder="America/New_York"
			/>
		</div>

		{#if pendingRestart}
			<div>
				<button
					type="button"
					class="px-3 py-1 text-xs font-medium rounded-lg bg-amber-600 text-white hover:bg-amber-700 transition"
					on:click={doRestart}
				>
					{$i18n.t('Restart agent to apply')}
				</button>
			</div>
		{/if}
	</div>
</section>
