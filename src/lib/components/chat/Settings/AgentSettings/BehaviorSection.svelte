<script lang="ts">
	import { createEventDispatcher, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { addMcpServer, removeMcpServer } from '$lib/apis/agent-config';

	export let config: Record<string, any> = {};
	export let schema: Record<string, any> = {};
	export let onPatch: (body: Record<string, unknown>) => Promise<void>;

	const i18n = getContext<any>('i18n');
	const dispatch = createEventDispatcher<{ reload: void }>();

	const reasoningLevels = ['low', 'medium', 'high'];
	const approvalModes = ['manual', 'smart', 'auto'];

	async function setField(key: string, value: string) {
		await onPatch({ [key]: value });
	}

	let newMcpJson = '';

	async function addMcp() {
		try {
			const cfg = JSON.parse(newMcpJson);
			await addMcpServer(localStorage.token, cfg);
			toast.success(`${cfg.name} added`);
			newMcpJson = '';
			dispatch('reload');
		} catch (err) {
			toast.error(`${err}`);
		}
	}

	async function removeMcp(name: string) {
		if (!confirm(`Remove MCP server ${name}?`)) return;
		try {
			await removeMcpServer(localStorage.token, name);
			toast.success(`${name} removed`);
			dispatch('reload');
		} catch (err) {
			toast.error(`${err}`);
		}
	}

	$: mcpServers = (config.mcp_servers ?? {}) as Record<string, unknown>;
	$: visibleMcpServers = Object.fromEntries(
		Object.entries(mcpServers).filter(([k]) => k !== 'composio')
	);
</script>

<section
	class="py-2 bg-white dark:bg-gray-900 rounded-3xl border border-gray-100/30 dark:border-gray-850/30"
>
	<div class="flex items-center justify-between px-4 mb-2">
		<div class="text-sm font-medium">{$i18n.t('Behavior')}</div>
	</div>

	<div class="px-3.5 flex flex-col gap-3">
		<div>
			<label for="agent-reasoning-effort" class="mb-1 block text-xs text-gray-500">
				{$i18n.t('Reasoning effort')}
			</label>
			<select
				id="agent-reasoning-effort"
				class="text-sm rounded-xl py-1.5 px-3 bg-transparent border border-gray-100 dark:border-gray-850 outline-none"
				value={config.agent?.reasoning_effort ?? 'medium'}
				on:change={(e) =>
					setField('agent.reasoning_effort', (e.target as HTMLSelectElement).value)}
			>
				{#each reasoningLevels as lvl}
					<option value={lvl}>{lvl}</option>
				{/each}
			</select>
		</div>

		<div>
			<label for="agent-approval-mode" class="mb-1 block text-xs text-gray-500">
				{$i18n.t('Approval mode')}
			</label>
			<select
				id="agent-approval-mode"
				class="text-sm rounded-xl py-1.5 px-3 bg-transparent border border-gray-100 dark:border-gray-850 outline-none"
				value={config.approvals?.mode ?? 'smart'}
				on:change={(e) => setField('approvals.mode', (e.target as HTMLSelectElement).value)}
			>
				{#each approvalModes as m}
					<option value={m}>{m}</option>
				{/each}
			</select>
		</div>

		<div>
			<label for="agent-personality" class="mb-1 block text-xs text-gray-500">
				{$i18n.t('Personality')}
			</label>
			<input
				id="agent-personality"
				type="text"
				class="text-sm rounded-xl py-1.5 px-3 bg-transparent border border-gray-100 dark:border-gray-850 outline-none"
				value={config.display?.personality ?? ''}
				on:blur={(e) => setField('display.personality', (e.target as HTMLInputElement).value)}
			/>
		</div>

		<details>
			<summary class="cursor-pointer text-sm font-medium text-gray-700 dark:text-gray-300 py-1">
				{$i18n.t('Custom MCP servers (advanced)')}
			</summary>
			<div class="mt-2">
				<p class="text-xs text-gray-500 dark:text-gray-400 mb-2">
					{$i18n.t('Add MCP servers manually if you need a service not available in Integrations.')}
				</p>
				{#if Object.keys(visibleMcpServers).length === 0}
					<div class="text-xs text-gray-400 dark:text-gray-600 py-1">
						{$i18n.t('No MCP servers configured')}
					</div>
				{:else}
					<ul class="text-sm flex flex-col gap-1">
						{#each Object.keys(visibleMcpServers) as name (name)}
							<li
								class="flex items-center justify-between px-3 py-2 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-850/50 transition"
							>
								<span class="font-mono text-xs">{name}</span>
								<button
									type="button"
									class="text-xs text-gray-500 hover:text-red-600"
									on:click={() => removeMcp(name)}
								>
									{$i18n.t('Remove')}
								</button>
							</li>
						{/each}
					</ul>
				{/if}
				<details class="mt-2">
					<summary class="cursor-pointer text-xs text-gray-500 hover:text-gray-700">
						+ {$i18n.t('Add MCP server (JSON)')}
					</summary>
					<textarea
						class="mt-2 h-24 w-full text-xs rounded-xl py-1.5 px-3 bg-transparent border border-gray-100 dark:border-gray-850 outline-none font-mono"
						bind:value={newMcpJson}
						placeholder={`{"name": "github", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"], "env": {}}`}
					/>
					<button
						type="button"
						class="mt-1 px-3 py-1 text-xs font-medium rounded-lg bg-gray-50 dark:bg-gray-850 hover:bg-gray-100 dark:hover:bg-gray-800 transition"
						on:click={addMcp}
					>
						{$i18n.t('Add')}
					</button>
				</details>
			</div>
		</details>
	</div>
</section>
