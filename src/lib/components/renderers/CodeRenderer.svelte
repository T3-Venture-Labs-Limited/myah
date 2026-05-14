<script lang="ts">
	import { onMount, onDestroy, createEventDispatcher } from 'svelte';
	import { basicSetup, EditorView } from 'codemirror';
	import { lineNumbers } from '@codemirror/view';
	import { EditorState, Compartment } from '@codemirror/state';
	import { oneDark } from '@codemirror/theme-one-dark';
	import { languages } from '@codemirror/language-data';
	import { MergeView } from '@codemirror/merge';

	import { MYAH_API_BASE_URL } from '$lib/constants';
	import ArtifactFallback from './ArtifactFallback.svelte';
	import SelectionToolbar from '$lib/components/chat/Artifacts/SelectionToolbar.svelte';
	import { artifactSelection } from '$lib/stores';
	import { formatPythonCode } from '$lib/apis/utils';
	import type { ToolbarItem, SelectionPayload } from '$lib/types/artifact';

	// Renderer Contract props
	export let file_id: string | undefined = undefined;
	export let path: string | undefined = undefined;
	export let content: Blob | string | undefined = undefined;
	export let filename: string;
	// eslint-disable-next-line @typescript-eslint/no-unused-vars
	export let mime: string | undefined = undefined;
	export let editable = true;
	// eslint-disable-next-line @typescript-eslint/no-unused-vars
	export let mtime: number | undefined = undefined;
	// When set, the renderer mounts a MergeView (CodeMirror) instead of the
	// normal editor — surfaced when the agent has modified the file while the
	// user has dirty local edits.  Spec §8.4. Phase 4B ships the component;
	// the detection logic that sets this prop is a follow-up.
	export let pendingDiff: { from: string; to: string } | undefined = undefined;

	const dispatch = createEventDispatcher<{
		select: SelectionPayload | null;
		dirty: { isDirty: boolean; diff?: string };
		discard: void;
		error: Error;
		toolbar: { items: ToolbarItem[] };
	}>();

	let editorRoot: HTMLElement;
	let mergeRoot: HTMLElement;
	let view: EditorView | null = null;
	let mergeView: MergeView | null = null;
	let originalText = '';
	let currentText = '';
	let isDirty = false;
	let cursorPos = { line: 1, col: 1 };
	let lineCount = 0;
	let loading = true;
	let errorObj: Error | null = null;
	let toolbarAnchorRect: DOMRect | null = null;

	// Local mirror of pendingDiff used by the MergeView branch — when the host
	// dispatches a conflict-resolution action ("Take Myah's", "Keep mine",
	// "Resolve manually") we clear this and re-render to fall back to the
	// normal editor.  Phase 4B MVP: callbacks just clear the diff; the host
	// integration (which knows whether to write to disk or revert) is a
	// follow-up.
	$: _activeDiff = pendingDiff;

	function _resolveTakeMyahs() {
		// Agent's content is already on disk; dismiss the warning.
		_activeDiff = undefined;
	}
	function _resolveKeepMine() {
		// User's local edits remain; the agent's update is treated as a
		// notification rather than a forced write.  The on-disk content
		// is what the agent wrote, so this is "ignore the warning."
		_activeDiff = undefined;
	}
	function _resolveManually() {
		// Drop the merge view; user can edit normally.
		_activeDiff = undefined;
	}

	// Clear the renderer-local anchor rect whenever the global selection store
	// is reset (e.g. when the host clears the selection via tab switch).
	$: if ($artifactSelection === null) toolbarAnchorRect = null;

	function selectionAnchorRect(): DOMRect | null {
		if (!view) return null;
		const sel = view.state.selection.main;
		if (sel.from === sel.to) return null;
		const startCoords = view.coordsAtPos(sel.from);
		const endCoords = view.coordsAtPos(sel.to);
		if (!startCoords || !endCoords) return null;
		const top = Math.min(startCoords.top, endCoords.top);
		const bottom = Math.max(startCoords.bottom, endCoords.bottom);
		const left = Math.min(startCoords.left, endCoords.left);
		const right = Math.max(startCoords.right, endCoords.right);
		return {
			top,
			bottom,
			left,
			right,
			width: right - left,
			height: bottom - top,
			x: left,
			y: top,
			toJSON: () => ''
		} as DOMRect;
	}

	// Compartments for hot-swapping theme + language + readonly without rebuilding state.
	const themeCompartment = new Compartment();
	const langCompartment = new Compartment();
	const readonlyCompartment = new Compartment();

	$: extension = filename.split('.').pop()?.toLowerCase() ?? '';
	$: language = languageLabelFor(extension);

	function languageLabelFor(ext: string): string {
		const map: Record<string, string> = {
			py: 'Python',
			js: 'JavaScript',
			ts: 'TypeScript',
			tsx: 'TypeScript',
			jsx: 'JavaScript',
			go: 'Go',
			rs: 'Rust',
			java: 'Java',
			cpp: 'C++',
			c: 'C',
			rb: 'Ruby',
			sh: 'Shell',
			yaml: 'YAML',
			yml: 'YAML',
			toml: 'TOML',
			md: 'Markdown',
			markdown: 'Markdown',
			json: 'JSON',
			html: 'HTML',
			css: 'CSS'
		};
		return map[ext] ?? ext.toUpperCase();
	}

	async function loadLanguageExtension(ext: string) {
		const desc = languages.find(
			(l) =>
				l.extensions.includes(ext) || l.alias.includes(ext) || l.name.toLowerCase() === ext
		);
		if (!desc) return null;
		try {
			return await desc.load();
		} catch (e) {
			console.warn(`Failed to load CM language for ${ext}:`, e);
			return null;
		}
	}

	function makeDiff(_from: string, to: string): string {
		// Minimal unified-style diff. Phase 4 ships a real diff lib; this is enough
		// for the contract.
		return `--- before\n+++ after\n${to}`;
	}

	function dispatchToolbar() {
		const items: ToolbarItem[] = [];
		if (isDirty) {
			items.push({
				placement: 'top',
				id: 'discard',
				label: 'Discard edits',
				onClick: () => dispatch('discard')
			});
		}
		items.push({
			placement: 'top',
			id: 'format',
			label: 'Format',
			onClick: format
		});
		dispatch('toolbar', { items });
	}

	function computeLineCount(text: string): number {
		// Match CodeMirror's line counting: trailing '\n' is not a separate line.
		if (text === '') return 1;
		const trimmed = text.endsWith('\n') ? text.slice(0, -1) : text;
		return trimmed.split('\n').length;
	}

	function onTextChange(newText: string) {
		currentText = newText;
		lineCount = computeLineCount(newText);
		const wasDirty = isDirty;
		isDirty = newText !== originalText;
		if (wasDirty !== isDirty) {
			dispatch('dirty', {
				isDirty,
				diff: isDirty ? makeDiff(originalText, newText) : undefined
			});
			dispatchToolbar();
		} else if (isDirty) {
			dispatch('dirty', { isDirty: true, diff: makeDiff(originalText, newText) });
		}
	}

	function onSelectionChange() {
		if (!view) return;
		const sel = view.state.selection.main;
		// Cursor with no characters selected — clear the toolbar.
		if (sel.from === sel.to) {
			dispatch('select', null);
			artifactSelection.set(null);
			toolbarAnchorRect = null;
			return;
		}
		const startLine = view.state.doc.lineAt(sel.from).number;
		const endLine = view.state.doc.lineAt(sel.to).number;
		const preview = view.state.sliceDoc(sel.from, sel.to);
		// 2026-05-05 dogfooding: single-line selections used to be silently
		// dropped to "avoid cursor noise". That broke the common case of
		// highlighting a few characters within one line — the toolbar would
		// never appear. Allow any non-empty selection through; the cursor-
		// only case is already filtered above.
		const lineSpan = endLine - startLine + 1;
		const summary =
			lineSpan === 1
				? `${filename} · L${startLine} · ${preview.length} chars`
				: `${filename} · L${startLine}-L${endLine} · ${lineSpan} lines`;
		const payload: SelectionPayload = {
			kind: 'code-lines',
			anchor: { startLine, endLine, language: extension },
			preview,
			summary
		};
		dispatch('select', payload);
		// Belt + suspenders: also write to the store directly. The host
		// (ArtifactViewer) listens to `on:select` via <svelte:component>,
		// but that forwarding is fragile across Svelte 5's `<svelte:component>`
		// rewrite. Direct store write guarantees the SelectionToolbar — which
		// reads `$artifactSelection` — re-renders even if the event never
		// reaches the host.
		artifactSelection.set(payload);
		toolbarAnchorRect = selectionAnchorRect();
	}

	async function format() {
		if (extension !== 'py' || !view) return;
		try {
			const token = typeof localStorage !== 'undefined' ? localStorage.token : '';
			const res = await formatPythonCode(token, currentText);
			const formatted = res?.code;
			if (typeof formatted === 'string' && formatted !== currentText) {
				view.dispatch({
					changes: { from: 0, to: view.state.doc.length, insert: formatted }
				});
			}
		} catch (e) {
			console.warn('Format failed:', e);
		}
	}

	async function loadContent() {
		loading = true;
		errorObj = null;
		try {
			// Resolution priority:
			// 1. Blob content → read directly (used by host pre-fetch + tests).
			// 2. file_id → fetch via /api/v1/files/{id}/content. (Important: ArtifactViewer
			//    currently passes the file_id string as the `content` prop too — preferring
			//    file_id here means we always fetch the real file in production rather than
			//    trying to render the UUID literal.)
			// 3. path → fetch via Hermes media proxy.
			// 4. Literal string content (test fixtures use this path).
			if (content instanceof Blob) {
				originalText = await content.text();
			} else if (file_id) {
				const res = await fetch(`${MYAH_API_BASE_URL}/files/${file_id}/content`, {
					credentials: 'include'
				});
				if (!res.ok) throw new Error(`HTTP ${res.status}`);
				originalText = await res.text();
			} else if (path) {
				const res = await fetch(
					`${MYAH_API_BASE_URL}/hermes/media?path=${encodeURIComponent(path)}`,
					{ credentials: 'include' }
				);
				if (!res.ok) throw new Error(`HTTP ${res.status}`);
				originalText = await res.text();
			} else if (typeof content === 'string') {
				// Literal text content (test fixtures); reachable when no file_id/path.
				originalText = content;
			}
			currentText = originalText;
			lineCount = computeLineCount(originalText);
		} catch (e) {
			console.error('Error loading code file:', e);
			errorObj = e instanceof Error ? e : new Error(String(e));
			dispatch('error', errorObj);
			loading = false;
			return;
		}
		loading = false;
	}

	function isDarkMode(): boolean {
		if (typeof document === 'undefined') return false;
		return document.documentElement.classList.contains('dark');
	}

	let darkObserver: MutationObserver | null = null;

	onMount(async () => {
		await loadContent();
		if (errorObj) return;

		const langExt = await loadLanguageExtension(extension);

		// Diff-overlay branch: mount @codemirror/merge MergeView when a
		// pendingDiff is present.  Spec §8.4.
		if (_activeDiff && mergeRoot) {
			mergeView = new MergeView({
				a: { doc: _activeDiff.from },
				b: { doc: _activeDiff.to },
				parent: mergeRoot
			});
			loading = false;
			return;
		}

		view = new EditorView({
			state: EditorState.create({
				doc: originalText,
				extensions: [
					basicSetup,
					lineNumbers(),
					langCompartment.of(langExt ?? []),
					themeCompartment.of(isDarkMode() ? oneDark : []),
					readonlyCompartment.of(EditorState.readOnly.of(!editable)),
					EditorView.editable.of(editable),
					EditorView.updateListener.of((update) => {
						if (update.docChanged) {
							onTextChange(update.state.doc.toString());
						}
						if (update.selectionSet) {
							onSelectionChange();
							const head = update.state.selection.main.head;
							const line = update.state.doc.lineAt(head);
							cursorPos = { line: line.number, col: head - line.from + 1 };
						}
					})
				]
			}),
			parent: editorRoot
		});

		dispatchToolbar();

		// MutationObserver mirrors CodeEditor.svelte:170 — re-applies theme
		// when the dark class toggles on <html>.
		if (typeof document !== 'undefined') {
			darkObserver = new MutationObserver(() => {
				view?.dispatch({
					effects: themeCompartment.reconfigure(isDarkMode() ? oneDark : [])
				});
			});
			darkObserver.observe(document.documentElement, {
				attributes: true,
				attributeFilter: ['class']
			});
		}

	});

	onDestroy(() => {
		darkObserver?.disconnect();
		view?.destroy();
		mergeView?.destroy();
	});
</script>

{#if loading}
	<div class="flex items-center justify-center py-8 text-sm text-gray-500">Loading…</div>
{:else if errorObj}
	<ArtifactFallback
		error={errorObj}
		{filename}
		file_id={typeof content === 'string' ? content : file_id}
		{path}
		onRetry={loadContent}
	/>
{:else if _activeDiff}
	<div class="flex flex-col h-full relative" data-testid="merge-view">
		<div
			class="border-b border-orange-200 dark:border-orange-800 bg-orange-50 dark:bg-orange-900/20 px-3 py-2 text-sm flex items-center gap-2"
		>
			<strong>{filename}</strong>
			<span class="text-xs text-orange-700 dark:text-orange-300">Conflict resolution</span>
		</div>
		<div bind:this={mergeRoot} class="flex-1 overflow-auto"></div>
		<div
			class="border-t border-gray-100 dark:border-gray-800 px-3 py-2 text-xs flex items-center gap-2"
		>
			<button
				class="px-2 py-1 rounded bg-orange-100 dark:bg-orange-800"
				on:click={_resolveTakeMyahs}
			>
				Take Myah's
			</button>
			<button
				class="px-2 py-1 rounded bg-gray-100 dark:bg-gray-800"
				on:click={_resolveKeepMine}
			>
				Keep mine
			</button>
			<button class="px-2 py-1 rounded text-gray-600 dark:text-gray-300" on:click={_resolveManually}>
				Resolve manually
			</button>
		</div>
	</div>
{:else}
	<div class="flex flex-col h-full relative">
		<div bind:this={editorRoot} class="flex-1 overflow-auto"></div>
		<SelectionToolbar placement="floating" anchorRect={toolbarAnchorRect} {filename} />
		<div
			data-testid="code-status-bar"
			class="border-t border-gray-100 dark:border-gray-800 px-3 py-1 text-xs flex items-center gap-3 text-gray-500 dark:text-gray-400 font-mono"
		>
			<span>{language}</span>
			<span>UTF-8</span>
			<span>LF</span>
			<span class="ml-auto">Ln {cursorPos.line}, Col {cursorPos.col}</span>
			<span>{lineCount} lines</span>
			{#if isDirty}<span class="text-orange-500" title="Unsaved edits">●</span>{/if}
		</div>
	</div>
{/if}
