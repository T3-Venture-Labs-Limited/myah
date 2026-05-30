<script lang="ts">
	// Adopt Legacy Crons (Phase 6): shown instead of a fake empty chat when a
	// recurring task points at a cron that has no linked Myah chat yet. Lets the
	// user explicitly adopt the cron — creating/reusing a chat, backfilling
	// history, and (for external-origin jobs) preserving existing delivery.
	import { goto } from '$app/navigation';
	import { processMap, allTasks, applyAdoptedProcessToTasks } from '$lib/stores/tasks';
	import { adoptProcess, type Process } from '$lib/apis/processes';
	import { stripProcessPrefix } from '$lib/utils/tasks';
	import Spinner from '$lib/components/common/Spinner.svelte';

	export let process: Process;

	let adopting = false;
	let error = '';

	$: name = stripProcessPrefix(process?.name ?? '');
	$: isExternal = process?.adoption_state === 'external_origin';
	$: externalPlatform = process?.origin?.platform ?? 'an external destination';

	async function adopt() {
		if (adopting || !process) return;
		adopting = true;
		error = '';
		try {
			const result = await adoptProcess(localStorage.token, process.id);
			const chatId = result?.chat_id;

			// Reflect the new linkage in the process map so the card doesn't
			// reshow and lookups by chat_id resolve to this process.
			processMap.update((m) => {
				const next = new Map(m);
				const linked = {
					...process,
					chat_id: chatId,
					adoptable: false,
					adoption_state: 'myah_linked'
				} as Process;
				next.set(process.id, linked);
				if (chatId) next.set(chatId, linked);
				return next;
			});
			allTasks.update((tasks) => applyAdoptedProcessToTasks(tasks, process, chatId));

			if (chatId) {
				await goto(`/c/${chatId}`);
			}
		} catch (e: unknown) {
			const detail = e && typeof e === 'object' && 'detail' in e ? String(e.detail) : null;
			error = typeof e === 'string' ? e : (detail ?? 'Adoption failed. Please try again.');
		} finally {
			adopting = false;
		}
	}
</script>

<div class="flex h-full w-full items-center justify-center p-6">
	<div
		class="w-full max-w-md rounded-2xl border border-gray-100 dark:border-gray-850 p-6 text-center"
	>
		<div
			class="mx-auto mb-4 flex size-12 items-center justify-center rounded-full bg-gray-100 dark:bg-gray-850"
		>
			<svg class="size-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"
				/>
			</svg>
		</div>

		<h2 class="text-base font-semibold text-gray-800 dark:text-gray-200">
			Adopt this cron into Myah
		</h2>

		<p class="mt-2 text-sm text-gray-500 dark:text-gray-400">
			{#if isExternal}
				<span class="font-medium">{name}</span> currently delivers to {externalPlatform}. Adopting
				it into Myah won't change that — its existing delivery is preserved. You'll also see its run
				history here and future runs as they happen.
			{:else}
				<span class="font-medium">{name}</span> was created before it was linked to a Myah chat. Adopt
				it to bring its run history into this chat and receive future runs here.
			{/if}
		</p>

		{#if error}
			<p class="mt-3 text-sm text-red-500">{error}</p>
		{/if}

		<button
			class="mt-5 inline-flex items-center justify-center gap-2 rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-gray-800 disabled:opacity-60 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white"
			on:click={adopt}
			disabled={adopting}
		>
			{#if adopting}
				<Spinner className="size-4" />
				Adopting…
			{:else}
				Adopt into Myah
			{/if}
		</button>
	</div>
</div>
