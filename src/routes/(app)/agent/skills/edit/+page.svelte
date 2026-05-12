<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { goto } from '$app/navigation';
	import { onMount, getContext } from 'svelte';

	const i18n = getContext('i18n');

	import { getAgentSkillByName, updateAgentSkill } from '$lib/apis/agent';
	import { page } from '$app/stores';

	import SkillEditor from '$lib/components/workspace/Skills/SkillEditor.svelte';

	let skill: {
		id: string;
		name: string;
		description: string;
		content: string;
		is_active: boolean;
		access_grants: never[];
	} | null = null;
	let disabled = false;

	$: skillName = $page.url.searchParams.get('name');

	const onSubmit = async (_skill: {
		id: string;
		name: string;
		description: string;
		content: string;
	}) => {
		if (!skillName) return;
		const updatedSkill = await updateAgentSkill(localStorage.token, skillName, {
			name: _skill.id,
			description: _skill.description,
			content: _skill.content
		}).catch((err) => {
			toast.error(`${err}`);
			return null;
		});

		if (updatedSkill) {
			toast.success($i18n.t('Skill updated successfully'));
			skill = {
				id: updatedSkill.name,
				name: updatedSkill.name,
				description: updatedSkill.description,
				content: updatedSkill.content,
				is_active: true,
				access_grants: []
			};
		}
	};

	onMount(async () => {
		if (skillName) {
			const _skill = await getAgentSkillByName(localStorage.token, skillName).catch((err) => {
				toast.error(`${err}`);
				return null;
			});

			if (_skill) {
				disabled = false;
				skill = {
					id: _skill.name,
					name: _skill.name,
					description: _skill.description,
					content: _skill.content,
					is_active: true,
					access_grants: []
				};
			} else {
				goto('/agent/skills');
			}
		} else {
			goto('/agent/skills');
		}
	});
</script>

{#if skill}
	<SkillEditor {skill} {onSubmit} {disabled} edit />
{/if}
