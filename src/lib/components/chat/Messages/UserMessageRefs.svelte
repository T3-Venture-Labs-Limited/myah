<script lang="ts">
	// What was attached, made visible.
	// Renders the selection chips that the user added to a message via the
	// SelectionToolbar's "+ Add to chat" button. Mirrors the composer-side
	// RefChip styling so the chat history reads like a continuation of the
	// composer state — same colour for the same kind, same shape, same
	// summary string. Click expands the preview inline so the user can see
	// exactly what they referenced without re-opening the file.
	import type { SelectionPayload } from '$lib/types/artifact';
	import { openArtifactInPane } from '$lib/stores';

	type StoredRef = SelectionPayload & {
		id: string;
		filename: string;
		file_key?: string;
		file_id?: string;
		path?: string;
	};

	export let refs: StoredRef[] = [];
	// Match the composer's ref-bar alignment (right-aligned for chat-bubble
	// layouts) so the chips visually trace back to the input that produced
	// them.
	export let align: 'start' | 'end' = 'end';

	let expanded = new Set<string>();

	function toggle(id: string) {
		const next = new Set(expanded);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		expanded = next;
	}

	function kindClasses(kind: SelectionPayload['kind']): string {
		switch (kind) {
			case 'doc-text':
			case 'code-lines':
				return 'bg-pink-100 dark:bg-pink-900/30 text-pink-900 dark:text-pink-100 border-pink-200 dark:border-pink-800';
			case 'sheet-cells':
				return 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-900 dark:text-emerald-100 border-emerald-200 dark:border-emerald-800';
			case 'image-region':
			case 'video-region':
				return 'bg-sky-100 dark:bg-sky-900/30 text-sky-900 dark:text-sky-100 border-sky-200 dark:border-sky-800';
			default:
				return 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-200 border-gray-200 dark:border-gray-700';
		}
	}

	function previewText(ref: StoredRef): string {
		if (ref.kind === 'doc-text' || ref.kind === 'code-lines') {
			return String(ref.preview ?? '');
		}
		if (ref.kind === 'sheet-cells') {
			return ref.preview.map((row) => row.join('\t')).join('\n');
		}
		return '';
	}

	function openSource(ref: StoredRef) {
		// Best-effort: re-open the source file in the artifact pane. Refs
		// captured at send time may not carry file_id/path (older shapes); in
		// that case nothing happens — the chip stays informational.
		const fileKey = ref.file_key;
		const file_id = ref.file_id;
		const path = ref.path;
		if (!fileKey && !file_id && !path) return;
		openArtifactInPane({
			file_key: fileKey ?? (file_id ? `file_id:${file_id}` : `path:${path ?? ''}`),
			file_id,
			path,
			filename: ref.filename,
			source: 'user-click'
		});
	}
</script>

{#if refs && refs.length > 0}
	<div
		data-testid="user-message-refs"
		class="flex flex-col gap-1 mb-1 {align === 'end' ? 'items-end' : 'items-start'}"
	>
		{#each refs as ref (ref.id)}
			<div class="flex flex-col gap-1 max-w-[90%] min-w-0">
				<button
					type="button"
					class="self-{align} inline-flex items-center gap-1.5 px-2 py-0.5 text-xs rounded-full border {kindClasses(
						ref.kind
					)} hover:opacity-80 transition"
					title="Click to view in artifact pane · double-click to expand inline"
					on:click={() => openSource(ref)}
					on:dblclick={(e) => {
						e.preventDefault();
						toggle(ref.id);
					}}
				>
					<span class="font-mono truncate max-w-[180px]">{ref.filename}</span>
					<span class="opacity-70">·</span>
					<span class="opacity-90 truncate max-w-[280px]">{ref.summary}</span>
				</button>
				{#if expanded.has(ref.id) && previewText(ref)}
					<pre
						class="text-[11px] font-mono rounded-md bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 p-2 overflow-auto max-h-48 whitespace-pre-wrap break-all m-0 self-{align}"
					>{previewText(ref)}</pre>
				{/if}
			</div>
		{/each}
	</div>
{/if}
