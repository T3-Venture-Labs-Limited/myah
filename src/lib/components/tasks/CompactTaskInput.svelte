<!-- CompactTaskInput.svelte -->
<!-- A focused entry point — collapsed to a whisper, expanded to a full voice. -->
<script lang="ts">
	import { getContext, tick } from 'svelte';
	import { slide } from 'svelte/transition';
	import { goto } from '$app/navigation';
	import { models, settings } from '$lib/stores';

	const i18n = getContext('i18n');

	let expanded = false;
	let prompt = '';
	let textarea: HTMLTextAreaElement;
	let container: HTMLDivElement;
	let selectedModelId = '';

	// Prevent the window click from collapsing immediately after expand
	let justExpanded = false;

	$: firstModel = $models?.[0]?.id ?? '';
	$: if (!selectedModelId && firstModel) {
		selectedModelId = $settings?.models?.[0] ?? firstModel;
	}

	async function expand() {
		if (expanded) return;
		justExpanded = true;
		expanded = true;
		await tick();
		textarea?.focus();
		// Allow window clicks to collapse after a short delay
		setTimeout(() => {
			justExpanded = false;
		}, 200);
	}

	function collapse() {
		if (prompt.trim()) return;
		expanded = false;
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			prompt = '';
			expanded = false;
		} else if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			submit();
		}
	}

	function submit() {
		const q = prompt.trim();
		if (!q) return;
		prompt = '';
		expanded = false;
		// Navigate to /tasks with ?q= — the tasks page renders an embedded Chat
		// that auto-submits the prompt, keeping the task list panel visible.
		goto(`/tasks?q=${encodeURIComponent(q)}`);
	}

	function handleWindowClick(e: MouseEvent) {
		if (!expanded || justExpanded) return;
		if (container && !container.contains(e.target as Node)) {
			collapse();
		}
	}

	function autoResize(el: HTMLTextAreaElement) {
		el.style.height = 'auto';
		el.style.height = Math.min(el.scrollHeight, 120) + 'px';
	}
</script>

<svelte:window on:mousedown={handleWindowClick} />

<div
	bind:this={container}
	class="flex-shrink-0 px-3 pb-3 border-b border-gray-100 dark:border-gray-850"
>
	{#if expanded}
		<!-- Expanded state: textarea + bottom bar -->
		<div
			transition:slide={{ duration: 150 }}
			class="bg-gray-50 dark:bg-gray-900 rounded-xl border border-gray-300 dark:border-gray-700 overflow-hidden"
		>
			<textarea
				bind:this={textarea}
				bind:value={prompt}
				on:keydown={handleKeydown}
				on:input={(e) => autoResize(e.currentTarget)}
				placeholder={$i18n.t('Start a task...')}
				rows="2"
				class="w-full px-3 pt-3 pb-1 text-sm bg-transparent outline-none resize-none text-gray-800 dark:text-gray-200 placeholder-gray-400 dark:placeholder-gray-500 min-h-[52px] max-h-[120px]"
			></textarea>

			<!-- Bottom bar -->
			<div class="flex items-center gap-1.5 px-2 pb-2">
				<div class="relative flex-1 min-w-0">
					<select
						bind:value={selectedModelId}
						class="appearance-none w-full max-w-[140px] px-2 py-1 text-xs rounded-lg bg-gray-200 dark:bg-gray-800 text-gray-600 dark:text-gray-400 outline-none cursor-pointer hover:bg-gray-300 dark:hover:bg-gray-700 transition truncate pr-5"
					>
						{#each $models ?? [] as model}
							<option value={model.id}>{model.name}</option>
						{/each}
					</select>
					<svg
						class="pointer-events-none absolute right-1 top-1/2 -translate-y-1/2 size-3 text-gray-400"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
						stroke-width="2"
					>
						<path stroke-linecap="round" stroke-linejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
					</svg>
				</div>

				<div class="flex items-center gap-1 ml-auto">
					<button
						type="button"
						disabled={!prompt.trim()}
						class="p-1.5 rounded-lg transition {prompt.trim()
							? 'bg-gray-900 dark:bg-white text-white dark:text-gray-900 hover:opacity-80'
							: 'bg-gray-200 dark:bg-gray-800 text-gray-400 cursor-not-allowed'}"
						aria-label={$i18n.t('Submit')}
						on:click={submit}
					>
						<svg
							class="size-3.5"
							fill="none"
							viewBox="0 0 24 24"
							stroke="currentColor"
							stroke-width="2.5"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								d="M4.5 10.5 12 3m0 0 7.5 7.5M12 3v18"
							/>
						</svg>
					</button>
				</div>
			</div>
		</div>
	{:else}
		<!-- Collapsed state: single-line pill -->
		<!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
		<div
			class="flex items-center gap-2 px-3 py-2.5 bg-gray-50 dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 hover:border-gray-300 dark:hover:border-gray-700 cursor-text transition"
			on:click={expand}
		>
			<span class="flex-1 text-sm text-gray-400 dark:text-gray-500 select-none">
				{$i18n.t('Start a task...')}
			</span>
			<svg
				class="size-4 text-gray-400 dark:text-gray-500 flex-shrink-0"
				fill="none"
				viewBox="0 0 24 24"
				stroke="currentColor"
				stroke-width="1.5"
			>
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09Z"
				/>
			</svg>
		</div>
	{/if}
</div>
