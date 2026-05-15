<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { getAgentSoul, putAgentSoul } from '$lib/apis/agent-config';

	const i18n = getContext<any>('i18n');

	let body = '';
	let etag = '';
	let saving = false;
	let conflict: { current_body: string } | null = null;

	let softWarnChars = 8_192;
	let hardCapChars = 32_768;

	async function load() {
		try {
			const res = await getAgentSoul(localStorage.token);
			body = res.body;
			etag = res.etag;
			if (res.softWarnChars != null) softWarnChars = res.softWarnChars;
			if (res.hardCapChars != null) hardCapChars = res.hardCapChars;
		} catch (err) {
			toast.error(`${err}`);
		}
	}

	async function save() {
		if (body.length > hardCapChars) {
			toast.error(
				$i18n.t('SOUL is {{got}} chars; hard cap is {{cap}}.', {
					got: body.length.toLocaleString(),
					cap: hardCapChars.toLocaleString()
				})
			);
			return;
		}
		if (!etag) {
			await load();
		}
		saving = true;
		try {
			const res = await putAgentSoul(localStorage.token, body, etag);
			if ('conflict' in res) {
				conflict = { current_body: res.current_body };
			} else {
				etag = res.etag;
				toast.success($i18n.t('SOUL saved'));
				if (res.warning) toast.warning(res.warning);
			}
		} catch (err) {
			toast.error(`${err}`);
		} finally {
			saving = false;
		}
	}

	function keepMine() {
		getAgentSoul(localStorage.token).then(async (r) => {
			etag = r.etag;
			conflict = null;
			await save();
		});
	}

	function useTheirs() {
		if (conflict) {
			body = conflict.current_body;
			conflict = null;
			getAgentSoul(localStorage.token).then((r) => {
				etag = r.etag;
			});
		}
	}

	onMount(load);
</script>

<section
	class="py-2 bg-white dark:bg-gray-900 rounded-3xl border border-gray-100/30 dark:border-gray-850/30"
>
	<div class="flex items-center justify-between px-4 mb-2">
		<div class="text-sm font-medium">{$i18n.t('Persona (SOUL.md)')}</div>
	</div>

	<div class="px-3.5 flex flex-col gap-2">
		<textarea
			class="h-64 w-full text-sm rounded-xl py-2 px-3 bg-transparent border border-gray-100 dark:border-gray-850 outline-none font-mono"
			bind:value={body}
			disabled={saving}
		/>

		<div class="flex items-center gap-2">
			<button
				type="button"
				class="px-3 py-1 text-xs font-medium rounded-lg bg-gray-50 dark:bg-gray-850 hover:bg-gray-100 dark:hover:bg-gray-800 transition disabled:opacity-50"
				on:click={save}
				disabled={saving}
			>
				{saving ? $i18n.t('Saving…') : $i18n.t('Save')}
			</button>
			<span
				class="text-xs"
				class:text-gray-500={body.length <= softWarnChars}
				class:text-amber-600={body.length > softWarnChars && body.length <= hardCapChars}
				class:text-red-600={body.length > hardCapChars}
			>
				{body.length.toLocaleString()} / {hardCapChars.toLocaleString()} chars
				{#if body.length > hardCapChars}
					<span>— exceeds hard cap; save will return 413</span>
				{:else if body.length > softWarnChars}
					<span>— long SOULs add to every turn's token cost</span>
				{/if}
			</span>
		</div>
	</div>

	{#if conflict}
		<div
			class="mx-3.5 mt-3 mb-2 p-3 rounded-xl border border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-950/30"
		>
			<h4 class="mb-2 text-sm font-medium">
				{$i18n.t('Your SOUL was edited elsewhere')}
			</h4>
			<p class="text-xs text-gray-700 dark:text-gray-300">
				{$i18n.t('The server has a newer version. Compare and choose:')}
			</p>
			<div class="mt-2 grid grid-cols-2 gap-2 text-xs">
				<div>
					<div class="mb-1 font-medium">{$i18n.t('Your version')}</div>
					<pre
						class="whitespace-pre-wrap break-all rounded-lg bg-white dark:bg-gray-900 p-2 border border-gray-100 dark:border-gray-850">{body}</pre>
				</div>
				<div>
					<div class="mb-1 font-medium">{$i18n.t('Server version')}</div>
					<pre
						class="whitespace-pre-wrap break-all rounded-lg bg-white dark:bg-gray-900 p-2 border border-gray-100 dark:border-gray-850">{conflict.current_body}</pre>
				</div>
			</div>
			<div class="mt-3 flex gap-2">
				<button
					type="button"
					class="px-3 py-1 text-xs font-medium rounded-lg bg-amber-600 text-white hover:bg-amber-700 transition"
					on:click={keepMine}
				>
					{$i18n.t('Keep mine (overwrite server)')}
				</button>
				<button
					type="button"
					class="px-3 py-1 text-xs font-medium rounded-lg bg-gray-100 dark:bg-gray-850 hover:bg-gray-200 dark:hover:bg-gray-800 transition"
					on:click={useTheirs}
				>
					{$i18n.t('Use server version')}
				</button>
			</div>
		</div>
	{/if}
</section>
