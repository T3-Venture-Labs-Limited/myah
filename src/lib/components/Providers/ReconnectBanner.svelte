<script lang="ts">
	import { goto } from '$app/navigation';
	import { reconnectNeeded } from '$lib/stores/providers';

	const DISMISS_KEY = 'myah.reconnect.dismissed_until';

	function dismissedUntilNow(): boolean {
		try {
			const until = Number(localStorage.getItem(DISMISS_KEY) ?? 0);
			return Date.now() < until;
		} catch {
			return false;
		}
	}

	function dismiss() {
		try {
			localStorage.setItem(DISMISS_KEY, String(Date.now() + 24 * 60 * 60 * 1000));
		} catch {
			// ignore
		}
		visible = false;
	}

	let visible = !dismissedUntilNow();
	$: if ($reconnectNeeded.length === 0) visible = false;
</script>

{#if visible && $reconnectNeeded.length > 0}
	<div
		class="px-4 py-2 bg-amber-100 dark:bg-amber-950/40 text-amber-900 dark:text-amber-200 text-sm flex items-center justify-between"
	>
		<span>
			Reconnect {$reconnectNeeded.map((r) => r.providerId).join(', ')} to restore chat.
		</span>
		<div class="flex gap-2">
			<button class="underline" on:click={() => goto('/settings?pane=providers')}>Reconnect</button>
			<button class="opacity-70" on:click={dismiss}>Dismiss</button>
		</div>
	</div>
{/if}
