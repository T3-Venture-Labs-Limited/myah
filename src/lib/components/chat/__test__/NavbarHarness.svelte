<script lang="ts">
	import { setContext } from 'svelte';
	import { writable } from 'svelte/store';
	import Navbar from '../Navbar.svelte';

	setContext(
		'i18n',
		writable({
			t: (value: string) => value
		})
	);

	export let chat: Record<string, unknown> | null = null;
	export let history: Record<string, unknown> = { currentId: null };
	export let selectedModels: string[] = [];
</script>

<Navbar
	{chat}
	{history}
	bind:selectedModels
	initNewChat={() => {}}
	onSaveTempChat={() => ({})}
	archiveChatHandler={() => {}}
	deleteChatHandler={() => {}}
	moveChatHandler={() => {}}
/>
