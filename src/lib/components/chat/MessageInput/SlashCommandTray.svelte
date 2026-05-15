<script lang="ts">
	import Fuse from 'fuse.js';

	import { agentCommands } from '$lib/stores';
	import type { AgentCommand } from '$lib/types';

	let {
		query = '',
		openUpward = false,
		onSelect = (_command: AgentCommand) => {},
		onClose = () => {}
	}: {
		query: string;
		openUpward?: boolean;
		onSelect: (command: AgentCommand) => void;
		onClose: () => void;
	} = $props();

	let activeIdx = $state(0);
	let trayListEl: HTMLDivElement | undefined = $state();

	$effect(() => {
		query;
		activeIdx = 0;
	});

	let fuse = new Fuse($agentCommands, {
		keys: [
			{ name: 'name', weight: 2 },
			{ name: 'aliases', weight: 1.5 },
			{ name: 'description', weight: 1 }
		],
		threshold: 0.5,
		ignoreLocation: true
	});

	$effect(() => {
		$agentCommands;
		fuse = new Fuse($agentCommands, {
			keys: [
				{ name: 'name', weight: 2 },
				{ name: 'aliases', weight: 1.5 },
				{ name: 'description', weight: 1 }
			],
			threshold: 0.5,
			ignoreLocation: true
		});
	});

	let filtered: AgentCommand[] = $derived(
		query
			? fuse.search(query).map((r) => r.item)
			: [...$agentCommands].sort((a, b) => a.name.localeCompare(b.name))
	);

	let matchCount = $derived(filtered.length);

	function scrollToActive() {
		const el = trayListEl?.querySelector(`[data-active="true"]`);
		el?.scrollIntoView({ block: 'nearest', behavior: 'instant' });
	}

	export function handleKeydown(e: KeyboardEvent): boolean {
		if (!filtered.length) {
			if (e.key === 'Escape') {
				onClose();
				return true;
			}
			return false;
		}

		if (e.key === 'ArrowDown') {
			e.preventDefault();
			activeIdx = (activeIdx + 1) % filtered.length;
			scrollToActive();
			return true;
		}
		if (e.key === 'ArrowUp') {
			e.preventDefault();
			activeIdx = (activeIdx - 1 + filtered.length) % filtered.length;
			scrollToActive();
			return true;
		}
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			const cmd = filtered[activeIdx];
			if (cmd) onSelect(cmd);
			return true;
		}
		if (e.key === 'Tab') {
			e.preventDefault();
			const cmd = filtered[activeIdx];
			if (cmd) onSelect(cmd);
			return true;
		}
		if (e.key === 'Escape') {
			e.preventDefault();
			onClose();
			return true;
		}
		return false;
	}
</script>

<div class="absolute left-0 right-0 z-50 {openUpward ? 'bottom-[calc(100%-1px)]' : 'top-full'}">
	<div
		class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 shadow-2xl overflow-hidden {openUpward ? 'border-b-0 rounded-t-2xl animate-slide-up' : 'border-t-0 rounded-b-2xl animate-slide-down'}"
	>
		<div class="flex items-center justify-between px-3 py-1.5">
			<span class="text-[13px] text-gray-500 dark:text-gray-400 uppercase tracking-wider">Commands</span>
			<span class="text-[11px] font-mono text-gray-400 dark:text-gray-500">{matchCount} match{matchCount === 1 ? '' : 'es'}</span>
		</div>

		<div class="max-h-[240px] overflow-y-auto scrollbar-thin px-1 pb-1" bind:this={trayListEl}>
			{#if filtered.length > 0}
				{#each filtered as cmd, idx (cmd.name)}
					<button
						type="button"
						class="w-full text-left flex flex-col gap-0.5 px-2.5 py-1.5 rounded-lg cursor-pointer transition-colors duration-150 hover:bg-gray-100 dark:hover:bg-gray-800 {idx === activeIdx ? 'bg-gray-100 dark:bg-gray-800' : ''}"
						data-active={idx === activeIdx ? 'true' : 'false'}
						onmousemove={() => {
							activeIdx = idx;
						}}
						onclick={() => onSelect(cmd)}
					>
						<div class="flex items-center gap-1.5 flex-wrap">
							<span class="font-mono text-[13px] font-medium text-gray-900 dark:text-gray-100">/{cmd.name}</span>
							{#if cmd.args}
								<span class="font-mono text-[11px] text-gray-400 dark:text-gray-500">{cmd.args}</span>
							{/if}
							{#if cmd.source === 'skill'}
								<span class="text-[9px] px-1 py-0.5 rounded font-medium bg-blue-50 dark:bg-blue-500/10 text-blue-600 dark:text-blue-400">skill</span>
							{/if}
							{#if cmd.bypass}
								<span class="text-[11px]" title="Instant command">⚡</span>
							{/if}
						</div>
						{#if cmd.description}
							<div class="text-[11px] text-gray-600 dark:text-gray-400 line-clamp-1">{cmd.description}</div>
						{/if}
					</button>
				{/each}
			{:else}
				<div class="py-5 px-4 text-center text-[12px] text-gray-500 dark:text-gray-500">No commands match.</div>
			{/if}
		</div>

		<div class="flex items-center justify-between px-3 py-1 border-t border-gray-100 dark:border-gray-800">
			<div class="flex items-center gap-2">
				<span class="inline-flex items-center gap-1">
					<kbd class="font-mono text-[9px] px-1 py-0.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded text-gray-600 dark:text-gray-400">↑</kbd>
					<kbd class="font-mono text-[9px] px-1 py-0.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded text-gray-600 dark:text-gray-400">↓</kbd>
					<span class="text-[10px] text-gray-500 dark:text-gray-500">navigate</span>
				</span>
				<span class="inline-flex items-center gap-1">
					<kbd class="font-mono text-[9px] px-1 py-0.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded text-gray-600 dark:text-gray-400">↵</kbd>
					<span class="text-[10px] text-gray-500 dark:text-gray-500">select</span>
				</span>
				<span class="inline-flex items-center gap-1">
					<kbd class="font-mono text-[9px] px-1 py-0.5 bg-gray-100 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded text-gray-600 dark:text-gray-400">Esc</kbd>
					<span class="text-[10px] text-gray-500 dark:text-gray-500">close</span>
				</span>
			</div>
		</div>
	</div>
</div>

<style>
	@keyframes slide-down {
		from {
			opacity: 0;
			transform: translateY(-8px) scale(0.98);
		}
		to {
			opacity: 1;
			transform: translateY(0) scale(1);
		}
	}
	.animate-slide-down {
		animation: slide-down 0.2s cubic-bezier(0.16, 1, 0.3, 1);
		transform-origin: top center;
	}
	@keyframes slide-up {
		from {
			opacity: 0;
			transform: translateY(12px) scale(0.98);
		}
		to {
			opacity: 1;
			transform: translateY(0) scale(1);
		}
	}
	.animate-slide-up {
		animation: slide-up 0.2s cubic-bezier(0.16, 1, 0.3, 1);
		transform-origin: bottom center;
	}
</style>
