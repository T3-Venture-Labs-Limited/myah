<script lang="ts">
	import { toast } from 'svelte-sonner';

	import { onMount, getContext, onDestroy } from 'svelte';
	const i18n = getContext('i18n');

	import { user } from '$lib/stores';
	import { goto } from '$app/navigation';
	import { getAgentSkills, deleteAgentSkill, type AgentSkill } from '$lib/apis/agent';

	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import DeleteConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import EllipsisHorizontal from '$lib/components/icons/EllipsisHorizontal.svelte';
	import GarbageBin from '$lib/components/icons/GarbageBin.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import SkillMenu from '$lib/components/workspace/Skills/SkillMenu.svelte';

	let shiftKey = false;
	let loading = false;

	let query = '';
	let searchDebounceTimer: ReturnType<typeof setTimeout>;

	let skills: AgentSkill[] = [];
	let filteredItems: AgentSkill[] | null = null;
	let selectedSkill: AgentSkill | null = null;
	let showDeleteConfirm = false;

	const setFilteredItems = () => {
		if (!query) {
			filteredItems = skills;
			return;
		}
		const q = query.toLowerCase();
		filteredItems = skills.filter(
			(s) =>
				s.name.toLowerCase().includes(q) ||
				s.category.toLowerCase().includes(q) ||
				s.description.toLowerCase().includes(q)
		);
	};

	$: if (query !== undefined) {
		loading = true;
		clearTimeout(searchDebounceTimer);
		searchDebounceTimer = setTimeout(() => {
			setFilteredItems();
			loading = false;
		}, 300);
	}

	const loadSkills = async () => {
		loading = true;
		try {
			skills = await getAgentSkills(localStorage.token);
			setFilteredItems();
		} catch (err) {
			toast.error(`${err}`);
		} finally {
			loading = false;
		}
	};

	const deleteHandler = async (skill: AgentSkill) => {
		const res = await deleteAgentSkill(localStorage.token, skill.name).catch((err) => {
			toast.error(`${err}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t('Skill deleted successfully'));
		}

		await loadSkills();
	};

	onMount(async () => {
		await loadSkills();

		const onKeyDown = (event: KeyboardEvent) => {
			if (event.key === 'Shift') shiftKey = true;
		};
		const onKeyUp = (event: KeyboardEvent) => {
			if (event.key === 'Shift') shiftKey = false;
		};
		const onBlur = () => {
			shiftKey = false;
		};

		window.addEventListener('keydown', onKeyDown);
		window.addEventListener('keyup', onKeyUp);
		window.addEventListener('blur-sm', onBlur);

		return () => {
			clearTimeout(searchDebounceTimer);
			window.removeEventListener('keydown', onKeyDown);
			window.removeEventListener('keyup', onKeyUp);
			window.removeEventListener('blur-sm', onBlur);
		};
	});

	onDestroy(() => {
		clearTimeout(searchDebounceTimer);
	});
</script>

<div
	class="py-2 bg-white dark:bg-gray-900 rounded-3xl"
>
	<div class="flex items-center gap-2 px-1 mb-2">
		<div class="flex flex-1 items-center space-x-2 py-0.5">
			<div class="self-center ml-1 mr-3">
				<Search className="size-3.5" />
			</div>
			<input
				class="w-full text-sm pr-4 py-1 rounded-r-xl outline-hidden bg-transparent"
				bind:value={query}
				aria-label={$i18n.t('Search Skills')}
				placeholder={$i18n.t('Search Skills')}
			/>
			{#if query}
				<div class="self-center pl-1.5 translate-y-[0.5px] rounded-l-xl bg-transparent">
					<button
						class="p-0.5 rounded-full hover:bg-gray-100 dark:hover:bg-gray-900 transition"
						aria-label={$i18n.t('Clear search')}
						on:click={() => {
							query = '';
						}}
					>
						<XMark className="size-3" strokeWidth="2" />
					</button>
				</div>
			{/if}
		</div>

		<div class="text-xs text-gray-500 dark:text-gray-400 shrink-0">
			{filteredItems?.length ?? ''}
			{$i18n.t('skills')}
		</div>

		{#if $user?.role === 'admin' || $user?.permissions?.workspace?.skills}
			<a
				class="px-2 py-1 rounded-xl bg-black text-white dark:bg-white dark:text-black transition font-medium text-xs flex items-center shrink-0"
				href="/agent/skills/create"
			>
				<Plus className="size-3" strokeWidth="2.5" />
				<div class="ml-1">{$i18n.t('New Skill')}</div>
			</a>
		{/if}
	</div>

	{#if filteredItems === null || loading}
		<div class="w-full h-full flex justify-center items-center my-16 mb-24">
			<Spinner className="size-5" />
		</div>
	{:else if (filteredItems ?? []).length !== 0}
		<div class="my-2 gap-2 grid px-3 lg:grid-cols-2">
			{#each filteredItems as skill}
				<Tooltip content={skill?.description ?? skill?.name}>
					<div
						class="flex space-x-4 text-left w-full px-3 py-2.5 transition rounded-2xl cursor-pointer dark:hover:bg-gray-850/50 hover:bg-gray-50"
					>
						<a
							class="flex flex-1 space-x-3.5 cursor-pointer w-full"
							href={`/agent/skills/edit?name=${encodeURIComponent(skill.name)}`}
						>
							<div class="flex items-center text-left">
								<div class="flex-1 self-center">
									<div class="flex items-center gap-2">
										<div class="line-clamp-1 text-sm">
											{skill.name}
										</div>
									</div>
									<div class="px-0.5">
										<div class="text-xs text-gray-500 shrink-0">
											{skill.category}
											{#if skill.description}
												· {skill.description}
											{/if}
										</div>
									</div>
								</div>
							</div>
						</a>
						<div class="flex flex-row gap-0.5 self-center">
							{#if shiftKey}
								<Tooltip content={$i18n.t('Delete')}>
									<button
										class="self-center w-fit text-sm px-2 py-2 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
										type="button"
										aria-label={$i18n.t('Delete')}
										on:click={() => {
											deleteHandler(skill);
										}}
									>
										<GarbageBin />
									</button>
								</Tooltip>
							{:else}
								<SkillMenu
									editHandler={() => {
										goto(`/agent/skills/edit?name=${encodeURIComponent(skill.name)}`);
									}}
									cloneHandler={() => {
										sessionStorage.skill = JSON.stringify({
											name: `${skill.name}-clone`,
											id: `${skill.name}-clone`,
											description: skill.description,
											content: '',
											is_active: true,
											access_grants: []
										});
										goto('/agent/skills/create');
									}}
									exportHandler={() => {}}
									deleteHandler={async () => {
										selectedSkill = skill;
										showDeleteConfirm = true;
									}}
									onClose={() => {}}
								>
									<button
										class="self-center w-fit text-sm p-1.5 dark:text-gray-300 dark:hover:text-white hover:bg-black/5 dark:hover:bg-white/5 rounded-xl"
										type="button"
									>
										<EllipsisHorizontal className="size-5" />
									</button>
								</SkillMenu>
							{/if}
						</div>
					</div>
				</Tooltip>
			{/each}
		</div>
	{:else}
		<div class="w-full h-full flex flex-col justify-center items-center my-16 mb-24">
			<div class="max-w-md text-center">
				<div class="text-3xl mb-3">📝</div>
				<div class="text-lg font-medium mb-1">{$i18n.t('No skills found')}</div>
				<div class="text-gray-500 text-center text-xs">
					{$i18n.t('Try adjusting your search or filter to find what you are looking for.')}
				</div>
			</div>
		</div>
	{/if}
</div>

<DeleteConfirmDialog
	bind:show={showDeleteConfirm}
	title={$i18n.t('Delete skill?')}
	on:confirm={() => {
		if (selectedSkill) deleteHandler(selectedSkill);
	}}
>
	<div class="text-sm text-gray-500 truncate">
		{$i18n.t('This will delete')} <span class="font-medium">{selectedSkill?.name}</span>.
	</div>
</DeleteConfirmDialog>
