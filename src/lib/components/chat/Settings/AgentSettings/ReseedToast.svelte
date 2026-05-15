<script lang="ts">
	import { onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { getLastReseed } from '$lib/apis/agent-config';

	onMount(async () => {
		try {
			const info = await getLastReseed(localStorage.token);
			if (!info) return;
			const acknowledged = localStorage.getItem('reseed-ack') ?? '';
			if (acknowledged === info.timestamp) return;
			// Defensive: older agent containers wrote `files` as a
			// space-separated string. Normalise to an array before joining.
			// See e2e-output/report.md ISSUE-009.
			const files: string[] = Array.isArray(info.files)
				? info.files
				: typeof info.files === 'string'
					? (info.files as string).split(/\s+/).filter(Boolean)
					: [];
			toast.info(
				`Your agent's defaults were updated — ${files.join(' and ')} customizations were refreshed.`,
				{ duration: 10000 }
			);
			localStorage.setItem('reseed-ack', info.timestamp);
		} catch {
			// Silent failure — not critical
		}
	});
</script>
