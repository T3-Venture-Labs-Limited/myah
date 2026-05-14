<script lang="ts">
	import Bug from '$lib/components/icons/Bug.svelte';
	import { openSentryFeedback } from '$lib/utils/sentryFeedback';
	import { mobile, showSidebar } from '$lib/stores';
	import { env } from '$env/dynamic/public';
	import { getContext } from 'svelte';

	const i18n = getContext('i18n');

	export let variant: 'floating' | 'collapsed' | 'expanded' = 'floating';

	// Only render when the Sentry DSN is configured. OSS builds ship with no
	// DSN; rendering a button that no-ops on click is a phantom UI element.
	// Hosted builds inject PUBLIC_SENTRY_DSN at image build time so this is
	// non-empty in production and the button renders normally.
	const hasSentryDsn = Boolean(env.PUBLIC_SENTRY_DSN);

	let isHovered = false;
	let isLoading = false;

	async function handleClick() {
		if (isLoading) return;
		isLoading = true;
		if ($mobile) showSidebar.set(false);
		try {
			await openSentryFeedback();
		} catch (err) {
			console.error('[sentry] failed to open feedback form:', err);
		} finally {
			isLoading = false;
		}
	}
</script>

{#if !hasSentryDsn}
	<!-- OSS build with no PUBLIC_SENTRY_DSN — nothing to render. -->
{:else if variant === 'floating'}
	<button
		type="button"
		class="sentry-feedback-trigger"
		on:click={handleClick}
		on:mouseenter={() => (isHovered = true)}
		on:mouseleave={() => (isHovered = false)}
		aria-label={$i18n.t('Report a bug')}
		disabled={isLoading}
	>
		<span class="icon-wrapper">
			<Bug className="size-4" strokeWidth="1.5" />
		</span>
		<span class="label" class:visible={isHovered}>{$i18n.t('Report a bug')}</span>
	</button>
{:else if variant === 'collapsed'}
	<button
		type="button"
		class="cursor-pointer flex rounded-xl hover:bg-gray-100 dark:hover:bg-gray-850 transition group"
		on:click={handleClick}
		aria-label={$i18n.t('Report a bug')}
		disabled={isLoading}
	>
		<div class="self-center flex items-center justify-center size-9">
			<Bug className="size-4.5" strokeWidth="1.5" />
		</div>
	</button>
{:else if variant === 'expanded'}
	<div class="flex justify-center text-gray-800 dark:text-gray-200">
		<button
			type="button"
			class="group grow flex items-center space-x-3 rounded-2xl px-2.5 py-2 hover:bg-gray-100 dark:hover:bg-gray-900 transition outline-none"
			on:click={handleClick}
			aria-label={$i18n.t('Report a bug')}
			disabled={isLoading}
		>
			<div class="self-center">
				<Bug className="size-4.5" strokeWidth="2" />
			</div>
			<div class="flex flex-1 self-center translate-y-[0.5px]">
				<div class="self-center text-sm font-primary">{$i18n.t('Report a bug')}</div>
			</div>
		</button>
	</div>
{/if}

<style>
	.sentry-feedback-trigger {
		position: fixed;
		bottom: 24px;
		right: 24px;
		z-index: 45;
		display: flex;
		align-items: center;
		gap: 0;
		padding: 0;
		width: 40px;
		height: 40px;
		border-radius: 20px;
		border: 1px solid #e5e5e5;
		background: #ffffff;
		color: #171717;
		cursor: pointer;
		transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
		overflow: hidden;
		white-space: nowrap;
		box-shadow: 0px 2px 8px rgba(0, 0, 0, 0.08);
	}

	.sentry-feedback-trigger:hover {
		width: 152px;
		gap: 6px;
		padding: 0 14px 0 10px;
		box-shadow: 0px 4px 16px rgba(0, 0, 0, 0.12);
	}

	.sentry-feedback-trigger:active {
		transform: scale(0.96);
	}

	.icon-wrapper {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 40px;
		height: 40px;
		flex-shrink: 0;
	}

	.label {
		font-size: 13px;
		font-weight: 500;
		opacity: 0;
		transform: translateX(-4px);
		transition: all 0.2s ease;
		flex-shrink: 0;
	}

	.label.visible {
		opacity: 1;
		transform: translateX(0);
	}

	:global(.dark) .sentry-feedback-trigger {
		background: #141414;
		border-color: #2a2a2a;
		color: #fafafa;
		box-shadow: 0px 2px 8px rgba(0, 0, 0, 0.3);
	}

	:global(.dark) .sentry-feedback-trigger:hover {
		box-shadow: 0px 4px 16px rgba(0, 0, 0, 0.5);
	}
</style>
