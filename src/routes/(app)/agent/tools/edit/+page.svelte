<script>
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { getAgentPlugins, updateAgentPlugin } from '$lib/apis/agent';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import ToolkitEditor from '$lib/components/workspace/Tools/ToolkitEditor.svelte';
	import { onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	const i18n = getContext('i18n');

	let tool = null;

	const saveHandler = async (data) => {
		const res = await updateAgentPlugin(localStorage.token, tool.id, {
			name: data.id,
			description: data.meta?.description ?? '',
			content: data.content
		}).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			toast.success($i18n.t('Tool updated successfully'));
		}
	};

	onMount(async () => {
		const id = $page.url.searchParams.get('id');

		if (id) {
			// Fetch plugin list and find by name
			const plugins = await getAgentPlugins(localStorage.token).catch((error) => {
				toast.error(`${error}`);
				goto('/agent/tools');
				return [];
			});

			const plugin = plugins.find((p) => p.name === id);
			if (plugin) {
				tool = {
					id: plugin.name,
					name: plugin.name,
					meta: { description: plugin.description },
					content: plugin.content,
					write_access: true,
					access_grants: []
				};
			} else {
				toast.error($i18n.t('Tool not found'));
				goto('/agent/tools');
			}
		} else {
			goto('/agent/tools');
		}
	});
</script>

{#if tool}
	<ToolkitEditor
		edit={true}
		id={tool.id}
		name={tool.name}
		meta={tool.meta}
		content={tool.content}
		onSave={(value) => {
			saveHandler(value);
		}}
	/>
{:else}
	<div class="flex items-center justify-center h-full">
		<div class="pb-16">
			<Spinner className="size-5" />
		</div>
	</div>
{/if}
