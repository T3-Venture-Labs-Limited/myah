<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { goto } from '$app/navigation';
	import { onMount, getContext } from 'svelte';

	const i18n = getContext('i18n');

	import { createAgentSkill } from '$lib/apis/agent';
	import SkillEditor from '$lib/components/workspace/Skills/SkillEditor.svelte';

	let skill: {
		name: string;
		id: string;
		description: string;
		content: string;
		is_active: boolean;
		access_grants: never[];
	} | null = null;

	let clone = false;

	// Extract category from SKILL.md frontmatter if present.
	const extractCategory = (content: string): string => {
		const m = content.match(/^---\n([\s\S]*?)\n---/);
		if (m) {
			const catLine = m[1].split('\n').find((l) => l.startsWith('category:'));
			if (catLine) return catLine.split(':')[1].trim().replace(/['"]/g, '');
		}
		return 'general';
	};

	const onSubmit = async (_skill: {
		id: string;
		name: string;
		description: string;
		content: string;
	}) => {
		const res = await createAgentSkill(localStorage.token, {
			name: _skill.id,
			category: extractCategory(_skill.content),
			description: _skill.description,
			trigger: '',
			content: _skill.content
		}).catch((err) => {
			toast.error(`${err}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t('Skill created successfully'));
			await goto('/agent/skills');
		}
	};

	onMount(async () => {
		if (sessionStorage.skill) {
			const _skill = JSON.parse(sessionStorage.skill);
			sessionStorage.removeItem('skill');

			clone = true;
			skill = {
				name: _skill.name || 'Skill',
				id: _skill.id || '',
				description: _skill.description || '',
				content: _skill.content || '',
				is_active: true,
				access_grants: []
			};
		}
	});
</script>

{#key skill}
	<SkillEditor {skill} {onSubmit} {clone} />
{/key}
