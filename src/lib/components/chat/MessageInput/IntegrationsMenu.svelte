<script lang="ts">
	// OSS-mode stub for the IntegrationsMenu.
	//
	// The real component lives in platform-hosted/ and renders the
	// Composio-backed integrations dropdown (Slack / Gmail / GitHub /
	// Linear / Notion / etc.). It's a hosted-only feature; the OSS
	// variant has no Composio.
	//
	// platform-oss/.../chat/MessageInput.svelte:70 imports this file by
	// path (``./MessageInput/IntegrationsMenu.svelte``). Without this
	// stub, vite/rollup can't resolve the import and ``npm run build``
	// fails — that was launch-blocker F0 in
	// docs/oss-launch/vm-testing-followups.md.
	//
	// The hosted Docker overlay (platform-hosted/Dockerfile lines 39-42)
	// copies platform-hosted/src/ on top of this file at build time, so
	// hosted gets the real component. OSS users just don't see the
	// integrations button in the message input toolbar.
	//
	// Props mirror the real component's signature so the parent's
	// ``<IntegrationsMenu ...>`` invocation in MessageInput.svelte
	// type-checks regardless of which variant is built. Most are
	// unused here — they're declared so svelte-check / TS don't
	// complain about unknown props on the OSS instance.

	// eslint-disable-next-line @typescript-eslint/no-unused-vars
	export let selectedToolIds: string[] = [];
	// eslint-disable-next-line @typescript-eslint/no-unused-vars
	export let selectedModels: string[] = [];
	// eslint-disable-next-line @typescript-eslint/no-unused-vars
	export let fileUploadCapableModels: string[] = [];
	// eslint-disable-next-line @typescript-eslint/no-unused-vars
	export let showWebSearchButton = false;
	// eslint-disable-next-line @typescript-eslint/no-unused-vars
	export let webSearchEnabled = false;
	// eslint-disable-next-line @typescript-eslint/no-unused-vars
	export let onClose: (() => void) | (() => Promise<void>) = () => {};
	// eslint-disable-next-line @typescript-eslint/no-unused-vars
	export let closeOnOutsideClick = true;
</script>

<!--
	OSS-mode stub: renders nothing.

	The parent passes its trigger button via the default <slot/>. We
	deliberately do NOT render the slot — the integrations entry-point
	should be absent in OSS, not present-but-inert. The hosted overlay
	swaps in the real component (which renders the slot inside a
	Dropdown) at Docker build time.

	Mark the props as referenced (without rendering) so svelte-check
	doesn't warn about unused exports.
-->
{#if false}
	<span>{selectedToolIds.length}{selectedModels.length}{fileUploadCapableModels.length}{showWebSearchButton}{webSearchEnabled}{closeOnOutsideClick}{typeof onClose}</span>
{/if}
