<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { onMount, getContext } from 'svelte';

	import {
		getAgentEnvVars,
		setAgentEnvVar,
		deleteAgentEnvVar,
		type AgentEnvVar
	} from '$lib/apis/agent';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';

	const i18n = getContext('i18n');

	let loading = false;
	let envVars: Record<string, AgentEnvVar> = {};
	let query = '';

	// Add/edit state
	let showAddForm = false;
	let editingKey = '';
	let formKey = '';
	let formValue = '';
	let saving = false;

	// Delete state
	let deletingKey = '';
	let showDeleteConfirm = false;
	let pendingDeleteKey = '';

	$: filteredVars = Object.entries(envVars)
		.filter(([key, info]) => {
			if (!query) return true;
			const q = query.toLowerCase();
			return (
				key.toLowerCase().includes(q) ||
				info.description.toLowerCase().includes(q) ||
				info.category.toLowerCase().includes(q) ||
				(info.tools || []).some((t) => t.toLowerCase().includes(q))
			);
		})
		.sort(([, a], [, b]) => {
			if (a.is_set !== b.is_set) return a.is_set ? -1 : 1;
			return 0;
		});

	$: categoryGroups = (() => {
		const groups: Record<string, [string, AgentEnvVar][]> = {};
		for (const entry of filteredVars) {
			const cat = entry[1].category || 'other';
			if (!groups[cat]) groups[cat] = [];
			groups[cat].push(entry);
		}
		return groups;
	})();

	const init = async () => {
		loading = true;
		try {
			envVars = await getAgentEnvVars(localStorage.token);
		} catch (err) {
			toast.error(`${$i18n.t('Failed to load secrets')}: ${err}`);
		} finally {
			loading = false;
		}
	};

	const handleSave = async () => {
		if (!formKey || !formValue) return;
		saving = true;
		try {
			await setAgentEnvVar(localStorage.token, formKey, formValue);
			toast.success(`${formKey} ${$i18n.t('saved')}`);
			formKey = '';
			formValue = '';
			editingKey = '';
			showAddForm = false;
			await init();
		} catch (err) {
			toast.error(`${$i18n.t('Failed to save')}: ${err}`);
		} finally {
			saving = false;
		}
	};

	const confirmDelete = (key: string) => {
		pendingDeleteKey = key;
		showDeleteConfirm = true;
	};

	const handleDelete = async () => {
		const key = pendingDeleteKey;
		showDeleteConfirm = false;
		deletingKey = key;
		try {
			await deleteAgentEnvVar(localStorage.token, key);
			toast.success(`${key} ${$i18n.t('removed')}`);
			await init();
		} catch (err) {
			toast.error(`${$i18n.t('Failed to remove')}: ${err}`);
		} finally {
			deletingKey = '';
			pendingDeleteKey = '';
		}
	};

	const startEdit = (key: string) => {
		editingKey = key;
		formKey = key;
		formValue = '';
		showAddForm = true;
	};

	const startAdd = () => {
		editingKey = '';
		formKey = '';
		formValue = '';
		showAddForm = true;
	};

	const cancelForm = () => {
		showAddForm = false;
		editingKey = '';
		formKey = '';
		formValue = '';
	};

	onMount(async () => {
		await init();
	});
</script>

<div class="flex flex-col h-full justify-between text-sm">
	<div
		class="py-2 bg-white dark:bg-gray-900 rounded-3xl border border-gray-100/30 dark:border-gray-850/30"
	>
		<!-- Header -->
		<div class="flex items-center justify-between px-4 mb-2">
			<div class="flex items-center gap-2">
				<div class="text-sm font-medium">
					{$i18n.t('Secrets')}
				</div>
				<div class="text-xs text-gray-500">
					{Object.values(envVars).filter((v) => v.is_set).length}
					{$i18n.t('configured')}
				</div>
			</div>
			<button
				class="px-3 py-1 text-xs font-medium rounded-lg bg-gray-50 dark:bg-gray-850 hover:bg-gray-100 dark:hover:bg-gray-800 transition"
				on:click={startAdd}
			>
				+ {$i18n.t('Add')}
			</button>
		</div>

		<!-- Search -->
		<div class="flex w-full space-x-2 py-0.5 px-3.5 pb-2">
			<input
				class="w-full text-sm rounded-xl py-1.5 px-4 bg-transparent border border-gray-100 dark:border-gray-850 outline-none"
				placeholder={$i18n.t('Search secrets...')}
				bind:value={query}
			/>
		</div>

		<!-- Add/Edit Form -->
		{#if showAddForm}
			<div
				class="mx-3.5 mb-3 p-3 rounded-xl border border-blue-200 dark:border-blue-800 bg-blue-50/50 dark:bg-blue-950/30"
			>
				<div class="flex flex-col gap-2">
					<input
						class="w-full text-sm rounded-lg py-1.5 px-3 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 outline-none font-mono"
						placeholder="VARIABLE_NAME"
						bind:value={formKey}
						disabled={!!editingKey}
					/>
					<input
						type="password"
						class="w-full text-sm rounded-lg py-1.5 px-3 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 outline-none font-mono"
						placeholder={$i18n.t('Value (hidden)')}
						bind:value={formValue}
						autocomplete="new-password"
					/>
					<div class="flex gap-2 justify-end">
						<button
							class="px-3 py-1 text-xs rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition"
							on:click={cancelForm}
						>
							{$i18n.t('Cancel')}
						</button>
						<button
							class="px-3 py-1 text-xs font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition disabled:opacity-50"
							disabled={!formKey || !formValue || saving}
							on:click={handleSave}
						>
							{saving ? $i18n.t('Saving...') : editingKey ? $i18n.t('Update') : $i18n.t('Save')}
						</button>
					</div>
				</div>
			</div>
		{/if}

		<!-- Content -->
		{#if loading}
			<div class="flex justify-center py-8">
				<Spinner className="size-5" />
			</div>
		{:else if filteredVars.length === 0}
			<div class="text-center text-gray-500 text-xs py-8">
				{query ? $i18n.t('No matching secrets') : $i18n.t('No secrets configured')}
			</div>
		{:else}
			<div class="flex flex-col gap-1 px-3.5 max-h-[28rem] overflow-y-auto">
				{#each Object.entries(categoryGroups) as [category, entries]}
					<div
						class="text-xs text-gray-400 dark:text-gray-500 uppercase tracking-wider mt-2 mb-1 px-1"
					>
						{category}
					</div>
					{#each entries as [key, info]}
						<div
							class="flex items-center justify-between px-3 py-2 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-850/50 transition group"
						>
							<div class="flex flex-col min-w-0 flex-1">
								<div class="flex items-center gap-2">
									<span class="font-mono text-xs truncate">{key}</span>
									{#if info.is_set}
										<span
											class="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400"
										>
											{$i18n.t('set')}
										</span>
									{:else}
										<span
											class="text-[10px] px-1.5 py-0.5 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-500"
										>
											{$i18n.t('not set')}
										</span>
									{/if}
								</div>
								<div class="text-xs text-gray-500 truncate mt-0.5">
									{info.description}
									{#if info.redacted_value}
										<span class="font-mono text-gray-400 ml-1">{info.redacted_value}</span>
									{/if}
								</div>
							</div>

							<div class="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition">
								{#if info.url}
									<a
										href={info.url}
										target="_blank"
										rel="noopener noreferrer"
										class="p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-400 hover:text-gray-600"
										title={$i18n.t('Get API key')}
									>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											viewBox="0 0 20 20"
											fill="currentColor"
											class="size-3.5"
										>
											<path
												d="M12.232 4.232a2.5 2.5 0 0 1 3.536 3.536l-1.225 1.224a.75.75 0 0 0 1.061 1.06l1.224-1.224a4 4 0 0 0-5.656-5.656l-3 3a4 4 0 0 0 .225 5.865.75.75 0 0 0 .977-1.138 2.5 2.5 0 0 1-.142-3.667l3-3Z"
											/>
											<path
												d="M11.603 7.963a.75.75 0 0 0-.977 1.138 2.5 2.5 0 0 1 .142 3.667l-3 3a2.5 2.5 0 0 1-3.536-3.536l1.225-1.224a.75.75 0 0 0-1.061-1.06l-1.224 1.224a4 4 0 1 0 5.656 5.656l3-3a4 4 0 0 0-.225-5.865Z"
											/>
										</svg>
									</a>
								{/if}
								<button
									class="p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-400 hover:text-blue-600"
									title={info.is_set ? $i18n.t('Update') : $i18n.t('Set value')}
									on:click={() => startEdit(key)}
								>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										viewBox="0 0 20 20"
										fill="currentColor"
										class="size-3.5"
									>
										<path
											d="m5.433 13.917 1.262-3.155A4 4 0 0 1 7.58 9.42l6.92-6.918a2.121 2.121 0 0 1 3 3l-6.92 6.918c-.383.383-.84.685-1.343.886l-3.154 1.262a.5.5 0 0 1-.65-.65Z"
										/>
										<path
											d="M3.5 5.75c0-.69.56-1.25 1.25-1.25H10A.75.75 0 0 0 10 3H4.75A2.75 2.75 0 0 0 2 5.75v9.5A2.75 2.75 0 0 0 4.75 18h9.5A2.75 2.75 0 0 0 17 15.25V10a.75.75 0 0 0-1.5 0v5.25c0 .69-.56 1.25-1.25 1.25h-9.5c-.69 0-1.25-.56-1.25-1.25v-9.5Z"
										/>
									</svg>
								</button>
								{#if info.is_set}
									<button
										class="p-1 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-400 hover:text-red-600"
										title={$i18n.t('Remove')}
										disabled={deletingKey === key}
										on:click={() => confirmDelete(key)}
									>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											viewBox="0 0 20 20"
											fill="currentColor"
											class="size-3.5"
										>
											<path
												fill-rule="evenodd"
												d="M8.75 1A2.75 2.75 0 0 0 6 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 1 0 .23 1.482l.149-.022 1.005 11.36A2.75 2.75 0 0 0 7.763 20h4.474a2.75 2.75 0 0 0 2.744-2.689l1.005-11.36.15.022a.75.75 0 1 0 .23-1.482A41.03 41.03 0 0 0 14 4.193V3.75A2.75 2.75 0 0 0 11.25 1h-2.5ZM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4ZM8.58 7.72a.75.75 0 0 1 .7.798l-.2 4.5a.75.75 0 0 1-1.497-.066l.2-4.5a.75.75 0 0 1 .797-.699Zm2.84 0a.75.75 0 0 1 .798.7l.2 4.5a.75.75 0 1 1-1.496.065l-.2-4.5a.75.75 0 0 1 .698-.798Z"
												clip-rule="evenodd"
											/>
										</svg>
									</button>
								{/if}
							</div>
						</div>
					{/each}
				{/each}
			</div>
		{/if}
	</div>
</div>

<ConfirmDialog
	bind:show={showDeleteConfirm}
	on:confirm={handleDelete}
	title={$i18n.t('Remove Secret')}
	message={$i18n.t(
		'Are you sure you want to remove **{{key}}**? The original value cannot be recovered.',
		{ key: pendingDeleteKey }
	)}
/>
