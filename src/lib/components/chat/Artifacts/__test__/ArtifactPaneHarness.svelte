<script lang="ts">
	import ArtifactPane from '../ArtifactPane.svelte';

	export let chatId: string;
	export let token: string = 't';
</script>

<ArtifactPane {chatId} {token} />
