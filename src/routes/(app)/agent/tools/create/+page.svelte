<script>
	import { goto } from '$app/navigation';
	import { createAgentPlugin } from '$lib/apis/agent';
	import ToolkitEditor from '$lib/components/workspace/Tools/ToolkitEditor.svelte';
	import { onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	const i18n = getContext('i18n');

	let mounted = false;
	let clone = false;
	let tool = null;

	const saveHandler = async (data) => {
		const res = await createAgentPlugin(localStorage.token, {
			name: data.id,
			description: data.meta?.description ?? '',
			content: data.content
		}).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t('Tool created successfully'));
			await goto('/agent/tools');
		}
	};

	onMount(() => {
		if (sessionStorage.tool) {
			tool = JSON.parse(sessionStorage.tool);
			sessionStorage.removeItem('tool');
			clone = true;
		}

		mounted = true;
	});
</script>

{#if mounted}
	{#key tool?.content}
		<ToolkitEditor
			id={tool?.id ?? ''}
			name={tool?.name ?? ''}
			meta={tool?.meta ?? { description: '' }}
			content={tool?.content ?? ''}
			{clone}
			onSave={(value) => {
				saveHandler(value);
			}}
		/>
	{/key}
{/if}
